"""The adapter written on the day — the only genuinely new code on 16 August.

This file is a working template with the shape already decided, so that at 10:30
the job is filling in three or four methods against a feed you have just seen,
not designing an interface under time pressure.

**Every method may return None.** That is what makes this cheap: a sponsor
adapter that only implements `get_consensus` is still useful, because the loader
falls through to yfinance and SEC for everything else. You are never blocked on
making it complete, and a half-working adapter written in twenty minutes beats a
complete one written in ninety.

**Priority 1** puts it ahead of yfinance and SEC. `get_consensus` is resolved
with `cross_check=True`, so when the sponsor's consensus and yfinance's disagree
the loader records it rather than picking silently — and that disagreement is
usually a GAAP/non-GAAP basis mismatch, which is a finding worth catching before
it becomes a systematic one-directional error.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog

from forecaster.data.cache import Cache
from forecaster.data.protocol import assert_point_in_time
from forecaster.schemas import Basis, Claim, Consensus, Guidance, Source, SourceKind

log = structlog.get_logger()


class SponsorSource:
    """Fill in `_fetch` and whichever getters their feed actually improves."""

    name = "sponsor"
    priority = 1  # ahead of everything: their data is the scored data

    def __init__(self, base_url: str, api_key: str, cache: Cache) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self._client = None

    # ------------------------------------------------------------------ #

    def _fetch(self, path: str, as_of: date, **params: Any) -> Any:
        """One cached GET. Cached on `as_of` so it can never serve across a
        point-in-time boundary, exactly like every other source."""
        import httpx

        key = self.cache.key("sponsor", as_of, path=path, **params)

        def produce():
            if self._client is None:
                self._client = httpx.Client(
                    base_url=self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30.0,
                )
            response = self._client.get(path, params=params)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

        return self.cache.fetch(key, produce)

    # ------------------------------------------------------------------ #
    # DataSource protocol — implement what helps, return None for the rest
    # ------------------------------------------------------------------ #

    def get_consensus(self, ticker: str, as_of: date) -> Consensus | None:
        """The highest-value method to implement first.

        Their consensus is very likely the one the scoring uses, so it beats
        yfinance's even when both are available. Keep yfinance in the chain as
        the cross-check.
        """
        payload = self._fetch("/estimates", as_of, ticker=ticker)
        if not payload:
            return None

        # ---- MAP THEIR FIELD NAMES HERE ----------------------------- #
        eps = payload.get("eps_mean") or payload.get("consensus_eps")
        if eps is None:
            return None

        published = payload.get("as_of_date")
        if published:
            # Their feed may hand you tomorrow's revision without meaning to.
            assert_point_in_time(
                date.fromisoformat(str(published)[:10]), as_of,
                f"{ticker} sponsor consensus",
            )

        return Consensus(
            eps=float(eps),
            revenue=_maybe_float(payload.get("revenue_mean")),
            # ⚠️ CONFIRM THIS AT 10:30. Consensus is universally non-GAAP, but
            # if their feed is GAAP and this says otherwise, every forecast is
            # systematically wrong by the bridge and it will look like bad
            # modelling rather than a flag set incorrectly.
            basis=Basis.NON_GAAP,
            n_analysts=_maybe_int(payload.get("num_analysts")),
            eps_high=_maybe_float(payload.get("eps_high")),
            eps_low=_maybe_float(payload.get("eps_low")),
            as_of=as_of,
        )

    def get_actuals(self, ticker: str, period: str, as_of: date) -> list[Claim] | None:
        payload = self._fetch("/actuals", as_of, ticker=ticker, period=period)
        if not payload:
            return None

        claims: list[Claim] = []
        for label, key, unit in (
            ("Revenue", "revenue", "USD"),
            ("Diluted EPS", "eps_diluted", "USD/shares"),
            ("Diluted shares", "shares_diluted", "shares"),
        ):
            value = payload.get(key)
            if value is None:
                continue
            claims.append(
                Claim(
                    id=f"sponsor:{ticker}:{period}:{key}",
                    label=label,
                    value=float(value),
                    unit=unit,
                    period=period,
                    source=Source(
                        kind=SourceKind.SPONSOR,
                        uri=f"{self.base_url}/actuals?ticker={ticker}&period={period}",
                        as_of=as_of,
                    ),
                    # Structured feed, so the "quote" is the field itself —
                    # machine-verifiable against the same endpoint.
                    verbatim_quote=f"{key}={value} for {ticker} {period}",
                )
            )
        return claims or None

    def get_guidance(self, ticker: str, as_of: date) -> list[Guidance] | None:
        return None  # guidance lives in 8-K prose; the extractor handles it

    def get_filings(
        self, ticker: str, as_of: date, forms: list[str], limit: int = 10
    ) -> list[Claim] | None:
        return None  # SEC is the floor for filings and is already reliable

    def get_transcript(self, ticker: str, as_of: date) -> str | None:
        return None

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None

    def get_macro(self, series_ids: list[str], as_of: date):
        return None


def _maybe_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _maybe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
