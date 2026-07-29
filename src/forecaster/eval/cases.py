"""Building the firm-quarter cases the whole eval rests on.

This is Block 1, the gate. Until these cases exist and `consensus × 1.02` has
been scored against them, every number downstream is an assertion.

**The point-in-time subtlety that quietly ruins backtests.** yfinance's
`earnings_estimate` gives consensus for the *current* quarter *as of now*. Using
it for a historical case is look-ahead bias: you are scoring a forecast against a
bar that was set after the fact, and the backtest looks great for no reason.

`earnings_history.epsEstimate` is different — it is consensus *as it stood at
that quarter's report date*, which is exactly the bar the company was scored
against. That is the column this module uses, and the distinction is the single
most important line of code in the file.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import structlog

from forecaster.data.cache import Cache
from forecaster.eval.backtest import Case

log = structlog.get_logger()

THROTTLE_S = 0.6  # Yahoo rate-limits hard on loops; do not thread this

# Detecting a 2% edge over consensus at 80% power needs roughly this many
# resolved forecasts. Below it, leaderboard position is variance.
TARGET_CASES = 350

# A "surprise" outside this band is a data error — a split not adjusted for, a
# currency mix-up, a placeholder value — not a forecasting event. Micron has
# printed +40%, so this is deliberately wide.
SANE_SURPRISE = (-3.0, 5.0)


@dataclass
class CaseSet:
    cases: list[Case] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    by_ticker: dict[str, int] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.cases)

    @property
    def underpowered(self) -> bool:
        return self.n < TARGET_CASES

    def surprises(self) -> dict[str, list[float]]:
        """Per-company surprise history, for the baseline's shrunk tilt."""
        out: dict[str, list[float]] = {}
        for case in self.cases:
            if case.consensus_eps:
                surprise = (case.actual_eps - case.consensus_eps) / abs(
                    case.consensus_eps
                )
                out.setdefault(case.ticker, []).append(surprise)
        return out

    def summary(self) -> dict:
        surprises = [s for ss in self.surprises().values() for s in ss]
        return {
            "n_cases": self.n,
            "n_tickers": len(self.by_ticker),
            "n_rejected": len(self.rejected),
            "target": TARGET_CASES,
            "underpowered": self.underpowered,
            "median_surprise": (
                round(statistics.median(surprises), 4) if surprises else None
            ),
            "beat_rate": (
                round(sum(s > 0 for s in surprises) / len(surprises), 3)
                if surprises
                else None
            ),
            "power_note": (
                f"n={self.n} < {TARGET_CASES} needed to detect a 2% edge at 80% "
                "power — treat any ranking as variance-dominated"
                if self.underpowered
                else f"n={self.n} is adequately powered"
            ),
        }


def build(
    tickers: list[str],
    cache: Cache,
    max_quarters: int = 8,
    lock_days_before_report: int = 1,
) -> CaseSet:
    """Pull historical firm-quarters for a universe.

    `lock_days_before_report` sets `as_of` a day before the print, so a case can
    never see the result it is being scored on. The consensus is the one that
    stood at the report date, which is the bar the company actually faced.
    """
    result = CaseSet()

    for ticker in tickers:
        rows = _earnings_history(ticker, cache)
        if not rows:
            result.rejected.append(f"{ticker}: no earnings history")
            continue

        kept = 0
        for row in rows[-max_quarters:]:
            case = _to_case(ticker, row, lock_days_before_report, result.rejected)
            if case is not None:
                result.cases.append(case)
                kept += 1
        if kept:
            result.by_ticker[ticker] = kept

    log.info("cases_built", **result.summary())
    if result.underpowered:
        # Said out loud here so it cannot be discovered late. This is the number
        # to put on the slide before someone else asks for it.
        log.warning("case_set_underpowered", n=result.n, target=TARGET_CASES)
    return result


def _earnings_history(ticker: str, cache: Cache) -> list[dict]:
    """Cached `earnings_history` — the point-in-time consensus table."""
    key = cache.key("yf_history", date(2000, 1, 1), ticker=ticker)

    def produce() -> list[dict]:
        import yfinance as yf

        time.sleep(THROTTLE_S)
        frame = yf.Ticker(ticker).earnings_history
        if frame is None or frame.empty:
            return []
        return frame.reset_index().to_dict("records")

    try:
        return cache.fetch(key, produce) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("earnings_history_failed", ticker=ticker, error=str(exc))
        return []


def _to_case(
    ticker: str, row: dict, lock_days: int, rejected: list[str]
) -> Case | None:
    quarter = row.get("quarter") or row.get("index")
    estimate = row.get("epsEstimate")
    actual = row.get("epsActual")

    if quarter is None or estimate is None or actual is None:
        rejected.append(f"{ticker} {quarter}: missing estimate or actual")
        return None

    try:
        reported = date.fromisoformat(str(quarter)[:10])
        estimate = float(estimate)
        actual = float(actual)
    except (ValueError, TypeError):
        rejected.append(f"{ticker} {quarter}: unparseable row")
        return None

    if estimate == 0:
        # A near-zero consensus makes percentage surprise meaningless and would
        # dominate any MAPE-style metric. Excluded, and the exclusion is counted.
        rejected.append(f"{ticker} {reported}: zero consensus, surprise undefined")
        return None

    surprise = (actual - estimate) / abs(estimate)
    lo, hi = SANE_SURPRISE
    if not lo <= surprise <= hi:
        rejected.append(
            f"{ticker} {reported}: surprise {surprise:+.1%} outside the sane band "
            "— probably a split or currency artefact, not a forecasting event"
        )
        return None

    return Case(
        ticker=ticker,
        period=str(reported),
        as_of=reported - timedelta(days=lock_days),
        consensus_eps=estimate,
        actual_eps=actual,
    )
