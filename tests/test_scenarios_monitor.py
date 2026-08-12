"""Bull/base/bear, kill criteria, and the post-mortem.

The version of each of these that is worth nothing is easy to build: three
numbers with no arithmetic between them, a caveat that cannot be checked, and an
error figure with no attribution. Every test here is about the difference.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.model import scenarios as S
from forecaster.pipeline import j_monitor as M

BASE_EPS = 2.05
BASE_DRIVERS = {"revenue_growth": 0.30, "gross_margin": 0.74}
EPS_FOR = {
    ("revenue_growth", 0.345): 2.31,
    ("revenue_growth", 0.255): 1.79,
    ("gross_margin", 0.851): 2.42,
    ("gross_margin", 0.629): 1.68,
}


def _scenarios(**kwargs):
    return S.build(
        "T", BASE_EPS, BASE_DRIVERS, EPS_FOR,
        material=["revenue_growth", "gross_margin"],
        immaterial=["tax_rate"],
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# bull / base / bear
# --------------------------------------------------------------------------- #


def test_the_cases_are_ordered_and_the_base_is_untouched():
    cases = _scenarios().cases

    assert [c.case for c in cases] == ["bear", "base", "bull"]
    assert cases[1].eps == BASE_EPS
    assert cases[0].eps < cases[1].eps < cases[2].eps


def test_every_case_carries_the_steps_that_produced_it():
    """The whole artefact. Three numbers are an opinion; three numbers with the
    arithmetic between them is something a reader can attack one line at a
    time."""
    bull = _scenarios().get("bull")

    assert len(bull.steps) == 2
    assert bull.eps == pytest.approx(BASE_EPS + bull.eps_delta)
    for step in bull.steps:
        assert step.eps_delta != 0
        assert step.base_value != step.case_value


def test_the_bridge_reconciles_from_base_to_the_case():
    bull = _scenarios().get("bull")

    bridge = bull.bridge(BASE_EPS)

    assert f"{BASE_EPS:.3f} base" in bridge
    assert f"{bull.eps:.3f} bull" in bridge


def test_steps_are_ordered_by_what_they_are_worth():
    """A reader should see the line that moves the case first."""
    bear = _scenarios().get("bear")

    deltas = [abs(s.eps_delta) for s in bear.steps]
    assert deltas == sorted(deltas, reverse=True)


def test_only_the_material_drivers_move():
    """A bear case that moves nine drivers at once is not a scenario, it is a
    mood. If gross margin is 29% of the answer and the tax rate is 3%, the bear
    case is a margin story and the tax rate stays where it is."""
    result = _scenarios()

    assert result.drivers_moved == ["revenue_growth", "gross_margin"]
    assert result.held == ["tax_rate"]
    for case in result.cases:
        assert all(s.driver != "tax_rate" for s in case.steps)


def test_what_was_held_is_stated_as_prominently_as_what_moved():
    """A scenario is defined as much by what it holds fixed, and that is the part
    a reader should check hardest."""
    block = S.to_block(_scenarios())

    assert "HELD AT BASE" in block
    assert "tax_rate" in block


def test_a_driver_the_model_could_not_price_is_skipped_not_guessed():
    result = S.build(
        "T", BASE_EPS, BASE_DRIVERS, {}, material=["revenue_growth"],
    )

    assert result.get("bull").eps == BASE_EPS
    assert result.get("bull").steps == []


def test_the_expected_value_is_probability_weighted():
    result = _scenarios()

    manual = sum(c.eps * c.probability for c in result.cases)
    assert result.expected_eps == pytest.approx(manual)


def test_the_block_says_the_probabilities_are_the_weak_part():
    """They are a subjective weight on three arbitrary points of a continuous
    distribution, and the interval to act on comes from V3's own residuals. A
    reader who takes the weighted number as the forecast has been misled."""
    block = S.to_block(_scenarios())

    assert "weakest" in block
    assert "residuals" in block


# --------------------------------------------------------------------------- #
# kill criteria
# --------------------------------------------------------------------------- #


def _criterion(**kwargs) -> M.KillCriterion:
    base = {
        "watch": "price_move",
        "what": "the shares gap before the print",
        "source": "yfinance daily bars",
        "invalidates": "the assumption that nothing is known that we do not know",
    }
    base.update(kwargs)
    return M.KillCriterion(**base)


def test_a_criterion_with_no_source_is_not_observable():
    """A criterion nobody can check before the print is a caveat wearing a
    criterion's clothes."""
    assert _criterion().observable
    assert not _criterion(source="").observable


def test_unobservable_criteria_are_surfaced_rather_than_dropped():
    """A forecast whose kill criteria are all unobservable has no kill criteria,
    and that is worth knowing at the time rather than afterwards."""
    monitor = M.Monitor("T", "2027Q2", criteria=[_criterion(source="")])

    assert len(monitor.unobservable) == 1


def test_a_price_gap_past_the_threshold_fires():
    check = M.check_price(_criterion(), 200.0, 220.0, date(2026, 8, 12))

    assert check.verdict == "triggered"
    assert "+10.0%" in check.detail


def test_a_price_move_inside_the_threshold_holds():
    check = M.check_price(_criterion(), 200.0, 205.0, date(2026, 8, 12))

    assert check.verdict == "holding"


def test_a_peer_that_has_not_reported_is_unobservable_not_holding():
    """"Nothing has happened" and "we cannot see whether anything happened" are
    different states, and collapsing them makes a monitor read as reassuring
    when it is blind."""
    criterion = _criterion(watch="peer_result", subject="AMD")

    check = M.check_peer(criterion, {}, date(2026, 8, 12))

    assert check.verdict == "unobservable"


def test_a_peer_missing_badly_fires():
    criterion = _criterion(watch="peer_result", subject="AMD", threshold=-0.05)

    check = M.check_peer(criterion, {"AMD": -0.12}, date(2026, 8, 12))

    assert check.verdict == "triggered"


def test_a_headline_match_fires_without_a_model_call():
    """This runs repeatedly between the forecast and the print. A monitor that
    costs tokens every time it looks is a monitor that gets turned off."""
    criterion = _criterion(watch="pre_announcement", what="preliminary|results")

    check = M.check_news(
        criterion, ["Acme announces preliminary third quarter results"],
        date(2026, 8, 12),
    )

    assert check.verdict == "triggered"


def test_having_no_criteria_says_so_rather_than_reporting_all_clear():
    monitor = M.Monitor("T", "2027Q2")

    assert "no kill criteria" in monitor.verdict()


def test_a_fired_criterion_names_what_it_invalidates():
    monitor = M.Monitor("T", "2027Q2", criteria=[_criterion()])
    monitor.checks = [M.check_price(_criterion(), 200.0, 230.0, date(2026, 8, 12))]

    block = M.to_block(monitor)

    assert "FIRED" in block
    assert "would invalidate" in block


# --------------------------------------------------------------------------- #
# the post-mortem
# --------------------------------------------------------------------------- #


def test_being_closer_than_consensus_is_the_score_that_matters():
    """Being right in absolute terms while further from the actual than the
    Street is a loss."""
    better = M.PostMortem("T", "q", forecast_eps=2.00, actual_eps=2.05,
                          consensus_eps=1.90)
    worse = M.PostMortem("T", "q", forecast_eps=2.30, actual_eps=2.05,
                         consensus_eps=2.00)

    assert better.beat_consensus is True
    assert worse.beat_consensus is False


def test_the_error_is_attributed_by_line_largest_first():
    result = M.PostMortem(
        "T", "q", 2.10, 2.05,
        lines=[
            M.LineError("tax_rate", 0.15, 0.16, -0.01),
            M.LineError("revenue_growth", 0.30, 0.26, 0.09),
        ],
    )

    assert [line.driver for line in result.attributed()][0] == "revenue_growth"


def test_offsetting_errors_are_caught_rather_than_scored_as_success():
    """The finding a headline error hides. Revenue 4% low and margin 80bp high
    can produce an EPS within a cent of the actual, and recording that as a good
    forecast teaches the process exactly the wrong lesson."""
    lucky = M.PostMortem(
        "T", "q", 2.05, 2.05,
        lines=[
            M.LineError("revenue_growth", 0.26, 0.30, -0.40),
            M.LineError("gross_margin", 0.78, 0.74, 0.41),
        ],
    )

    assert lucky.eps_error == pytest.approx(0.0)
    assert lucky.offsetting()
    assert "ERRORS OFFSET" in M.post_mortem_block(lucky)


def test_a_genuinely_accurate_forecast_is_not_flagged_as_lucky():
    honest = M.PostMortem(
        "T", "q", 2.05, 2.05,
        lines=[
            M.LineError("revenue_growth", 0.30, 0.30, 0.00),
            M.LineError("gross_margin", 0.74, 0.74, 0.01),
        ],
    )

    assert not honest.offsetting()
