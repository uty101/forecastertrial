"""The three-statement model and the GAAP↔non-GAAP bridge.

The links between the statements are pure arithmetic, which is exactly why they
are code rather than a model call — and why they get tests that encode the ways
a link breaks silently.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.model import statements
from forecaster.model.bridge import Bridge, BridgeItem, convert
from forecaster.schemas import Basis, Claim, Source, SourceKind

AS_OF = date(2026, 8, 16)
SOURCE = Source(kind=SourceKind.FILING_10Q, uri="https://sec.gov/x/10q.htm", as_of=AS_OF)


def _claim(label: str, value: float, unit: str = "USD") -> Claim:
    return Claim(
        id=f"c:{label}", label=label, value=value, unit=unit,
        source=SOURCE, verbatim_quote=f"{label} was {value}",
    )


def _balanced() -> statements.StatementInputs:
    """A set of inputs whose balance sheet ties by construction.

    Opening equity is chosen so assets = liabilities + equity at t0; the model's
    own links then have to keep it tied at t1, which is the actual test.
    """
    cash, receivables, inventory, ppe = 5_000.0, 2_000.0, 1_500.0, 8_000.0
    payables, debt = 1_200.0, 4_000.0
    equity = (cash + receivables + inventory + ppe) - (payables + debt)

    return statements.StatementInputs(
        revenue=10_000.0,
        gross_margin=0.60,
        opex=3_000.0,
        da=400.0,
        tax_rate=0.20,
        cash_open=cash,
        receivables_open=receivables,
        inventory_open=inventory,
        ppe_net_open=ppe,
        payables_open=payables,
        debt=debt,
        equity_open=equity,
        capex=500.0,
        buyback_spend=600.0,
        dividends=200.0,
        delta_receivables=300.0,
        delta_inventory=-100.0,
        delta_payables=150.0,
        shares_open=1_000.0,
        avg_price=50.0,
        sbc_dilution=5.0,
        notes={k: "synthetic fixture" for k in (
            "revenue", "gross_margin", "opex", "da", "tax_rate", "other_income",
            "cash_open", "receivables_open", "inventory_open", "ppe_net_open",
            "payables_open", "debt", "equity_open", "capex", "buyback_spend",
            "dividends", "delta_receivables", "delta_inventory",
            "delta_payables", "shares_open", "avg_price", "sbc_dilution",
        )},
    )


# --------------------------------------------------------------------------- #
# the links
# --------------------------------------------------------------------------- #


def test_balance_sheet_balances():
    """The single test that proves the links are wired correctly. An unbalanced
    model produces an entirely plausible EPS that is wrong for a reason no
    eyeball finds."""
    model = statements.build(_balanced())
    ok, message = statements.check_balance(model)
    assert ok, message


def test_a_broken_link_is_caught_by_the_balance_check():
    """Capex that leaves the cash flow but never arrives on the balance sheet is
    the canonical broken link. Simulated by spending cash on capex without the
    PP&E offset."""
    model = statements.build(_balanced())
    # Rebuild PP&E without the capex term — exactly the link most often missed.
    model.cells["ppe_net_close"].fn = lambda v: v["ppe_net_open"] - v["da"]
    model._cache.clear()

    ok, message = statements.check_balance(model)
    assert not ok
    assert "DOES NOT BALANCE" in message
    assert "do not use this model" in message


def test_eps_is_net_income_over_the_weighted_share_count():
    model = statements.build(_balanced())
    values = model.evaluate()
    assert values["eps"] == pytest.approx(
        values["net_income"] / values["shares_diluted"]
    )


def test_a_buyback_removes_only_half_its_shares_this_quarter():
    """A buyback executed evenly through the quarter sits in the weighted
    average for half the period. Treating it as fully retired overstates the
    denominator reduction and flatters EPS every single quarter."""
    model = statements.build(_balanced())
    values = model.evaluate()
    # $600 of buyback at $50 = 12 shares outright, 6 weighted.
    assert values["shares_retired"] == pytest.approx(6.0)
    assert values["shares_diluted"] == pytest.approx(1_000.0 - 6.0 + 5.0)


def test_working_capital_signs_are_the_right_way_round():
    """Receivables building CONSUMES cash. Getting this backwards produces a
    cash flow statement that looks fine and says the opposite of the truth."""
    inputs = _balanced()
    inputs.delta_receivables = 1_000.0
    inputs.delta_inventory = 0.0
    inputs.delta_payables = 0.0
    values = statements.build(inputs).evaluate()
    assert values["working_capital_change"] == pytest.approx(-1_000.0)

    inputs.delta_receivables = 0.0
    inputs.delta_payables = 1_000.0
    values = statements.build(inputs).evaluate()
    assert values["working_capital_change"] == pytest.approx(1_000.0)


def test_da_is_added_back_in_cash_flow_and_taken_off_ppe():
    """The same number, two statements, opposite directions. If D&A only
    appears in one of them the model is not linked."""
    values = statements.build(_balanced()).evaluate()
    assert values["cfo"] == pytest.approx(
        values["net_income"] + 400.0 + values["working_capital_change"]
    )
    assert values["ppe_net_close"] == pytest.approx(8_000.0 + 500.0 - 400.0)


def test_every_input_cell_carries_provenance_or_an_explicit_note():
    """`Cell.__post_init__` refuses an input with neither. This asserts the
    model as built has no cell that slipped through."""
    model = statements.build(_balanced())
    for key, cell in model.cells.items():
        if cell.is_input:
            assert cell.claim is not None or cell.note is not None, key


def test_provenance_walks_from_eps_back_to_the_filings():
    """The hover-to-see-source behaviour in the UI, and the proof that a
    forecast figure traces to a filing."""
    inputs = _balanced()
    inputs.claims = {"revenue": _claim("Revenue", 10_000.0)}
    model = statements.build(inputs)
    sources = model.provenance("eps")
    assert any(c.label == "Revenue" for c in sources)


def test_statements_render_as_three_statements_for_the_ui():
    rendered = statements.to_statements(statements.build(_balanced()))
    assert set(rendered) == {"income_statement", "cash_flow", "balance_sheet"}
    assert any(row["key"] == "eps" for row in rendered["income_statement"])
    assert any(row["key"] == "balance_check" for row in rendered["balance_sheet"])


# --------------------------------------------------------------------------- #
# the bridge
# --------------------------------------------------------------------------- #


def test_bridge_ties_to_the_reported_non_gaap_figure():
    bridge = Bridge(
        eps_gaap=1.80,
        items=[
            BridgeItem("Stock-based compensation", 0.45, claim=_claim("SBC", 0.45)),
            BridgeItem("Acquisition amortisation", 0.15, claim=_claim("Amort", 0.15)),
        ],
    )
    assert bridge.eps_non_gaap == pytest.approx(2.40)
    ok, message = bridge.verify(2.40)
    assert ok, message


def test_a_bridge_that_does_not_tie_refuses_loudly():
    """A missing reconciling item is a systematic error in one direction — the
    worst kind, because it looks like a bad model rather than a bug."""
    bridge = Bridge(
        eps_gaap=1.80,
        items=[BridgeItem("Stock-based compensation", 0.45, claim=_claim("SBC", 0.45))],
    )
    ok, message = bridge.verify(2.40)
    assert not ok
    assert "DOES NOT TIE" in message
    assert "do not forecast on this bridge" in message


def test_the_gap_can_be_the_31_percent_that_bites():
    """The median DJIA gap was 31% in one recent quarter. Forecast GAAP, get
    scored on non-GAAP consensus, and every company misses in the same
    direction every quarter."""
    bridge = Bridge(
        eps_gaap=1.00,
        items=[BridgeItem("Exclusions", 0.31, claim=_claim("Excl", 0.31))],
    )
    assert bridge.gap_pct == pytest.approx(0.31)


def test_a_recurring_one_off_is_flagged_as_structural():
    """Four consecutive quarters of the same 'unusual' item is a permanent cost
    the company has moved below the line. That is a Forensics finding, and it
    means the non-GAAP bar has quietly dropped."""
    bridge = Bridge(
        eps_gaap=1.00,
        items=[
            BridgeItem("Restructuring", 0.20, claim=_claim("R", 0.20),
                       quarters_recurring=6),
            BridgeItem("Legal settlement", 0.05, claim=_claim("L", 0.05),
                       quarters_recurring=1),
        ],
    )
    assert bridge.recurring_adjustment == pytest.approx(0.20)
    assert bridge.explain()[1]["recurring"] is True
    assert bridge.explain()[2]["recurring"] is False


def test_a_bridge_item_needs_a_claim_or_an_explicit_note():
    """An unsourced adjustment is exactly the invented number the provenance
    design exists to prevent."""
    with pytest.raises(ValueError, match="needs a Claim"):
        BridgeItem("Mystery adjustment", 0.30)
    assert BridgeItem("Estimated SBC", 0.30, note="modelled from the 10-K run rate")


def test_conversion_between_bases_uses_a_real_bridge():
    bridge = Bridge(
        eps_gaap=1.80,
        items=[BridgeItem("SBC", 0.60, claim=_claim("SBC", 0.60))],
    )
    assert convert(1.80, Basis.GAAP, Basis.NON_GAAP, bridge) == pytest.approx(2.40)
    assert convert(2.40, Basis.NON_GAAP, Basis.GAAP, bridge) == pytest.approx(1.80)
    assert convert(2.40, Basis.NON_GAAP, Basis.NON_GAAP, bridge) == pytest.approx(2.40)


def test_an_empty_bridge_converts_to_nothing_rather_than_guessing():
    """There is deliberately no default ratio. If you do not have this company's
    reconciling items you do not know its gap, and assuming the sector median is
    how you produce a confident forecast that is 31% wrong."""
    assert convert(1.80, Basis.GAAP, Basis.NON_GAAP, Bridge(eps_gaap=1.80)) == 1.80
