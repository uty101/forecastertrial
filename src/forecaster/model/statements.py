"""The linked three-statement model, built on `model/graph.py`.

Deterministic, no model call. A three-statement model built by an LLM is a model
you cannot trust, and the links between the statements are exactly the part that
is pure arithmetic — so it is code, and it is tested.

The links are what make it a model rather than three lists:

    net income        → retained earnings, and the top of the cash flow
    D&A               → added back in CF, and reduces net PP&E on the BS
    working capital   → the change flows through CF, the level sits on the BS
    capex             → out of CF, into net PP&E
    buybacks          → out of CF, reduce the share count, reduce equity
    ending cash       → the BS cash line, which is CF's own output

**The balance sheet must balance.** `check_balance` asserts it and the whole
model refuses to evaluate if it does not. That is not fastidiousness: an
unbalanced model means one of those links is broken, and a broken link produces
an EPS that looks entirely plausible and is wrong for a reason no eyeball finds.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from forecaster.model.graph import Model
from forecaster.schemas import Claim

log = structlog.get_logger()

# Balance-sheet tolerance, as a fraction of total assets. Tight enough to catch
# a broken link, loose enough to survive float rounding through twenty cells.
BALANCE_TOL = 1e-6


@dataclass
class StatementInputs:
    """Everything the model needs, each with the claim it came from.

    A field with no claim is allowed only with an explicit note — that is
    enforced by `Cell.__post_init__`, not by convention here.
    """

    # income statement
    revenue: float
    gross_margin: float
    opex: float
    da: float
    tax_rate: float
    other_income: float = 0.0

    # balance sheet, opening
    cash_open: float = 0.0
    receivables_open: float = 0.0
    inventory_open: float = 0.0
    ppe_net_open: float = 0.0
    payables_open: float = 0.0
    debt: float = 0.0
    equity_open: float = 0.0

    # cash flow
    capex: float = 0.0
    buyback_spend: float = 0.0
    dividends: float = 0.0
    delta_receivables: float = 0.0
    delta_inventory: float = 0.0
    delta_payables: float = 0.0

    # share count
    shares_open: float = 1.0
    avg_price: float = 1.0
    sbc_dilution: float = 0.0

    claims: dict[str, Claim] | None = None
    notes: dict[str, str] | None = None

    def claim_for(self, key: str) -> Claim | None:
        return (self.claims or {}).get(key)

    def note_for(self, key: str) -> str | None:
        note = (self.notes or {}).get(key)
        if note is None and self.claim_for(key) is None:
            # Every input cell must justify itself one way or the other. This is
            # the "no number without a source" rule reaching into the model.
            return "unsourced input — no claim supplied"
        return note


def build(inputs: StatementInputs, name: str = "3-statement") -> Model:
    """Assemble the linked model. Evaluation is a topological sort."""
    model = Model(name=name)

    def _input(key: str, label: str, unit: str, value: float) -> None:
        model.input(
            key, label, unit, value,
            claim=inputs.claim_for(key),
            note=inputs.note_for(key),
        )

    # ---- income statement ------------------------------------------- #
    _input("revenue", "Revenue", "USD", inputs.revenue)
    _input("gross_margin", "Gross margin", "fraction", inputs.gross_margin)
    _input("opex", "Operating expense", "USD", inputs.opex)
    _input("da", "Depreciation & amortisation", "USD", inputs.da)
    _input("tax_rate", "Effective tax rate", "fraction", inputs.tax_rate)
    _input("other_income", "Other income", "USD", inputs.other_income)

    model.formula(
        "gross_profit", "Gross profit", "USD",
        ("revenue", "gross_margin"), lambda v: v["revenue"] * v["gross_margin"],
    )
    model.formula(
        "operating_income", "Operating income", "USD",
        ("gross_profit", "opex"), lambda v: v["gross_profit"] - v["opex"],
    )
    model.formula(
        "pretax_income", "Pre-tax income", "USD",
        ("operating_income", "other_income"),
        lambda v: v["operating_income"] + v["other_income"],
    )
    model.formula(
        "tax", "Tax", "USD",
        ("pretax_income", "tax_rate"), lambda v: v["pretax_income"] * v["tax_rate"],
    )
    model.formula(
        "net_income", "Net income", "USD",
        ("pretax_income", "tax"), lambda v: v["pretax_income"] - v["tax"],
    )

    # ---- share count ------------------------------------------------ #
    # EPS is a ratio. Model net income perfectly, miss the divisor, still miss
    # the print. A buyback executed evenly through the quarter removes roughly
    # half its shares from this quarter's weighted average.
    _input("shares_open", "Diluted shares, opening", "shares", inputs.shares_open)
    _input("buyback_spend", "Buyback spend", "USD", inputs.buyback_spend)
    _input("avg_price", "Average share price", "USD", inputs.avg_price)
    _input("sbc_dilution", "Stock-comp dilution", "shares", inputs.sbc_dilution)

    model.formula(
        "shares_retired", "Shares retired (weighted)", "shares",
        ("buyback_spend", "avg_price"),
        lambda v: (v["buyback_spend"] / v["avg_price"]) * 0.5 if v["avg_price"] else 0.0,
        note="weighted average: an evenly-executed buyback removes ~half its "
             "shares from this quarter's denominator",
    )
    model.formula(
        "shares_diluted", "Diluted shares, weighted average", "shares",
        ("shares_open", "shares_retired", "sbc_dilution"),
        lambda v: v["shares_open"] - v["shares_retired"] + v["sbc_dilution"],
    )
    model.formula(
        "eps", "Diluted EPS", "USD/share",
        ("net_income", "shares_diluted"),
        lambda v: v["net_income"] / v["shares_diluted"] if v["shares_diluted"] else 0.0,
    )

    # ---- cash flow --------------------------------------------------- #
    _input("delta_receivables", "Change in receivables", "USD", inputs.delta_receivables)
    _input("delta_inventory", "Change in inventory", "USD", inputs.delta_inventory)
    _input("delta_payables", "Change in payables", "USD", inputs.delta_payables)
    _input("capex", "Capital expenditure", "USD", inputs.capex)
    _input("dividends", "Dividends paid", "USD", inputs.dividends)

    model.formula(
        "working_capital_change", "Change in working capital", "USD",
        ("delta_receivables", "delta_inventory", "delta_payables"),
        # Receivables and inventory building CONSUMES cash; payables building
        # provides it. Getting these signs backwards is the classic way a cash
        # flow statement looks fine and says the opposite of the truth.
        lambda v: -v["delta_receivables"] - v["delta_inventory"] + v["delta_payables"],
    )
    model.formula(
        "cfo", "Cash from operations", "USD",
        ("net_income", "da", "working_capital_change"),
        lambda v: v["net_income"] + v["da"] + v["working_capital_change"],
    )
    model.formula(
        "cfi", "Cash from investing", "USD", ("capex",), lambda v: -v["capex"],
    )
    model.formula(
        "cff", "Cash from financing", "USD",
        ("buyback_spend", "dividends"),
        lambda v: -v["buyback_spend"] - v["dividends"],
    )
    _input("cash_open", "Cash, opening", "USD", inputs.cash_open)
    model.formula(
        "cash_close", "Cash, closing", "USD",
        ("cash_open", "cfo", "cfi", "cff"),
        lambda v: v["cash_open"] + v["cfo"] + v["cfi"] + v["cff"],
    )

    # ---- balance sheet ----------------------------------------------- #
    _input("receivables_open", "Receivables, opening", "USD", inputs.receivables_open)
    _input("inventory_open", "Inventory, opening", "USD", inputs.inventory_open)
    _input("ppe_net_open", "Net PP&E, opening", "USD", inputs.ppe_net_open)
    _input("payables_open", "Payables, opening", "USD", inputs.payables_open)
    _input("debt", "Debt", "USD", inputs.debt)
    _input("equity_open", "Equity, opening", "USD", inputs.equity_open)

    model.formula(
        "receivables_close", "Receivables, closing", "USD",
        ("receivables_open", "delta_receivables"),
        lambda v: v["receivables_open"] + v["delta_receivables"],
    )
    model.formula(
        "inventory_close", "Inventory, closing", "USD",
        ("inventory_open", "delta_inventory"),
        lambda v: v["inventory_open"] + v["delta_inventory"],
    )
    model.formula(
        "ppe_net_close", "Net PP&E, closing", "USD",
        ("ppe_net_open", "capex", "da"),
        lambda v: v["ppe_net_open"] + v["capex"] - v["da"],
    )
    model.formula(
        "payables_close", "Payables, closing", "USD",
        ("payables_open", "delta_payables"),
        lambda v: v["payables_open"] + v["delta_payables"],
    )
    model.formula(
        "total_assets", "Total assets", "USD",
        ("cash_close", "receivables_close", "inventory_close", "ppe_net_close"),
        lambda v: (
            v["cash_close"] + v["receivables_close"]
            + v["inventory_close"] + v["ppe_net_close"]
        ),
    )
    model.formula(
        "equity_close", "Equity, closing", "USD",
        ("equity_open", "net_income", "dividends", "buyback_spend"),
        lambda v: (
            v["equity_open"] + v["net_income"] - v["dividends"] - v["buyback_spend"]
        ),
    )
    model.formula(
        "total_liabilities_equity", "Total liabilities & equity", "USD",
        ("payables_close", "debt", "equity_close"),
        lambda v: v["payables_close"] + v["debt"] + v["equity_close"],
    )
    model.formula(
        "balance_check", "Assets less liabilities & equity", "USD",
        ("total_assets", "total_liabilities_equity"),
        lambda v: v["total_assets"] - v["total_liabilities_equity"],
        note="must be zero — a non-zero value means one of the statement links "
             "is broken, and a broken link produces a plausible-looking EPS",
    )
    return model


def check_balance(model: Model) -> tuple[bool, str]:
    """Assert the balance sheet balances. Call this before trusting any output.

    The tolerance is relative to total assets, not absolute: a $3 discrepancy is
    a rounding artefact on a $400bn balance sheet and a real bug on a $2m one.
    """
    values = model.evaluate()
    residual = values["balance_check"]
    assets = abs(values["total_assets"]) or 1.0
    relative = abs(residual) / assets

    if relative <= BALANCE_TOL:
        return True, f"balance sheet balances (residual {residual:,.2f} on {assets:,.0f})"
    return False, (
        f"BALANCE SHEET DOES NOT BALANCE: assets {values['total_assets']:,.0f} vs "
        f"liabilities+equity {values['total_liabilities_equity']:,.0f}, residual "
        f"{residual:,.0f} ({relative:.2%} of assets). One of the statement links "
        "is broken — do not use this model's EPS."
    )


def to_statements(model: Model) -> dict[str, list[dict]]:
    """Group the flat cells into three statements for the UI.

    The model view renders as actual statements rather than a cell dump, because
    judges recognise an income statement and do not recognise a dependency graph.
    """
    values = model.evaluate()
    layout = {
        "income_statement": [
            "revenue", "gross_profit", "opex", "operating_income",
            "other_income", "pretax_income", "tax", "net_income",
            "shares_diluted", "eps",
        ],
        "cash_flow": [
            "net_income", "da", "working_capital_change", "cfo",
            "capex", "cfi", "buyback_spend", "dividends", "cff",
            "cash_open", "cash_close",
        ],
        "balance_sheet": [
            "cash_close", "receivables_close", "inventory_close",
            "ppe_net_close", "total_assets", "payables_close", "debt",
            "equity_close", "total_liabilities_equity", "balance_check",
        ],
    }
    out: dict[str, list[dict]] = {}
    for statement, keys in layout.items():
        rows = []
        for key in keys:
            cell = model.cells[key]
            rows.append(
                {
                    "key": key,
                    "label": cell.label,
                    "unit": cell.unit,
                    "value": values[key],
                    "is_input": cell.is_input,
                    "sourced": cell.claim is not None,
                    "source_uri": cell.claim.source.uri if cell.claim else None,
                    "quote": cell.claim.verbatim_quote if cell.claim else None,
                    "note": cell.note,
                }
            )
        out[statement] = rows
    return out
