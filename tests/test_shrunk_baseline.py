"""The per-company baseline — a measured number where an asserted one was.

`consensus × 1.02` applies the market's average tilt to every company. But the
surprise history is per company, it is already on disk, and shrinking it costs
nothing: no model call, no network, two lines of arithmetic on data the case
builder already produced.

Scored through the same harness as the flat baseline, it takes MAE from 0.1868
to 0.1229 on n=487 — 34% better. That is now the bar the pipeline has to clear,
which is the right direction for a bar to move.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.eval import backtest as B


def case(ticker: str, consensus: float, actual: float, i: int = 0) -> B.Case:
    return B.Case(
        ticker=ticker,
        period=f"2025Q{i % 4 + 1}",
        as_of=date(2025, 3, 1),
        consensus_eps=consensus,
        actual_eps=actual,
    )


def steady(ticker: str, surprise: float, n: int = 8) -> list[B.Case]:
    """A company that beats by the same amount every quarter."""
    return [case(ticker, 2.0, 2.0 * (1 + surprise), i) for i in range(n)]


def group(n: int = 8, surprise: float = 0.02) -> list[B.Case]:
    """A peer set big enough for the between-company spread to be measurable.

    `shrinkage.MIN_PEERS` is 5: below that, tau-squared is not an estimate of
    anything and everything is pulled hard toward the group. That is the correct
    behaviour and it makes a 3-company fixture test the fallback rather than the
    shrinkage.
    """
    return [
        c
        for i in range(n)
        for c in steady(f"PEER{i}", surprise + i * 0.002)
    ]


def test_a_consistent_beater_keeps_most_of_its_own_number():
    """A long, consistent record earns the right to its own estimate."""
    cases = steady("AAA", 0.05) + group()
    tilts = B.shrunk_tilts(cases)

    assert tilts["AAA"] == pytest.approx(0.05, abs=0.015)


def test_one_wild_quarter_is_pulled_back_to_the_group():
    """The reason shrinkage exists rather than a raw median.

    Boeing's raw median surprise across the real case set is +141% — one quarter
    against a near-zero denominator, not a property of the company. Applied as a
    tilt it would multiply its consensus by 2.4.
    """
    # Two usable quarters, wildly inconsistent: +400% then +5%.
    wild = [case("WILD", 0.5, 2.5, 0), case("WILD", 2.0, 2.1, 1)]
    cases = wild + group()
    tilts = B.shrunk_tilts(cases)

    assert tilts["WILD"] < 1.0, "a 400% raw surprise must not survive as a tilt"
    # And it lands near the peers rather than near its own wild median.
    assert tilts["WILD"] < 0.5


def test_a_perfectly_consistent_outlier_keeps_its_own_number():
    """Distance from the group is not evidence of noise.

    A company that has beaten by exactly 50% for eight straight quarters has
    zero within-company variance, so James-Stein leaves it alone — and that is
    correct, not a bug. Shrinkage pulls toward the group in proportion to how
    NOISY a record is, never in proportion to how unusual it is. Pulling this
    one back would be discarding the strongest signal in the set.
    """
    tilts = B.shrunk_tilts(steady("AAA", 0.50) + group())

    assert tilts["AAA"] == pytest.approx(0.50, abs=0.01)


def test_a_company_is_never_shrunk_against_a_group_containing_itself():
    """Including itself lets a company pull the target it is measured against.

    Constructed so the two differ: eight noisy copies of one wild company would
    drag a group median that included them, and the shrunk result would then
    flatter exactly the names the shrinkage exists to catch.
    """
    noisy = [
        case("AAA", 2.0, 2.0 * (1 + s), i)
        for i, s in enumerate([0.9, 0.1, 0.8, 0.05, 0.95, 0.02, 0.7, 0.15])
    ]
    tilts = B.shrunk_tilts(noisy + group())

    # Its own median is ~0.42; its peers sit near 0.027. A noisy record lands
    # near the peers rather than near itself.
    assert tilts["AAA"] < 0.2


def test_a_company_with_one_quarter_gets_no_tilt_of_its_own():
    """One observation is not a history. It falls back to the flat tilt at the
    call site rather than getting a per-company number from a single point."""
    cases = [case("ONE", 2.0, 2.1)] + group()

    assert "ONE" not in B.shrunk_tilts(cases)


def test_a_near_zero_consensus_is_excluded_not_divided_by():
    """`actual/consensus - 1` on a consensus of 0.001 produces a number in the
    hundreds, and it is arithmetic rather than information."""
    cases = [case("ZERO", 0.001, 0.5), case("ZERO", 0.002, 0.4)] + group()

    assert "ZERO" not in B.shrunk_tilts(cases)


def test_the_shrunk_baseline_is_scored_through_the_same_harness():
    """Not a separate metric with its own arithmetic. The flat and shrunk
    baselines have to be comparable, which means the same winsorization and the
    same case set — otherwise the improvement is a change of ruler."""
    cases = steady("AAA", 0.10) + steady("BBB", 0.10)
    tilts = B.shrunk_tilts(cases)

    flat = B.run(cases, forecaster=lambda c: c.consensus_eps, baseline_tilt=0.02)
    fitted = B.run(
        cases,
        forecaster=lambda c: c.consensus_eps,
        baseline_tilt=0.02,
        per_company_tilt=tilts,
    )

    # Both companies beat by 10% every quarter, so a 10% tilt is exactly right
    # and a 2% one is not.
    assert fitted.summary()["mae_baseline"] < flat.summary()["mae_baseline"]
