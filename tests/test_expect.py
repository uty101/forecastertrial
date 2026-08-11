"""Layer E — what is already expected, before any lens forms a view.

Two parts that did not exist. The landing distribution is the Guidance lens's
entire edge and `EvidenceStore.landing` was never assigned. The swing factors
replace an asserted materiality with a measured one.
"""

from __future__ import annotations

import pytest

from forecaster.pipeline.e_expect import landing, swing
from forecaster.schemas import Basis, Guidance


def _landed(actuals: list[float], low: float = 89.0, high: float = 93.0):
    return [
        landing.Landed(f"2026Q{i}", "revenue", low, high, a)
        for i, a in enumerate(actuals, 1)
    ]


# --------------------------------------------------------------------------- #
# E2 — the landing distribution
# --------------------------------------------------------------------------- #


def test_position_locates_the_actual_inside_the_guided_range():
    """0 is the low end, 0.5 the midpoint consensus assumes by default, 1 the
    high end."""
    assert landing.Landed("q", "revenue", 80.0, 100.0, 90.0).position == 0.5
    assert landing.Landed("q", "revenue", 80.0, 100.0, 80.0).position == 0.0
    assert landing.Landed("q", "revenue", 80.0, 100.0, 100.0).position == 1.0


def test_beating_the_range_entirely_reads_above_one():
    """Not clipped. A company that clears its own top end is telling you
    something, and clamping it to 1.0 would erase exactly that."""
    assert landing.Landed("q", "revenue", 80.0, 100.0, 110.0).position == 1.5


def test_a_point_guide_has_no_position_rather_than_an_infinite_one():
    """A zero-width range is a point guide, not a range. Dividing by it produces
    an infinity that then travels through the median as an ordinary-looking
    number."""
    assert landing.Landed("q", "revenue", 90.0, 90.0, 92.0).position is None


def test_too_few_quarters_returns_nothing_rather_than_a_number():
    """A landing distribution from two quarters is an anecdote with a decimal
    point. Returning it would let a lens treat noise as a persistent pattern."""
    assert landing.build("T", _landed([92.0, 92.5])) is None


def test_the_shrunk_figure_pulls_a_thin_sample_toward_the_midpoint():
    """The whole reason the field exists. A company that landed near the top
    five times is not yet a habitual top-end lander — it is a company with five
    observations, and the arithmetic should say so rather than leaving a lens to
    guess how much to trust n."""
    thin = landing.build("T", _landed([92.4, 92.8, 91.9, 92.6, 93.1]))

    assert thin.median_position == pytest.approx(0.90, abs=0.01)
    assert thin.shrunk_position < thin.median_position
    assert thin.shrunk_position > 0.5


def test_a_longer_sample_is_shrunk_less():
    """The property that makes shrinkage the right tool rather than a haircut:
    evidence earns its weight."""
    short = landing.shrink(0.9, n=4)
    long = landing.shrink(0.9, n=20)

    assert long > short
    assert long > 0.75


def test_a_median_is_used_so_one_odd_quarter_does_not_set_the_pattern():
    """One quarter with a one-off charge would drag a mean off a persistent
    behaviour. Same robust-statistics rule as everywhere else here."""
    with_outlier = landing.build("T", _landed([92.4, 92.8, 91.9, 92.6, 60.0]))

    assert with_outlier.median_position > 0.6


def test_a_guide_is_paired_with_the_quarter_it_was_ABOUT():
    """The join that is easy to get wrong. A guide issued in Q1 is a guide about
    Q2, and pairing it with Q1's own result would measure only that the company
    can read its own income statement."""
    guides = [
        Guidance(metric="revenue", period="2026Q2", low=89.0, high=93.0,
                 basis=Basis.NON_GAAP, claim_id="c1"),
        Guidance(metric="revenue", period="2026Q3", low=95.0, high=99.0,
                 basis=Basis.NON_GAAP, claim_id="c2"),
    ]

    paired = landing.pair(guides, {"2026Q2": 92.0, "2026Q3": 98.0})

    assert [p.period for p in paired] == ["2026Q2", "2026Q3"]
    assert paired[0].actual == 92.0


def test_a_guide_with_no_reported_actual_is_dropped():
    """The current quarter's guide has no result yet, and pairing it with
    anything would be a leak."""
    guides = [
        Guidance(metric="revenue", period="2027Q1", low=89.0, high=93.0,
                 basis=Basis.NON_GAAP, claim_id="c1")
    ]

    assert landing.pair(guides, {}) == []


def test_a_guide_for_another_metric_is_not_counted():
    guides = [
        Guidance(metric="eps", period="2026Q2", low=1.0, high=1.2,
                 basis=Basis.NON_GAAP, claim_id="c1")
    ]

    assert landing.pair(guides, {"2026Q2": 1.1}, metric="revenue") == []


def test_the_block_says_what_to_use_and_shows_how_thin_it_is():
    """A lens handed 0.90 with no sample size will act on it. The block leads
    with the shrunk figure and shows the raw beside it."""
    block = landing.to_block(landing.build("T", _landed([92.4, 92.8, 91.9, 92.6])))

    assert "SHRUNK" in block
    assert "midpoint" in block


def test_no_distribution_tells_the_lens_to_say_so():
    """Silence would leave the lens anchoring on the midpoint without declaring
    that is what it did."""
    block = landing.to_block(None)

    assert "midpoint as the anchor" in block


# --------------------------------------------------------------------------- #
# E5 — swing factors
# --------------------------------------------------------------------------- #


PERTURBED = {
    "revenue_growth": 2.61,
    "gross_margin": 1.78,
    "opex_pct_revenue": 1.98,
    "tax_rate": 2.04,
}


def test_lines_are_ranked_by_what_they_are_worth_in_eps():
    """Comparable across lines, which is the property that makes it a weight. A
    100bp margin error and a 200bp growth error are not comparable as
    percentages and are perfectly comparable as EPS."""
    factors = swing.measure("T", 2.05, PERTURBED)

    assert [s.driver for s in factors.swings][:2] == [
        "revenue_growth", "gross_margin"
    ]
    assert factors.swings[0].eps_impact > factors.swings[1].eps_impact


def test_the_shares_sum_to_one_so_they_can_be_used_as_weights():
    factors = swing.measure("T", 2.05, PERTURBED)

    assert sum(s.share for s in factors.swings) == pytest.approx(1.0)


def test_a_line_beneath_the_noise_floor_is_marked_immaterial():
    """Three per cent of the answer is inside the model's own reproduction
    error, so a lens arguing about it is arguing beneath what the arithmetic
    downstream can resolve."""
    factors = swing.measure("T", 2.05, {**PERTURBED, "tax_rate": 2.0501})

    tax = next(s for s in factors.swings if s.driver == "tax_rate")
    assert not tax.material


def test_a_lens_with_no_material_driver_is_not_worth_running():
    """Not dropped for being bad — dropped for having nothing that moves THIS
    company's quarter, which is a statement about the company."""
    factors = swing.measure("T", 2.05, {"gross_margin": 1.50})

    assert factors.lenses_worth_running() == {"margins", "guidance", "forensics"}
    assert "macro" not in factors.lenses_worth_running()


def test_the_judge_gets_a_measured_weight_rather_than_an_asserted_one():
    factors = swing.measure("T", 2.05, PERTURBED)

    weights = factors.weights()
    assert sum(weights.values()) == pytest.approx(1.0)
    # Revenue growth dominates, and every lens attached to it carries that.
    assert weights["drivers"] > weights["forensics"]


def test_a_driver_the_model_could_not_price_is_named_not_dropped():
    """A silently missing driver would leave the remaining shares summing to one
    and looking complete."""
    factors = swing.measure("T", 2.05, {**PERTURBED, "gross_margin": None})

    assert any("gross_margin" in note for note in factors.skipped)
    assert all(s.driver != "gross_margin" for s in factors.swings)


def test_no_base_eps_measures_nothing_rather_than_everything():
    factors = swing.measure("T", None, PERTURBED)

    assert factors.swings == []
    assert factors.skipped


def test_the_naive_assumption_is_a_median_not_the_last_quarter():
    """One quarter with a one-off would make the counterfactual measure that
    quarter rather than the line."""
    assert swing.naive_value([0.60, 0.62, 0.61, 0.10]) == pytest.approx(0.605)


def test_the_block_marks_what_is_beneath_the_noise_floor():
    factors = swing.measure("T", 2.05, {**PERTURBED, "tax_rate": 2.0501})

    block = swing.to_block(factors)

    assert "SWING FACTORS" in block
    assert "reproduction error" in block
