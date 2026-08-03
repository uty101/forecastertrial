"""Daily price bars, and the average price actually paid.

The only equity-price need this system has is a denominator. A filing reports
what a buyback COST and never how many shares it retired, so the share count —
and therefore EPS — cannot be closed from filings alone. That is the gap this
fills.

**Prices must be unadjusted, and turning the adjustment off is not enough.**
Back-adjusting for splits is right for charting a return series and wrong for
asking what a company paid per share. After a 10-for-1 the adjusted price is a
tenth of the price actually paid, which multiplies shares retired by ten, cuts
the EPS denominator and inflates EPS — no error, plausible number, same shape as
the `avg_price=1.0` placeholder that gave an EPS 27% too high.

The trap is that the obvious lever does not pull it. yfinance's `auto_adjust`
controls DIVIDEND adjustment only and applies split adjustment unconditionally:
NVDA closed near $1,150 on 2024-06-03, a week before its 10-for-1, and
`history(auto_adjust=False)` returns 115.0. The source therefore fetches the
split history and undoes the adjustment itself. A bar here is what a share
actually changed hands at, which means the series is deliberately discontinuous
across a split and must not be used to compute returns.

**Point-in-time is trivially satisfiable here, unlike everywhere else.** A trade
printed at a timestamp is a fact at that timestamp and is never restated. No
vintage handling, no `filed` date, no restatement filter — bounding by date is
the whole of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceBar:
    """One session, as traded. No split or dividend adjustment applied."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def vwap(bars: list[PriceBar]) -> float | None:
    """Volume-weighted average price across the bars, or None if unusable.

    Volume-weighted rather than a simple mean of closes, because a buyback
    executes WITH volume: heavy days move the average price paid and a plain
    mean treats a thin holiday session as equal to a print day. This is the
    daily-bar approximation of the "average price paid per share" a company
    discloses in Part II Item 5 once the 10-Q lands.

    The typical price `(high + low + close) / 3` stands in for each session's
    own intraday VWAP — closer to a day's real execution than the close alone,
    which is a single instant at the end of it.
    """
    usable = [b for b in bars if b.volume > 0]
    if not usable:
        return None
    traded = sum(b.volume for b in usable)
    if traded <= 0:
        return None
    return sum(((b.high + b.low + b.close) / 3.0) * b.volume for b in usable) / traded
