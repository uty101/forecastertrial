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


def test_one_unfinished_session_does_not_poison_the_whole_average():
    """The bug this was written for, and the most expensive kind here.

    Fetching intraday returns the current session as a real bar with a NaN
    close. NVDA's dossier had exactly one of those at the end of 500 bars, and
    it turned the VWAP into NaN. Nothing raised — `bool(nan)` is True, so the
    None-and-zero guard downstream waved it through. NaN became `avg_price`,
    then the buyback share retirement, then the EPS denominator, and stage D
    reported an EPS of `nan` for every quarter it checked.

    One partial row silently invalidated an entire stage. The bar stays in the
    series; it is excluded from the statistic.
    """
    partial = PriceBar(date(2026, 5, 3), 100.0, 110.0, 95.0, float("nan"), 5_000_000)
    bars = [bar(1, 100.0, 1_000_000), bar(2, 100.0, 1_000_000), partial]

    assert vwap(bars) == 100.0


def test_a_bar_with_nan_volume_is_excluded_too():
    """The weight is as capable of being NaN as the price, and a NaN weight
    propagates through the denominator instead of the numerator — same silent
    result, harder to spot."""
    partial = PriceBar(date(2026, 5, 3), 100.0, 100.0, 100.0, 100.0, float("nan"))

    assert vwap([bar(1, 200.0, 1_000_000), partial]) == 200.0


def test_only_unfinished_bars_is_none_not_nan():
    """If every bar is incomplete there is no average price, and the caller must
    be told that rather than handed a NaN it will not check."""
    partial = PriceBar(date(2026, 5, 3), 100.0, 110.0, 95.0, float("nan"), 5_000_000)

    assert vwap([partial]) is None


def test_complete_distinguishes_a_partial_bar_from_a_finished_one():
    """The bar is kept in the series deliberately — today's open and high are
    real information — so something has to mark it as unusable for statistics."""
    assert bar(1, 100.0, 1_000_000).complete() is True
    assert PriceBar(
        date(2026, 5, 3), 100.0, 110.0, 95.0, float("nan"), 5_000_000
    ).complete() is False
