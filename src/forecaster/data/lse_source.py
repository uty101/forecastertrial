"""London Strategic Edge — the options chain, and what the market thinks the move is.

The point of this source is one number the rest of the system cannot produce: a
**market-priced expected move** for the quarter being forecast. Everything else
we know about dispersion comes from our own backtest residuals and from analyst
disagreement, which are both our own opinion measured two ways. An option
straddle is somebody putting money on the size of the move.

That feeds two places — `h_lambda`, which already conditions lambda on
dispersion, and `v3_calibrate`, whose distribution width currently rests on our
residuals alone.

**It is live-only, and that is enforced rather than documented.** The chain
endpoint accepts `as_of`, `date` and `start`/`end` and IGNORES all three —
verified: every variant returns the identical 3,945 rows. And the underlying
dataset only begins 2026-06-11, so there is no depth to backtest against even if
the parameter worked. A historical `as_of` therefore returns None here instead
of today's chain, because serving a current option price into a backtest of a
past quarter would leak the answer in the most direct way available: the market
already knows what happened.

The consequence is worth stating plainly. A dispersion input that cannot be
backtested cannot be part of what lambda was fitted on, so this informs the day
and must not silently become a fitted parameter.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from forecaster.data.cache import Cache

log = structlog.get_logger()

_MIN_REQUEST_INTERVAL_S = 0.2
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# The chain is a snapshot of now. Anything older than this is a different
# market, and pretending otherwise is the leak this module exists to refuse.
LIVE_TOLERANCE_DAYS = 3


class _TransientLSE(RuntimeError):
    """Worth retrying. 4xx is not — a bad key or a spent quota is permanent."""


class LSESource:
    name = "lse"
    priority = 45

    def __init__(self, api_key: str, base_url: str, cache: Cache) -> None:
        if not api_key or not base_url:
            raise ValueError("LSESource needs LSE_API_KEY and LSE_BASE_URL.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self._client = None
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------ #

    @retry(
        retry=retry_if_exception_type(_TransientLSE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(self, path: str, **params: Any) -> Any | None:
        import httpx

        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    headers={"x-api-key": self.api_key}, timeout=60.0
                )
            elapsed = time.monotonic() - self._last_request
            if elapsed < _MIN_REQUEST_INTERVAL_S:
                time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
            self._last_request = time.monotonic()

        response = self._client.get(f"{self.base_url}/{path}", params=params)
        if response.status_code in _RETRY_STATUSES:
            raise _TransientLSE(f"{response.status_code} from {path}")
        if 400 <= response.status_code < 500:
            log.error(
                "lse_unavailable",
                path=path, status=response.status_code, detail=response.text[:200],
            )
            return None
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------ #

    def get_options_chain(self, underlying: str, as_of: date) -> list[dict] | None:
        """The current chain, or None if `as_of` is not current.

        The refusal is the important part. The endpoint silently ignores every
        date parameter it accepts, so a backtest asking for May's chain would be
        handed today's — priced with full knowledge of the quarter it is trying
        to forecast. Returning None loses a lens; returning today's chain
        invents a forecaster that already knew.
        """
        stale = (date.today() - as_of).days
        if stale > LIVE_TOLERANCE_DAYS:
            log.info(
                "lse_chain_refused",
                underlying=underlying, as_of=as_of.isoformat(), stale_days=stale,
                why="chain is a live snapshot and ignores date parameters",
            )
            return None

        key = self.cache.key("lse_chain", as_of, underlying=underlying)
        rows = self.cache.fetch(
            key, lambda: self._get("options/chain", underlying=underlying)
        )
        return rows or None

    def implied_move(
        self, underlying: str, as_of: date, on_or_after: date
    ) -> dict | None:
        """The market's expected move over the first expiry on or after a date.

        Straddle rather than implied volatility, because the straddle is what
        somebody actually paid. An at-the-money call plus put priced together is
        the cost of being wrong in either direction, and dividing by spot turns
        it into the percentage move the market is charging for.

        Pass the earnings date as `on_or_after`: the expiry that brackets a
        print is the one carrying the event premium, and an expiry before it
        prices an ordinary week.
        """
        chain = self.get_options_chain(underlying, as_of)
        if not chain:
            return None

        target = min(
            (row["expiry"] for row in chain if row.get("expiry")
             and date.fromisoformat(row["expiry"]) >= on_or_after),
            default=None,
        )
        if target is None:
            log.info("lse_no_expiry", underlying=underlying, after=str(on_or_after))
            return None

        at_expiry = [r for r in chain if r.get("expiry") == target
                     and r.get("last_price") and r.get("underlying_price")]
        if not at_expiry:
            return None

        spot = at_expiry[0]["underlying_price"]
        # Nearest strike to spot that has BOTH legs — a lone call prices a
        # direction, not a move.
        by_strike: dict[float, dict[str, dict]] = {}
        for row in at_expiry:
            by_strike.setdefault(row["strike"], {})[row["contract_type"]] = row
        paired = [
            (abs(strike - spot), strike, legs)
            for strike, legs in by_strike.items()
            if "call" in legs and "put" in legs
        ]
        if not paired:
            log.info("lse_no_straddle", underlying=underlying, expiry=target)
            return None

        _, strike, legs = min(paired)
        straddle = legs["call"]["last_price"] + legs["put"]["last_price"]
        ivs = [legs[side].get("iv") for side in ("call", "put")]
        ivs = [v for v in ivs if v]

        result = {
            "underlying": underlying,
            "expiry": target,
            "strike": strike,
            "spot": spot,
            "straddle": straddle,
            "implied_move_pct": straddle / spot if spot else None,
            "atm_iv": sum(ivs) / len(ivs) if ivs else None,
            "dte": legs["call"].get("dte"),
            "as_of": as_of.isoformat(),
        }
        log.info("lse_implied_move", **{k: result[k] for k in
                 ("underlying", "expiry", "strike", "implied_move_pct", "atm_iv")})
        return result

    def get_insider_trades(
        self, ticker: str, as_of: date, limit: int = 200
    ) -> list[dict] | None:
        """Form 4 filings — 23 years of them, and unlike the chain, dated.

        Kept deliberately separate from the chain: this one CAN be backtested,
        because every row carries the date it was filed.
        """
        key = self.cache.key("lse_insider", as_of, ticker=ticker, limit=limit)
        rows = self.cache.fetch(
            key,
            lambda: self._get(
                "series", dataset="insider_trades", symbol=ticker,
                end=as_of.isoformat(), limit=limit,
            ),
        )
        return rows or None

    # ------------------------------------------------------------------ #
    # DataSource protocol — this source answers none of the standard calls.
    # ------------------------------------------------------------------ #

    def get_consensus(self, ticker: str, as_of: date):
        return None

    def get_actuals(self, ticker: str, period: str, as_of: date):
        return None

    def get_guidance(self, ticker: str, as_of: date):
        return None

    def get_filings(self, ticker: str, as_of: date, forms: list[str],
                    limit: int = 10, items: str | None = None):
        return None

    def get_transcript(self, ticker: str, as_of: date):
        return None

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None

    def get_macro(self, series_ids: list[str], as_of: date):
        return None
