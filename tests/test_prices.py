"""Daily prices, and the average price actually paid.

The only reason this exists is the EPS denominator: filings report what a
buyback cost and never how many shares it retired. Both tests here encode a way
of getting a plausible number that is wrong — which is the only kind of error
that survives to the leaderboard.
"""

from __future__ import annotations

from datetime import date

from forecaster.data.prices import PriceBar, vwap


def bar(day: int, close: float, volume: float, spread: float = 0.0) -> PriceBar:
    return PriceBar(
        date=date(2026, 5, day),
        open=close,
        high=close + spread,
        low=close - spread,
        close=close,
        volume=volume,
    )


def test_vwap_is_volume_weighted_not_a_mean_of_closes():
    """A buyback executes WITH volume, so heavy days set the price paid.

    A plain mean of closes treats a thin holiday session as equal to a print
    day. Here the cheap day carries ten times the volume, so the true average
    paid is far below the arithmetic mean of 150 — and using the mean would
    understate shares retired.
    """
    bars = [bar(1, 100.0, 10_000_000), bar(2, 200.0, 1_000_000)]

    assert vwap(bars) == (100.0 * 10_000_000 + 200.0 * 1_000_000) / 11_000_000
    assert vwap(bars) < 150.0                      # the naive answer


def test_vwap_uses_the_typical_price_not_just_the_close():
    """The close is one instant at the end of a session; a buyback trades
    through it. `(high + low + close) / 3` stands in for the day's own VWAP."""
    bars = [bar(1, 100.0, 1_000_000, spread=30.0)]   # high 130, low 70

    assert vwap(bars) == (130.0 + 70.0 + 100.0) / 3.0


def test_zero_volume_sessions_are_excluded():
    """A halted or untraded session has no price paid to contribute, and
    including it would drag the average toward a price nobody transacted at."""
    bars = [bar(1, 100.0, 0), bar(2, 200.0, 1_000_000)]

    assert vwap(bars) == 200.0


def test_no_usable_bars_is_none_not_zero():
    """Zero would flow into the model as a share price of nothing and retire an
    infinite number of shares. Absence has to stay absence."""
    assert vwap([]) is None
    assert vwap([bar(1, 100.0, 0)]) is None
