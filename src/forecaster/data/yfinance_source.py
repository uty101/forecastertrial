"""yfinance — your consensus source, and the one nobody expects to still work.

Multiple 2026 posts claim yfinance is deprecated. It isn't: 1.0 shipped Dec 2025
and it has had twelve releases in twelve months. It gives, free and keyless:
forward EPS and revenue consensus, the estimate *trend* (current vs 7/30/60/90
days ago), and *revision counts*. EODHD charges ~$50/mo for the identical schema.
Estimate-revision momentum is the highest-signal free input in this system.

THE IMPORTANT SUBTLETY, and the thing that quietly breaks backtests:

  `ticker.earnings_estimate` gives consensus for the CURRENT quarter, as of now.
  It is NOT point-in-time. Using it for a historical backtest is look-ahead bias.

  For history, use `ticker.earnings_history`, whose `epsEstimate` column is the
  consensus *as it stood at that quarter's report date* — which is exactly the
  bar the company was scored against. That is what `get_consensus` returns when
  `as_of` is in the past.

Operational notes: datacentre IPs get 429'd far harder than laptops, so smoke
test from the machine you will demo on. Sleep between tickers; do not thread it.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import structlog

from forecaster.data.cache import Cache
from forecaster.data.prices import PriceBar
from forecaster.data.protocol import assert_point_in_time
from forecaster.schemas import Basis, Consensus

log = structlog.get_logger()

THROTTLE_S = 0.6  # be polite; yahoo rate-limits aggressively on repeated calls

# A large accelerated filer has 40 days from quarter end to file its 10-Q.
# yfinance reports period ends with no filing dates, so this stands in for
# knowability — erring late, because a figure withheld a fortnight too long
# costs coverage while one released a fortnight too early is a leak.
REPORTING_LAG_DAYS = 45


class YFinanceSource:
    name = "yfinance"
    priority = 10  # ahead of SEC for consensus; SEC has none

    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    # ------------------------------------------------------------------ #

    def _snapshot(self, ticker: str, as_of: date) -> dict | None:
        """One cached blob per (ticker, as_of) holding everything we need.

        Cached hard because a run touches this repeatedly and Yahoo will start
        429ing if you loop without pause.
        """
        key = self.cache.key("yf", as_of, ticker=ticker)

        def produce() -> dict | None:
            import yfinance as yf

            time.sleep(THROTTLE_S)
            t = yf.Ticker(ticker)
            out: dict = {"ticker": ticker, "fetched": date.today().isoformat()}
            for attr in (
                "earnings_estimate",
                "revenue_estimate",
                "eps_trend",
                "eps_revisions",
                "earnings_history",
            ):
                try:
                    frame = getattr(t, attr)
                    out[attr] = (
                        frame.reset_index().to_dict("records")
                        if frame is not None and not frame.empty
                        else []
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "yf_attr_failed", ticker=ticker, attr=attr, error=str(exc)
                    )
                    out[attr] = []
            return out

        return self.cache.fetch(key, produce)

    # ------------------------------------------------------------------ #

    def get_consensus(self, ticker: str, as_of: date) -> Consensus | None:
        snap = self._snapshot(ticker, as_of)
        if not snap:
            return None

        historical = as_of < date.today() - timedelta(days=1)
        if historical:
            return self._historical_consensus(snap, ticker, as_of)
        return self._current_consensus(snap, as_of)

    def _historical_consensus(
        self, snap: dict, ticker: str, as_of: date
    ) -> Consensus | None:
        """Consensus as it stood at the report date of the most recent quarter
        that had already reported by `as_of`.

        This is the honest backtest path. Note the limitation: it is consensus
        at *report date*, not at an arbitrary as_of. Good enough — the bar a
        company is scored against is the one standing when it prints.
        """
        rows = snap.get("earnings_history") or []
        usable = []
        for row in rows:
            quarter = row.get("quarter") or row.get("index")
            if quarter is None or row.get("epsEstimate") is None:
                continue
            try:
                reported = date.fromisoformat(str(quarter)[:10])
            except ValueError:
                continue
            if reported <= as_of:
                usable.append((reported, row))
        if not usable:
            return None

        reported, row = max(usable, key=lambda r: r[0])
        assert_point_in_time(reported, as_of, f"{ticker} historical consensus")
        return Consensus(
            eps=float(row["epsEstimate"]),
            basis=Basis.NON_GAAP,
            as_of=reported,
        )

    def _current_consensus(self, snap: dict, as_of: date) -> Consensus | None:
        estimates = snap.get("earnings_estimate") or []
        current = next(
            (r for r in estimates if str(r.get("period", "")).lower() in {"0q", "+0q"}),
            None,
        ) or (estimates[0] if estimates else None)
        if not current or current.get("avg") is None:
            return None

        revenue_rows = snap.get("revenue_estimate") or []
        period = current.get("period")
        revenue = next(
            (r.get("avg") for r in revenue_rows if r.get("period") == period),
            None,
        )

        revisions = snap.get("eps_revisions") or []
        rev = next(
            (r for r in revisions if r.get("period") == current.get("period")), {}
        )

        return Consensus(
            eps=float(current["avg"]),
            revenue=float(revenue) if revenue else None,
            basis=Basis.NON_GAAP,
            n_analysts=int(current["numberOfAnalysts"])
            if current.get("numberOfAnalysts")
            else None,
            eps_high=float(current["high"]) if current.get("high") else None,
            eps_low=float(current["low"]) if current.get("low") else None,
            revisions_up_30d=_int(rev.get("upLast30days")),
            revisions_down_30d=_int(rev.get("downLast30days")),
            days_since_last_revision=self._staleness(snap, current.get("period")),
            as_of=as_of,
        )

    @staticmethod
    def _staleness(snap: dict, period) -> int | None:
        """Infer staleness from eps_trend: if the estimate is unchanged over 30
        and 60 days, nobody has updated for recent news. A stale consensus is a
        beatable one, so this feeds straight into lambda."""
        trend = next(
            (r for r in (snap.get("eps_trend") or []) if r.get("period") == period), None
        )
        if not trend:
            return None
        now, d7, d30, d60 = (
            trend.get("current"),
            trend.get("7daysAgo"),
            trend.get("30daysAgo"),
            trend.get("60daysAgo"),
        )
        if now is None:
            return None
        if d7 is not None and now != d7:
            return 7
        if d30 is not None and now != d30:
            return 30
        if d60 is not None and now != d60:
            return 60
        return 90

    # ------------------------------------------------------------------ #

    def get_actuals(self, ticker: str, period: str, as_of: date):
        return None  # SEC is ground truth for actuals

    def get_guidance(self, ticker: str, as_of: date):
        return None

    def get_filings(self, ticker: str, as_of: date, forms: list[str],
                    limit: int = 10, items: str | None = None):
        return None

    def get_transcript(self, ticker: str, as_of: date):
        return None

    def get_share_count(self, ticker: str, as_of: date) -> dict[str, float] | None:
        """Quarterly diluted share counts, keyed by period end — a fallback only.

        SEC is the right source for this and usually has it. The exception is a
        filer with several listed share classes: it tags the weighted-average
        count, and often diluted EPS too, against a class dimension, and
        `companyfacts` returns only facts carrying no dimensions. Visa has no
        weighted-average share tag there at all while reporting one every
        quarter. No tag list closes that gap — the numbers are not in the
        response — and the count is the EPS denominator.

        **Point-in-time is approximated here, and that is a real weakening.**
        yfinance gives period ends with no filing dates, so knowability is
        inferred from the SEC deadline: a large accelerated filer must file its
        10-Q within 40 days of quarter end. Waiting `REPORTING_LAG_DAYS` is a
        conservative reading of that — it can hide a figure we could legally
        have known for a fortnight, which is the safe direction to be wrong in.

        Shallow, too: roughly six quarters. Enough to open a model on the day,
        not enough to backtest on.
        """
        key = self.cache.key("yf_shares", as_of, ticker=ticker)

        def produce() -> dict[str, float] | None:
            import yfinance as yf

            time.sleep(THROTTLE_S)
            frame = yf.Ticker(ticker).quarterly_income_stmt
            if frame is None or frame.empty:
                return None
            row = next(
                (r for r in frame.index if str(r).strip() == "Diluted Average Shares"),
                None,
            )
            if row is None:
                return None
            out: dict[str, float] = {}
            for column in frame.columns:
                value = frame.loc[row, column]
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number > 0:
                    out[column.date().isoformat()] = number
            return out or None

        counts = self.cache.fetch(key, produce)
        if not counts:
            return None

        knowable = {
            period_end: shares
            for period_end, shares in counts.items()
            if date.fromisoformat(period_end) + timedelta(days=REPORTING_LAG_DAYS)
            <= as_of
        }
        if len(knowable) < len(counts):
            log.info(
                "yf_shares_filtered",
                ticker=ticker, kept=len(knowable), dropped=len(counts) - len(knowable),
                why="period end plus the filing deadline is after as_of",
            )
        return knowable or None

    def get_prices(
        self, ticker: str, start: date, end: date
    ) -> list[PriceBar] | None:
        """Daily bars over [start, end], inclusive, AS TRADED on the day.

        `auto_adjust=False` is necessary and not sufficient, which is worth
        stating precisely because the obvious reading of the parameter name is
        wrong. It controls DIVIDEND adjustment only; yfinance applies SPLIT
        adjustment unconditionally. Verified: NVDA closed near $1,150 on
        2024-06-03, a week before its 10-for-1, and `history(auto_adjust=False)`
        returns 115.0 for that session.

        Left there, a buyback executed before a later split would be priced at a
        tenth of what was paid, retiring ten times too many shares and inflating
        EPS — no error, entirely plausible number. So the split series is fetched
        and the adjustment is undone: each bar is multiplied by the cumulative
        ratio of every split that happened AFTER it, and volume divided by the
        same factor.

        The result is deliberately NOT a continuous series for charting. It is
        the price a share actually changed hands at, which is the only thing
        "average price paid per share" can mean.

        Separately, yfinance treats `end` as EXCLUSIVE, so it is passed a day
        later and the result filtered on `end` regardless. Trusting the
        library's boundary convention would drop the last session of every
        quarter, and the session before a print is not one to lose.
        """
        # Namespace carries the payload version. The shape changed when split
        # un-adjustment was added, and an entry written by the old code has no
        # split data — so parsing it defensively would silently serve
        # split-ADJUSTED prices, which is precisely the bug this method exists
        # to avoid. A new namespace makes stale entries unreadable rather than
        # subtly wrong.
        key = self.cache.key(
            "yf_prices_v2", end, ticker=ticker, start=start.isoformat()
        )

        def produce() -> dict | None:
            import yfinance as yf

            time.sleep(THROTTLE_S)
            handle = yf.Ticker(ticker)
            frame = handle.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
            if frame is None or frame.empty:
                return None
            rows = [
                {
                    "date": stamp.date().isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
                for stamp, row in frame.iterrows()
            ]
            # The whole split history, not just the window: a split AFTER the
            # window is exactly the one that adjusted these prices.
            try:
                splits = [
                    [stamp.date().isoformat(), float(ratio)]
                    for stamp, ratio in handle.splits.items()
                    if ratio
                ]
            except Exception as exc:  # noqa: BLE001
                log.warning("yf_splits_failed", ticker=ticker, error=str(exc))
                splits = []
            return {"bars": rows, "splits": splits} if rows else None

        payload = self.cache.fetch(key, produce)
        if not payload:
            return None

        splits = [
            (date.fromisoformat(day), ratio) for day, ratio in payload.get("splits", [])
        ]

        bars = []
        for row in payload["bars"]:
            stamp = date.fromisoformat(row["date"])
            if stamp < start or stamp > end:
                continue
            factor = 1.0
            for split_day, ratio in splits:
                if split_day > stamp:
                    factor *= ratio
            bars.append(
                PriceBar(
                    date=stamp,
                    open=row["open"] * factor,
                    high=row["high"] * factor,
                    low=row["low"] * factor,
                    close=row["close"] * factor,
                    # Shares move the other way: a 10-for-1 multiplies the share
                    # count, so the adjusted volume is ten times the shares that
                    # actually traded.
                    volume=row["volume"] / factor if factor else row["volume"],
                )
            )
        return bars or None

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None

    def get_macro(self, series_ids: list[str], as_of: date):
        return None


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
