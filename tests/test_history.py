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
    History,
    _fill_from_identity,
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


def test_a_52_53_week_quarter_that_drifts_a_month_keeps_its_place():
    """Quarter-ends wander across month boundaries on a 52/53-week calendar.

    NVDA's first quarter usually ends in late April; in 2010 it ended 2010-05-02.
    Bucketing on the END month called that Q2, colliding with the real Q2 that
    ended 2010-07-31 — six NVDA quarters collide this way, and INTC and AMD do
    too. Whichever way the collision is then resolved is wrong: leaving both
    double-counts the year, and de-duplicating drops a real quarter. NVDA, AMD
    and INTC between them were losing thirteen quarters.

    The midpoint sits mid-quarter and cannot drift a whole bucket.
    """
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2010-01-31", "2010-05-02", 1_001.8, "2010-05-14"),   # Q1, ends in MAY
        fact("2010-05-03", "2010-07-31", 811.2, "2010-08-13"),     # Q2
        fact("2010-08-01", "2010-10-31", 843.9, "2010-11-12"),     # Q3
    ]
    series = build_series(revenue, facts, NVDA_FYE)

    assert [o.period for o in series] == ["2011Q1", "2011Q2", "2011Q3"]
    assert [o.value for o in series] == [1_001.8, 811.2, 843.9]


def test_the_same_quarter_restated_collapses_to_the_newest_filing():
    """A restatement can carry a slightly different start date.

    `_pick_latest` only resolves facts whose dates match EXACTLY, so both
    survive the (start, end) key and then land on the same fiscal label. On MSFT
    that put 2017Q1 in twice — 21,928m from a 2018 accession beside 20,453m from
    the 2016 original — and summing the year came out 21.2% above the 10-K, over
    by exactly the duplicate row.
    """
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2016-07-01", "2016-09-30", 20_453.0, "2016-10-20"),  # as filed
        fact("2016-06-30", "2016-09-30", 21_928.0, "2018-08-03"),  # restated
    ]
    series = build_series(revenue, facts, 6)

    assert len(series) == 1
    assert series[0].value == 21_928.0
    assert series[0].filed == date(2018, 8, 3)


def test_year_to_date_cash_flow_is_differenced_into_quarters():
    """Cash flow is filed YTD, so only Q1 is a quarter in its own right.

    A 10-Q's cash flow statement covers 0–3, then 0–6, then 0–9 months. The span
    filter correctly refuses to call a nine-month cumulative a quarter, which
    left the ENTIRE third statement at roughly one quarter in four — NVDA's CFO
    had 19 observations against 69 quarters — while the income statement and
    balance sheet sat near 100%. A three-statement model missing three quarters
    in four of one statement is not a three-statement model.
    """
    cfo = BY_KEY["cfo"]
    facts = [
        fact("2025-01-27", "2025-04-27", 100.0, "2025-05-28"),   # Q1
        fact("2025-01-27", "2025-07-27", 250.0, "2025-08-27"),   # H1 cumulative
        fact("2025-01-27", "2025-10-26", 420.0, "2025-11-19"),   # 9M cumulative
        fact("2025-01-27", "2026-01-25", 600.0, "2026-02-25", form="10-K"),
    ]
    series = build_series(cfo, facts, NVDA_FYE)

    assert [(o.period, o.value) for o in series] == [
        ("2026Q1", 100.0),
        ("2026Q2", 150.0),
        ("2026Q3", 170.0),
        ("2026Q4", 180.0),
    ]
    # Q1 was read off a filing; the rest were computed.
    assert [o.derived for o in series] == [False, True, True, True]
    # Knowable only once BOTH rungs are filed.
    assert series[1].filed == date(2025, 8, 27)


def test_a_directly_tagged_quarter_beats_a_differenced_one():
    """Filers that tag the quarter itself are trusted over our arithmetic."""
    cfo = BY_KEY["cfo"]
    facts = [
        fact("2025-01-27", "2025-04-27", 100.0, "2025-05-28"),
        fact("2025-04-28", "2025-07-27", 999.0, "2025-08-27"),   # tagged Q2
        fact("2025-01-27", "2025-07-27", 250.0, "2025-08-27"),   # H1 cumulative
    ]
    series = build_series(cfo, facts, NVDA_FYE)

    q2 = next(o for o in series if o.period == "2026Q2")
    assert q2.value == 999.0
    assert q2.derived is False


def test_year_to_date_differencing_never_applies_to_a_ratio():
    """Same rule as Q4: subtracting cumulative EPS is not EPS."""
    eps = BY_KEY["eps_diluted"]
    facts = [
        fact("2025-01-27", "2025-04-27", 0.76, "2025-05-28"),
        fact("2025-01-27", "2025-07-27", 1.84, "2025-08-27"),
    ]
    series = build_series(eps, facts, NVDA_FYE)

    assert [o.period for o in series] == ["2026Q1"]
    assert not any(o.derived for o in series)


def test_total_liabilities_falls_back_to_the_accounting_identity():
    """A large minority of filers never tag `Liabilities` at all.

    AMD has 128 facts for `LiabilitiesAndStockholdersEquity` and none for
    `Liabilities`, putting a core balance-sheet line at zero coverage. A = L + E
    is exact, so L = A - E needs no estimate — whereas adopting
    `LiabilitiesAndStockholdersEquity` as a synonym would silently yield total
    ASSETS.
    """
    series = {
        "total_liabilities": [],
        "total_assets": build_series(
            BY_KEY["total_assets"],
            [{"end": "2026-01-25", "val": 100.0, "filed": "2026-02-25",
              "form": "10-K", "fy": 2026, "fp": "FY", "accn": "a"}],
            NVDA_FYE,
        ),
        "equity": build_series(
            BY_KEY["equity"],
            [{"end": "2026-01-25", "val": 70.0, "filed": "2026-03-02",
              "form": "10-K/A", "fy": 2026, "fp": "FY", "accn": "b"}],
            NVDA_FYE,
        ),
    }
    _fill_from_identity(series, "total_liabilities", "total_assets", "equity")

    (liabilities,) = series["total_liabilities"]
    assert liabilities.value == 30.0
    assert liabilities.derived is True
    # Knowable only when the later of the two components landed.
    assert liabilities.filed == date(2026, 3, 2)


def test_the_identity_never_overwrites_a_reported_figure():
    reported = build_series(
        BY_KEY["total_liabilities"],
        [{"end": "2026-01-25", "val": 42.0, "filed": "2026-02-25",
          "form": "10-K", "fy": 2026, "fp": "FY", "accn": "c"}],
        NVDA_FYE,
    )
    series = {
        "total_liabilities": reported,
        "total_assets": build_series(
            BY_KEY["total_assets"],
            [{"end": "2026-01-25", "val": 100.0, "filed": "2026-02-25",
              "form": "10-K", "fy": 2026, "fp": "FY", "accn": "a"}],
            NVDA_FYE,
        ),
        "equity": build_series(
            BY_KEY["equity"],
            [{"end": "2026-01-25", "val": 70.0, "filed": "2026-02-25",
              "form": "10-K", "fy": 2026, "fp": "FY", "accn": "b"}],
            NVDA_FYE,
        ),
    }
    _fill_from_identity(series, "total_liabilities", "total_assets", "equity")

    (liabilities,) = series["total_liabilities"]
    assert liabilities.value == 42.0
    assert liabilities.derived is False


def test_latest_period_is_fiscal_and_can_lead_the_calendar():
    """The label callers used to guess at, answered by the data instead.

    A January year-end filer reporting an April 2026 quarter is in fiscal
    2027Q1. Anything generating labels from `as_of.year` tries 2026 and 2025,
    never 2027, and concludes the company has not reported.
    """
    revenue = BY_KEY["revenue"]
    facts = [
        fact("2025-10-27", "2026-01-25", 39.0, "2026-02-25", form="10-K"),
        fact("2026-01-26", "2026-04-26", 44.0, "2026-05-27"),
    ]
    series = build_series(revenue, facts, NVDA_FYE)
    history = History("NVDA", date(2026, 8, 16), {"revenue": series})

    assert history.latest_period() == "2027Q1"
    assert str(date(2026, 8, 16).year) not in history.latest_period()


def test_filed_for_takes_the_last_component_to_land():
    """A quarter is knowable when its LAST line item is filed, not its first.

    Taking the earliest would date a derived Q4 to the Q1 that fed it and let a
    staleness window admit a print that was not yet public.
    """
    revenue = BY_KEY["revenue"]
    cash = BY_KEY["cash"]
    history = History(
        "NVDA",
        date(2026, 8, 16),
        {
            "revenue": build_series(
                revenue, [fact("2026-01-26", "2026-04-26", 44.0, "2026-05-27")], NVDA_FYE
            ),
            "cash": build_series(
                cash,
                [{"end": "2026-04-26", "val": 9.0, "filed": "2026-06-10",
                  "form": "10-Q/A", "fy": 2027, "fp": "Q1", "accn": "z"}],
                NVDA_FYE,
            ),
        },
    )

    assert history.filed_for("2027Q1") == date(2026, 6, 10)
    assert history.filed_for("1999Q1") is None


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
