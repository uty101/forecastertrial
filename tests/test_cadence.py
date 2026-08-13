"""Reporting cadence — the assumption that broke every non-US filer.

Every constant in the model was four: four backtest quarters, four prior
quarters before a ratio counts, four periods in a trailing year. All correct for
a US filer and wrong for most of the world, and wrong in a way that does not
crash — a half-yearly reporter with five years of statements simply has "not
enough prior quarters", so no ratio base forms, every lens abstains for want of
anything to argue with, and the run dies looking like a model failure.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.model import cadence
from forecaster.model.inputs import next_period


def ends(start: date, step_days: int, n: int) -> list[date]:
    from datetime import timedelta

    return [start + timedelta(days=step_days * i) for i in range(n)]


def test_a_quarterly_filer_is_read_as_quarterly():
    beat = cadence.infer(ends(date(2024, 3, 31), 91, 8))

    assert beat.frequency == "quarterly"
    assert beat.periods_per_year == 4
    assert beat.seasonal_cycle == 4
    assert beat.annualise == 4


def test_a_half_yearly_filer_is_read_as_half_yearly():
    """Nestlé. Five years of statements that the quarterly assumption called
    insufficient."""
    beat = cadence.infer(ends(date(2022, 6, 30), 182, 8))

    assert beat.frequency == "half-yearly"
    assert beat.periods_per_year == 2
    assert beat.annualise == 2


def test_an_annual_filer_is_read_as_annual():
    beat = cadence.infer(ends(date(2020, 12, 31), 365, 6))

    assert beat.frequency == "annual"
    assert beat.annualise == 1
    # There is no seasonality to miss in an annual series, and that is a real
    # difference rather than a degenerate case.
    assert beat.seasonal_cycle == 1


def test_one_missing_filing_does_not_reclassify_the_filer():
    """Median, not mean. A single gap where a filing is absent would drag a mean
    across a band boundary and silently turn a quarterly filer into a
    half-yearly one — after which every trailing sum covers two years."""
    period_ends = ends(date(2024, 3, 31), 91, 8)
    del period_ends[3]  # one quarter missing, leaving a 182-day hole

    assert cadence.infer(period_ends).frequency == "quarterly"


def test_two_dates_are_not_a_cadence():
    beat = cadence.infer([date(2025, 6, 30), date(2025, 12, 31)])

    assert beat.frequency == "quarterly"  # the safe default
    assert "not a spacing" in beat.inferred_from


def test_a_half_yearly_filer_needs_more_than_one_cycle_of_history():
    """A full cycle is two periods for a half-yearly reporter, and a median over
    two observations is not a median. The constraint is enough OBSERVATIONS; the
    cycle only says how they are spaced."""
    beat = cadence.infer(ends(date(2022, 6, 30), 182, 8))

    assert beat.seasonal_cycle == 2
    assert beat.min_prior_periods == 3


# ---- period arithmetic ---------------------------------------------------- #


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("2027Q1", "2027Q2"),
        ("2026Q4", "2027Q1"),
        ("2026H1", "2026H2"),
        ("2026H2", "2027H1"),
        ("2025FY", "2026FY"),
    ],
)
def test_the_next_period_follows_whatever_cadence_the_label_says(period, expected):
    """`next_period` parsed the last character as a quarter number, so `2025FY`
    raised `invalid literal for int(): 'Y'` — four frames below anything that
    mentioned reporting frequency. `2025FY` is exactly what a half-yearly or
    annual reporter's latest period is called."""
    assert next_period(period) == expected


def test_an_unrecognised_label_is_a_hard_failure():
    """Not a silent pass-through. A label this does not understand means the
    history layer produced something unexpected, and guessing at it would put a
    forecast against a period that does not exist."""
    with pytest.raises(ValueError, match="unrecognised period label"):
        next_period("2026XYZ")


# ---- what the company actually reports ------------------------------------ #


def test_a_line_the_company_never_discloses_is_absent_not_blank():
    """An absent row means "not disclosed"; a blank row in a present one means
    "we could not find it". Those are different facts and a reader is entitled
    to tell them apart."""
    reported = cadence.reported_items(
        {"revenue": [1, 2, 3], "rnd": [], "sbc": [1]}
    )

    assert "revenue" in reported
    assert "rnd" not in reported
    # One stray observation is a tagging accident, not a disclosure policy.
    assert "sbc" not in reported
