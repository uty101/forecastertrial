"""The return leg: what the ensemble believes, folded into what the model runs on.

Stage D hands the lenses a model; this puts their conclusions back into it. The
tests are about the three ways that goes wrong quietly — a unit error that
balances perfectly, a mean dragged by one outlier, and silence read as agreement.
"""

from __future__ import annotations

import pytest

from forecaster.model import from_lenses, project
from forecaster.schemas import LensName, LensOutput


def _lens(name: LensName, **drivers) -> LensOutput:
    return LensOutput(
        lens=name, eps=1.0, reasoning="test", claim_ids=["c1"], confidence=0.7,
        **drivers,
    )


def _driver(value: float) -> project.Driver:
    return project.Driver(value, "held", "seeded")


def _seeded(n: int = 3) -> list[project.YearDrivers]:
    return [
        project.YearDrivers(
            fy=2027 + i,
            revenue_growth=_driver(0.10), gross_margin=_driver(0.60),
            opex_pct_revenue=_driver(0.30), da_pct_revenue=_driver(0.05),
            capex_pct_revenue=_driver(0.06), tax_rate=_driver(0.20),
            dso=_driver(60.0), dio=_driver(90.0), dpo=_driver(45.0),
            sbc_pct_revenue=_driver(0.03), interest_rate_debt=_driver(0.05),
            interest_rate_cash=_driver(0.03),
            dividend_pct_net_income=_driver(0.10),
            buyback_pct_net_income=_driver(0.20),
            debt_issued=_driver(0.0), debt_repaid=_driver(0.0),
        )
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# what gets through
# --------------------------------------------------------------------------- #


def test_a_lens_view_becomes_a_forecast_driver():
    lenses = [_lens(LensName.DRIVERS, revenue_growth=0.25)]

    updated, report = from_lenses.apply(_seeded(), lenses)

    assert updated[0].revenue_growth.value == 0.25
    assert updated[0].revenue_growth.origin == "forecast"
    assert "drivers" in updated[0].revenue_growth.note
    assert report["applied"]["revenue_growth"]["lenses"] == ["drivers"]


def test_several_lenses_on_one_driver_are_combined_by_median():
    """Three readings of the same quantity. The median is the robust summary —
    and this is NOT the ensemble forming a forecast, which happens at the judge
    weighted by materiality. It is only "what do the lenses that spoke to gross
    margin think gross margin is"."""
    lenses = [
        _lens(LensName.MARGINS, gross_margin=0.70),
        _lens(LensName.DRIVERS, gross_margin=0.74),
        _lens(LensName.FORENSICS, gross_margin=0.72),
    ]

    updated, report = from_lenses.apply(_seeded(), lenses)

    assert updated[0].gross_margin.value == pytest.approx(0.72)
    assert len(report["applied"]["gross_margin"]["lenses"]) == 3


def test_one_wild_lens_does_not_move_the_median():
    """A mean would take it. One lens misreading a segment table by a factor of
    ten is exactly the case robust statistics exist for."""
    lenses = [
        _lens(LensName.MARGINS, gross_margin=0.70),
        _lens(LensName.DRIVERS, gross_margin=0.71),
        _lens(LensName.FORENSICS, gross_margin=0.05),
    ]

    updated, _ = from_lenses.apply(_seeded(), lenses)

    assert updated[0].gross_margin.value == pytest.approx(0.70)


# --------------------------------------------------------------------------- #
# what gets stopped
# --------------------------------------------------------------------------- #


def test_a_percentage_where_a_fraction_was_asked_for_is_rejected_and_named():
    """The error that balances perfectly. A lens returning 60 for a gross margin
    means 60%, and taking it literally produces a company with 6000% margins
    whose balance sheet still ties — the arithmetic stays consistent, which is
    exactly why this cannot be caught by looking at the output."""
    lenses = [_lens(LensName.MARGINS, gross_margin=60.0)]

    updated, report = from_lenses.apply(_seeded(), lenses)

    assert updated[0].gross_margin.origin == "held"
    assert any("outside" in line for line in report["rejected"])
    assert "gross_margin" in report["silent"]


def test_a_nan_never_reaches_the_model():
    """`bool(nan)` is True and NaN survives every arithmetic operation without
    raising, so one NaN driver would produce a projection of NaN that balances
    (NaN − NaN is NaN, not an error)."""
    lenses = [_lens(LensName.DRIVERS, revenue_growth=float("nan"))]

    updated, report = from_lenses.apply(_seeded(), lenses)

    assert updated[0].revenue_growth.origin == "held"
    assert "revenue_growth" in report["silent"]


def test_a_driver_nobody_argued_about_stays_held_and_is_reported_as_silent():
    """Silence is not agreement with the historical ratio. A model carrying one
    forecast driver and fifteen extrapolated ones must not read as a fully-formed
    view."""
    lenses = [_lens(LensName.DRIVERS, revenue_growth=0.25)]

    updated, report = from_lenses.apply(_seeded(), lenses)

    assert updated[0].gross_margin.origin == "held"
    assert set(report["silent"]) == {"gross_margin", "opex_pct_revenue", "tax_rate"}


def test_an_empty_ensemble_leaves_the_scaffold_untouched():
    updated, report = from_lenses.apply(_seeded(), [])

    assert all(
        d.origin == "held" for d in vars(updated[0]).values()
        if isinstance(d, project.Driver)
    )
    assert not report["applied"]


# --------------------------------------------------------------------------- #
# how far the view reaches
# --------------------------------------------------------------------------- #


def test_only_the_first_forecast_year_is_touched_by_default():
    """The lenses were asked about one quarter's worth of business, not about
    2035. Pushing a near-term view a decade out would turn it into a long-run
    assertion nobody made — the same error as holding trailing growth flat, just
    wearing a lens's name."""
    lenses = [_lens(LensName.DRIVERS, revenue_growth=0.25)]

    updated, report = from_lenses.apply(_seeded(3), lenses)

    assert updated[0].revenue_growth.origin == "forecast"
    assert updated[1].revenue_growth.origin == "held"
    assert updated[2].revenue_growth.origin == "held"
    assert report["years_touched"] == 1


def test_the_view_can_be_pushed_across_every_year_when_asked():
    lenses = [_lens(LensName.DRIVERS, revenue_growth=0.25)]

    updated, report = from_lenses.apply(_seeded(3), lenses, apply_to_all_years=True)

    assert all(y.revenue_growth.origin == "forecast" for y in updated)
    assert report["years_touched"] == 3


def test_the_projection_still_ties_after_the_ensemble_moves_the_drivers():
    """The articulation is untouched, so the balance sheet ties for exactly the
    reasons it tied before. This is the test that would catch someone wiring the
    lens output into the projection maths rather than into its inputs."""
    lenses = [
        _lens(LensName.DRIVERS, revenue_growth=0.45),
        _lens(LensName.MARGINS, gross_margin=0.52, opex_pct_revenue=0.38),
        _lens(LensName.FORENSICS, tax_rate=0.28),
    ]
    updated, _ = from_lenses.apply(_seeded(5), lenses)

    opening = project.OpeningBalances(
        cash=500.0, receivables=160.0, inventory=100.0, ppe_net=300.0,
        # assets 1,060 = liabilities 450 + equity 610. An opening that does not
        # tie can never produce a forecast year that does.
        payables=50.0, long_term_debt=400.0, equity=610.0, diluted_shares=100.0,
    )
    years = project.project(opening, 1000.0, updated)

    assert all(year.balanced for year in years)


def test_an_opening_that_does_not_tie_fails_at_the_source():
    """Rather than producing nine forecast years each carrying the same residual,
    which reads as broken projection logic. NVDA showed exactly that: -42.7bn in
    all nine columns, and the logic was fine — the opening was short three line
    items nobody had modelled."""
    crooked = project.OpeningBalances(cash=1000.0, equity=400.0)

    with pytest.raises(ValueError, match="opening balance sheet does not tie"):
        project.project(crooked, 1000.0, _seeded(1))
