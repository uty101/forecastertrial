"""Reshaping raw XBRL facts into quarterly series.

Every test here encodes a bug that shipped, and all three shared a property: the
output was plausible. Nothing raised, nothing logged, the numbers had the right
magnitude and the right sign — they were simply about a different quarter, or a
different concept, or arithmetic that does not apply. A model built on top would
have balanced perfectly and been wrong.

The facts are hand-built dicts in the shape the SEC `companyfacts` endpoint
returns, so this runs with no network and no cache.
"""

from __future__ import annotations

from datetime import date

from forecaster.data.history import (
    build_series,
    fiscal_year_end_month,
    label_for,
)
from forecaster.data.lineitems import BY_KEY

# NVDA's fiscal year ends in late January, which is why it is the example: a
# December default puts every one of its quarters in the wrong fiscal year.
NVDA_FYE = 1


def fact(start, end, val, filed, form="10-Q", fy=2026, fp="FY"):
    """A fact with DELIBERATELY misleading fy/fp, which is the realistic case."""
    return {
        "start": start,
        "end": end,
        "val": val,
        "filed": filed,
        "form": form,
        "fy": fy,
        "fp": fp,
        "accn": "0001045810-26-000052",
    }


def test_quarter_labels_come_from_dates_not_from_fy_fp():
    """`fy`/`fp` describe the filing, not the fact.

    A 10-K carries its comparatives, so fy=2026/fp=FY sits on the FY2024, FY2025
    and FY2026 figures alike, and a ninety-day quarter reprinted in a 10-K is
    tagged fp='FY' too. Trusting those fields dropped every quarter of NVDA
    revenue — 72 quarters read as zero — because none of them said 'Q1'.
    """
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2025-01-27", "2025-04-27", 44_062e6, "2025-05-28"),
        fact("2025-04-28", "2025-07-27", 46_743e6, "2025-08-27"),
    ]
    series = build_series(revenue, facts, NVDA_FYE)

    assert [o.period for o in series] == ["2026Q1", "2026Q2"]
    assert series[0].value == 44_062e6


def test_fiscal_year_end_is_inferred_from_the_filer():
    """A hardcoded December is wrong for a large minority of filers."""
    annual = [fact("2025-01-27", "2026-01-25", 130_497e6, "2026-02-25", form="10-K")]
    assert fiscal_year_end_month(annual) == 1
    # And the January year-end puts an April quarter in Q1 of the NEXT fiscal
    # year, which is the thing a calendar assumption gets backwards.
    assert label_for(date(2026, 4, 26), 1) == (2027, "Q1")
    assert label_for(date(2026, 1, 25), 1) == (2026, "Q4")


def test_q4_is_derived_from_the_annual_figure():
    """There is no fourth 10-Q; Q4 only ever appears inside the year."""
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2025-01-27", "2025-04-27", 10.0, "2025-05-28"),
        fact("2025-04-28", "2025-07-27", 20.0, "2025-08-27"),
        fact("2025-07-28", "2025-10-26", 30.0, "2025-11-19"),
        fact("2025-01-27", "2026-01-25", 100.0, "2026-02-25", form="10-K"),
    ]
    series = build_series(revenue, facts, NVDA_FYE)

    q4 = next(o for o in series if o.period == "2026Q4")
    assert q4.value == 40.0
    assert q4.derived is True
    # Knowable only when the 10-K landed, not when Q3 did. Losing this would
    # reintroduce look-ahead after the source layer worked to prevent it.
    assert q4.filed == date(2026, 2, 25)


def test_q4_is_never_derived_for_a_ratio():
    """EPS is not additive and FY − (Q1+Q2+Q3) is meaningless for it.

    This shipped: a quarter that earned $22.1bn was reported at −4.49 EPS,
    because each quarter has a different share count and the subtraction has no
    financial meaning. The honest output is no Q4 at all.
    """
    eps = BY_KEY["eps_diluted"]
    assert eps.additive is False
    facts = [
        fact("2025-01-27", "2025-04-27", 0.76, "2025-05-28"),
        fact("2025-04-28", "2025-07-27", 1.08, "2025-08-27"),
        fact("2025-07-28", "2025-10-26", 1.30, "2025-11-19"),
        fact("2025-01-27", "2026-01-25", 3.10, "2026-02-25", form="10-K"),
    ]
    series = build_series(eps, facts, NVDA_FYE)

    assert [o.period for o in series] == ["2026Q1", "2026Q2", "2026Q3"]
    assert not any(o.derived for o in series)


def test_cumulative_periods_are_not_mistaken_for_quarters():
    """A 10-Q tags the three-month AND the year-to-date duration.

    Treating a nine-month cumulative as a quarter is the units error that stays
    internally consistent — the model still balances, on a number three times
    too large.
    """
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2025-07-28", "2025-10-26", 30.0, "2025-11-19"),      # the quarter
        fact("2025-01-27", "2025-10-26", 90.0, "2025-11-19"),      # YTD, 272 days
    ]
    series = build_series(revenue, facts, NVDA_FYE)

    assert len(series) == 1
    assert series[0].value == 30.0


def test_balance_sheet_items_are_instants_not_durations():
    """A balance has no start date, and summing four of them is nonsense."""
    cash = BY_KEY["cash"]
    assert cash.kind == "stock"
    facts = [
        {"end": "2025-04-27", "val": 9_000e6, "filed": "2025-05-28",
         "form": "10-Q", "fy": 2026, "fp": "Q1", "accn": "x"},
        {"end": "2026-01-25", "val": 10_605e6, "filed": "2026-02-25",
         "form": "10-K", "fy": 2026, "fp": "FY", "accn": "y"},
    ]
    series = build_series(cash, facts, NVDA_FYE)

    assert [o.period for o in series] == ["2026Q1", "2026Q4"]
    # The year-end balance IS the Q4 balance — never derived by subtraction.
    assert all(not o.derived for o in series)


def test_the_latest_restatement_visible_wins():
    """Two filings of the same quarter: the newer one is what we knew."""
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2025-01-27", "2025-04-27", 44_000e6, "2025-05-28"),
        fact("2025-01-27", "2025-04-27", 44_062e6, "2025-08-27"),  # restated
    ]
    series = build_series(revenue, facts, NVDA_FYE)

    assert len(series) == 1
    assert series[0].value == 44_062e6
