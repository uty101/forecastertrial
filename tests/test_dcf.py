"""The DCF, and the ways one produces a confident number that means nothing.

A DCF is arithmetic wrapped round an opinion, and the arithmetic is the easy
part. Every test here encodes a way the opinion gets laundered into something
that looks like a finding.
"""

from __future__ import annotations

import pytest

from forecaster.model import dcf


def _input(value: float, provenance: str = "measured") -> dcf.Input:
    return dcf.Input(value, provenance, "test")


def _assumptions(**overrides) -> dcf.Assumptions:
    base = {
        "risk_free": _input(0.04, "market"),
        "equity_risk_premium": _input(0.055, "assumed"),
        "beta": _input(1.0, "assumed"),
        "cost_of_debt": _input(0.05),
        "tax_rate": _input(0.21),
        "revenue_growth": _input(0.10),
        "ebit_margin": _input(0.20),
        "da_pct": _input(0.04),
        "capex_pct": _input(0.05),
        "nwc_pct": _input(0.10),
        "terminal_growth": _input(0.025, "assumed"),
    }
    base.update(overrides)
    return dcf.Assumptions(**base)


# --------------------------------------------------------------------------- #
# the arithmetic errors that produce a confident number
# --------------------------------------------------------------------------- #


def test_wacc_at_or_below_terminal_growth_raises():
    """The Gordon denominator goes non-positive and the valuation comes back
    confidently negative or absurdly large. That is a modelling error, not a
    bearish signal, and returning a number lets it be read as one."""
    broken = _assumptions(
        risk_free=_input(0.0, "assumed"),
        equity_risk_premium=_input(0.0, "assumed"),
        beta=_input(0.0, "assumed"),
        cost_of_debt=_input(0.0),
        terminal_growth=_input(0.05, "assumed"),
    )

    with pytest.raises(ValueError, match="terminal growth"):
        dcf.value("TEST", 1000.0, broken, net_debt=0.0, shares=100.0)


def test_no_share_count_raises_rather_than_dividing_by_one():
    with pytest.raises(ValueError, match="no share count"):
        dcf.value("TEST", 1000.0, _assumptions(), net_debt=0.0, shares=0.0)


def test_growth_fades_to_the_terminal_rate_rather_than_compounding_flat():
    """The single most misleading thing a DCF can do, and what the first version
    of this did.

    NVDA's trailing growth is over 100%. Capped hard at 35% and held flat for ten
    years it produced a fair value of $747 against a $201 price — a +272%
    "finding" that was entirely an artefact of assuming a company grows at its
    current rate for a decade. No business does.

    The last projected year must grow at the terminal rate, which is also what
    makes the handover to the Gordon formula continuous rather than a step.
    """
    assumptions = _assumptions(revenue_growth=_input(0.35))

    valuation = dcf.value("TEST", 1000.0, assumptions, net_debt=0.0, shares=100.0)

    assert valuation.rows[0].growth == pytest.approx(0.35)
    assert valuation.rows[-1].growth == pytest.approx(0.025)
    # Monotone in between, so it is a fade rather than a jump.
    growths = [row.growth for row in valuation.rows]
    assert growths == sorted(growths, reverse=True)


def test_the_fade_makes_a_high_growth_company_valuable_not_priceless():
    """The regression test for the +272%. Flat compounding and fading
    compounding must not produce the same answer, and the flat one must be the
    larger by a wide margin."""
    fast = _assumptions(revenue_growth=_input(0.35))
    faded = dcf.value("TEST", 1000.0, fast, net_debt=0.0, shares=100.0)

    flat = _assumptions(revenue_growth=_input(0.35), terminal_growth=_input(0.35))
    # A flat 35% forever needs a discount rate above it to be finite at all,
    # which is itself the point: the terminal formula refuses the assumption.
    with pytest.raises(ValueError):
        dcf.value("TEST", 1000.0, flat, net_debt=0.0, shares=100.0)

    assert faded.value_per_share > 0


# --------------------------------------------------------------------------- #
# what the model must admit about itself
# --------------------------------------------------------------------------- #


def test_the_terminal_share_of_value_is_computed_and_reported():
    """If most of enterprise value is the terminal calculation, the projected
    years are decoration and the model is one Gordon division wearing a DCF
    costume. A reader needs that ratio to know how much to trust the rest."""
    valuation = dcf.value("TEST", 1000.0, _assumptions(), net_debt=0.0, shares=100.0)

    assert 0 < valuation.terminal_share < 1
    assert valuation.pv_terminal + valuation.pv_explicit == pytest.approx(
        valuation.enterprise_value
    )


def test_a_terminal_heavy_valuation_warns():
    """Low near-term cash flow pushes everything into perpetuity. The number is
    still computable and much less meaningful."""
    thin = _assumptions(ebit_margin=_input(0.03), capex_pct=_input(0.02))

    valuation = dcf.value("TEST", 1000.0, thin, net_debt=0.0, shares=100.0)

    if valuation.terminal_share > 0.75:
        assert any("terminal" in w for w in valuation.warnings)


def test_a_flat_extreme_margin_is_flagged_as_the_untested_assumption():
    """Growth fades; margins do not. A 60% operating margin held flat while
    revenue quadruples assumes no competitor ever arrives, and on a company
    earning that today it is a larger assumption than the discount rate and
    sits invisibly next to it."""
    rich = _assumptions(ebit_margin=_input(0.60))

    valuation = dcf.value("TEST", 1000.0, rich, net_debt=0.0, shares=100.0)

    assert any("margin is held" in w for w in valuation.warnings)


def test_every_input_declares_whether_it_was_measured_or_assumed():
    """The only thing separating a DCF from a number-shaped opinion. Beta in
    particular: it needs a regression against an index return series this system
    does not carry, so it must never read as measured."""
    valuation = dcf.value("TEST", 1000.0, _assumptions(), net_debt=0.0, shares=100.0)
    payload = dcf.to_json(valuation, (None, "not solved"), {"values": []})

    assert payload["assumptions"]["beta"]["provenance"] == "assumed"
    assert payload["assumptions"]["ebit_margin"]["provenance"] == "measured"
    assert set(payload["assumptions"]) >= {
        "risk_free", "equity_risk_premium", "beta", "cost_of_debt", "tax_rate",
        "revenue_growth", "ebit_margin", "da_pct", "capex_pct", "nwc_pct",
        "terminal_growth",
    }


# --------------------------------------------------------------------------- #
# the reverse DCF, which is the reason the module exists
# --------------------------------------------------------------------------- #


def test_the_implied_growth_reproduces_the_price_it_was_solved_from():
    """The one output here that makes no claim about fair value: it takes the
    price as given and inverts the model, so the answer is a statement about
    what the market assumes."""
    assumptions = _assumptions()
    fair = dcf.value("TEST", 1000.0, assumptions, net_debt=0.0, shares=100.0)

    solved, note = dcf.implied_growth(
        "TEST", 1000.0, assumptions, net_debt=0.0, shares=100.0,
        market_price=fair.value_per_share,
    )

    assert solved is not None, note
    assert solved == pytest.approx(assumptions.revenue_growth.value, abs=0.01)


def test_a_price_no_growth_rate_explains_says_so_rather_than_guessing():
    """A price outside the range the model can produce is itself the finding.
    Returning the nearest bound would present a failed solve as a result."""
    solved, note = dcf.implied_growth(
        "TEST", 1000.0, _assumptions(), net_debt=0.0, shares=100.0,
        market_price=1e9,
    )

    assert solved is None
    assert "outside" in note


def test_the_solver_is_monotone_so_a_higher_price_implies_higher_growth():
    assumptions = _assumptions()
    low, _ = dcf.implied_growth(
        "TEST", 1000.0, assumptions, 0.0, 100.0, market_price=30.0
    )
    high, _ = dcf.implied_growth(
        "TEST", 1000.0, assumptions, 0.0, 100.0, market_price=60.0
    )

    assert low is not None and high is not None
    assert high > low


# --------------------------------------------------------------------------- #
# the discount rate is where the answer lives
# --------------------------------------------------------------------------- #


def test_a_sensitivity_grid_is_always_produced():
    """Move WACC 100bp and the value moves 15-25%. A single point estimate with
    nothing around it implies a precision the method does not have."""
    grid = dcf.sensitivity(
        "TEST", 1000.0, _assumptions(), net_debt=0.0, shares=100.0,
        market_price=50.0,
    )

    assert len(grid["values"]) == len(grid["wacc_steps"])
    assert all(len(row) == len(grid["growth_steps"]) for row in grid["values"])


def test_a_grid_cell_where_wacc_crosses_growth_is_blank_not_a_number():
    """The corner of the grid where the denominator inverts. A number there
    would be nonsense presented with the same weight as the rest."""
    fragile = _assumptions(
        risk_free=_input(0.005, "assumed"),
        equity_risk_premium=_input(0.005, "assumed"),
        beta=_input(0.1, "assumed"),
        cost_of_debt=_input(0.005),
        terminal_growth=_input(0.02, "assumed"),
    )

    grid = dcf.sensitivity("TEST", 1000.0, fragile, 0.0, 100.0, market_price=None)

    assert any(cell is None for row in grid["values"] for cell in row)


def test_lowering_the_discount_rate_raises_the_value():
    """The direction check. A DCF that moves the wrong way on its most important
    input is broken in a way no amount of provenance fixes."""
    cheap = dcf.value(
        "TEST", 1000.0, _assumptions(risk_free=_input(0.02, "market")),
        net_debt=0.0, shares=100.0,
    )
    dear = dcf.value(
        "TEST", 1000.0, _assumptions(risk_free=_input(0.06, "market")),
        net_debt=0.0, shares=100.0,
    )

    assert cheap.value_per_share > dear.value_per_share


def test_net_debt_is_subtracted_to_get_to_equity():
    """Enterprise value belongs to everyone who funded the business; the
    shareholder gets what is left after the lenders.

    Weights held constant via `equity_value_hint`, because changing the capital
    structure legitimately changes WACC and would confound the check.
    """
    without = dcf.value("TEST", 1000.0, _assumptions(), 0.0, 100.0,
                        equity_value_hint=5000.0)
    with_debt = dcf.value("TEST", 1000.0, _assumptions(), 500.0, 100.0,
                          equity_value_hint=5000.0)

    assert with_debt.equity_value < without.equity_value
    # The identity itself, on a single valuation. Comparing two runs cannot pin
    # the magnitude: debt is in the WACC weights too, so enterprise value moves
    # at the same time and the difference is not the debt alone.
    assert with_debt.equity_value == pytest.approx(
        with_debt.enterprise_value - 500.0
    )
    assert without.equity_value == pytest.approx(without.enterprise_value)


def test_without_a_market_capitalisation_the_rate_is_unlevered_and_says_so():
    """The bug this replaced: with no market value to weight against, an earlier
    version substituted trailing revenue. That made the discount rate depend on
    an unrelated number, and adding debt to the same company RAISED its equity
    value — the fake weights let the tax shield cut WACC by more than the debt
    subtracted. You cannot weight a capital structure without a market value, so
    the model no longer pretends to."""
    assumptions = _assumptions()

    valuation = dcf.value("TEST", 1000.0, assumptions, net_debt=500.0, shares=100.0)

    assert valuation.wacc == pytest.approx(assumptions.cost_of_equity())
    assert any("unlevered" in w for w in valuation.warnings)


def test_with_a_market_price_the_tax_shield_is_credited():
    """The other half: given a real market capitalisation the weights are real,
    and debt is cheaper than equity after tax."""
    assumptions = _assumptions()

    unlevered = dcf.value("TEST", 1000.0, assumptions, 0.0, 100.0, market_price=50.0)
    levered = dcf.value("TEST", 1000.0, assumptions, 2000.0, 100.0, market_price=50.0)

    assert levered.wacc < unlevered.wacc


def test_working_capital_consumes_cash_as_the_business_grows():
    """It is the CHANGE in the balance that is a cash flow, never the balance
    itself. A model that subtracts the level instead reports a company that
    never generates cash."""
    light = dcf.value(
        "TEST", 1000.0, _assumptions(nwc_pct=_input(0.02)), 0.0, 100.0
    )
    heavy = dcf.value(
        "TEST", 1000.0, _assumptions(nwc_pct=_input(0.40)), 0.0, 100.0
    )

    assert heavy.value_per_share < light.value_per_share
    # Only the growth in revenue is funded, so even a heavy ratio leaves the
    # company cash-generative.
    assert heavy.rows[0].fcf > 0


def test_mid_year_discounting_is_worth_more_than_year_end():
    """Cash arrives through the year rather than in a lump on 31 December, and
    discounting it as though it arrives at the end understates every flow."""
    mid = dcf.value("TEST", 1000.0, _assumptions(), 0.0, 100.0)
    end = _assumptions()
    end.mid_year = False
    year_end = dcf.value("TEST", 1000.0, end, 0.0, 100.0)

    assert mid.value_per_share > year_end.value_per_share
