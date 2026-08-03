"""Joining `History` to the three-statement model.

The conversion is not a copy, and every test here encodes one of the four ways
the two shapes differ — opening balances belonging to the previous quarter,
ratios that are not line items, levels that must become changes, and a forecast
quarter that has not happened. Getting any of them wrong produces a model that
evaluates cleanly and describes the wrong company.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.history import History, Observation
from forecaster.model import statements
from forecaster.model.inputs import inputs_for, next_period

AS_OF = date(2026, 8, 16)


def obs(key, period, value, filed="2026-05-20", unit="USD"):
    year, quarter = int(period[:4]), int(period[-1])
    return Observation(
        key=key, fy=year, fp=f"Q{quarter}", value=float(value), unit=unit,
        period_end=date(year, min(3 * quarter, 12), 28),
        filed=date.fromisoformat(filed), form="10-Q", accession="0001-26-000001",
    )


def history(**overrides) -> History:
    """Four quarters of a simple, internally consistent filer."""
    periods = ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]

    def ramp(key: str, step: float) -> list[Observation]:
        """A line item growing steadily, so ratios to revenue stay constant."""
        return [obs(key, p, step * (i + 1)) for i, p in enumerate(periods)]

    def flat(key: str, value: float, unit: str = "USD") -> list[Observation]:
        return [obs(key, p, value, unit=unit) for p in periods]

    series = {
        "revenue": ramp("revenue", 1000),
        "gross_profit": ramp("gross_profit", 500),
        "opex": ramp("opex", 200),
        "depreciation": ramp("depreciation", 50),
        "tax": ramp("tax", 30),
        "pretax_income": ramp("pretax_income", 300),
        "receivables": ramp("receivables", 100),
        "inventory": ramp("inventory", 80),
        "payables": ramp("payables", 60),
        "cash": ramp("cash", 400),
        "ppe_net": ramp("ppe_net", 700),
        "capex": ramp("capex", 90),
        "long_term_debt": flat("long_term_debt", 250),
        "equity": flat("equity", 5000),
        "diluted_shares": flat("diluted_shares", 1_000, unit="shares"),
        "buyback": flat("buyback", 40),
        "dividends": flat("dividends", 10),
        "other_income": flat("other_income", 5),
    }
    series.update(overrides)
    return History("TEST", AS_OF, series, cik="0000000001")


def test_next_period_rolls_the_fiscal_year():
    assert next_period("2027Q1") == "2027Q2"
    assert next_period("2026Q4") == "2027Q1"


def test_opening_balances_come_from_the_base_quarter():
    """Off by one here and every working-capital line describes last quarter."""
    inputs = inputs_for(history(), revenue=5000, avg_price=10.0)

    # 2026Q4 is the latest quarter: receivables 400, inventory 320, cash 1600.
    assert inputs.receivables_open == 400
    assert inputs.inventory_open == 320
    assert inputs.cash_open == 1600


def test_the_model_balances_on_a_real_shaped_history():
    """The decisive check. `balance_check` at close reduces algebraically to the
    imbalance at open, so a balancing model proves every link is wired right."""
    inputs = inputs_for(history(), revenue=5000, avg_price=10.0)
    model = statements.build(inputs)
    model.evaluate()

    ok, message = statements.check_balance(model)
    assert ok, message


def test_equity_open_is_a_residual_not_reported_equity():
    """The model's balance sheet is narrower than a filer's.

    It carries cash, receivables, inventory and net PP&E against payables, debt
    and equity — no short-term investments, goodwill or accrued liabilities. So
    equity must absorb what is not carried. Using reported `StockholdersEquity`
    would report a broken link on every real company when nothing is broken.
    """
    inputs = inputs_for(history(), revenue=5000, avg_price=10.0)

    carried = (
        inputs.cash_open + inputs.receivables_open
        + inputs.inventory_open + inputs.ppe_net_open
    )
    assert inputs.equity_open == carried - inputs.payables_open - inputs.debt
    assert inputs.equity_open != 5000                     # the reported figure
    assert "residual" in inputs.note_for("equity_open")


def test_a_missing_share_price_refuses_rather_than_guessing():
    """EPS is a ratio and the denominator is not in any filing.

    A filing reports what a buyback COST, never how many shares it retired. A
    1.0 placeholder does not fail — it retires `buyback_spend` shares, which on
    NVDA removed 5.2bn from a 24.4bn denominator and produced an EPS that looked
    entirely reasonable and was 27% too high.
    """
    for bad in (0.0, -5.0):
        with pytest.raises(ValueError, match="avg_price"):
            inputs_for(history(), revenue=5000, avg_price=bad)


def test_a_missing_share_count_refuses_rather_than_dividing_by_one():
    """EPS needs a denominator, and 1.0 is not a conservative default.

    Observed on Visa: a filer with several listed share classes tags its
    weighted-average count — and its diluted EPS — against a class dimension,
    and SEC's `companyfacts` endpoint returns only facts with no dimensions. So
    both are simply absent, for a company reporting them every quarter. No tag
    list fixes it; the numbers are not in the response.

    Falling back to one share reported net income as earnings per share.
    """
    thin = history(diluted_shares=[])

    with pytest.raises(ValueError, match="denominator"):
        inputs_for(thin, revenue=5000, avg_price=10.0)


def test_ratios_are_medians_so_one_odd_quarter_cannot_set_them():
    """A quarter with an inventory provision must not move the assumption."""
    spiked = history(
        gross_profit=[
            obs("gross_profit", "2026Q1", 500),
            obs("gross_profit", "2026Q2", 1000),
            obs("gross_profit", "2026Q3", 1500),
            obs("gross_profit", "2026Q4", 0),        # a write-down quarter
        ]
    )
    inputs = inputs_for(spiked, revenue=5000, avg_price=10.0)

    # Ratios per quarter are 0.5, 0.5, 0.5, 0.0 -> median 0.5, mean 0.375.
    assert inputs.gross_margin == pytest.approx(0.5)


def test_working_capital_levels_become_changes_against_forecast_revenue():
    """History stores levels; the cash flow statement needs the change."""
    inputs = inputs_for(history(), revenue=8000, avg_price=10.0)

    # Receivables run at a median 0.1 of revenue, so 8000 implies 800 closing
    # against an opening 400.
    assert inputs.delta_receivables == pytest.approx(800 - 400)


def test_balance_sheet_inputs_carry_their_claim():
    """"No number without provenance" reaches into the model, not just the store."""
    inputs = inputs_for(history(), revenue=5000, avg_price=10.0)

    claim = inputs.claim_for("receivables_open")
    assert claim is not None
    assert claim.value == 400
    assert claim.source.accession == "0001-26-000001"
    assert "0000000001".lstrip("0") in claim.source.uri
    # ...and a computed input explains itself instead.
    assert inputs.claim_for("delta_receivables") is None
    assert "median" in inputs.note_for("delta_receivables")
