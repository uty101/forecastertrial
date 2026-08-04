"""The three statements as a banker would lay them out in Excel.

`statements.py` builds ONE quarter as a linked cell graph — the thing the
forecast is computed in. This builds the other half: the full reported history,
every line item, every quarter back to 2010, laid out the way a three-statement
model is actually laid out on a desk.

The conventions here are not decoration. They are what a person who reads models
for a living scans for, and getting them wrong is the difference between a
screen they can audit in ten seconds and one they have to be walked through:

**Periods across columns, line items down rows, oldest left.** Never transposed.

**Colour is determined by what a cell CONTAINS, never by what it means.** Blue is
a hardcoded actual keyed from a filing, black is a formula over cells on the same
statement, green is a link from another statement. That is the whole code, and it
is what lets you see at a glance which numbers we were told and which we worked
out. A row that changes colour part-way across is someone having overwritten a
formula — the single most useful diagnostic the convention buys.

**Annual columns are not one rule.** Income and cash-flow lines are SUM(Q1:Q4);
balance-sheet lines take the Q4 CLOSING BALANCE. Summing four quarters of cash
gives a number that looks like a year of cash generation and is meaningless, and
it is internally consistent enough to survive every other check. `lineitems.py`
already declares flow vs stock, so this is read rather than inferred.

**Ratios and weighted averages are not additive at all.** A weighted-average
share count does not sum and neither does EPS — the denominator changes every
quarter. Those are recomputed from their components for the annual column and
marked as derived rather than reported.

**Subtotals carry a TOP border, not a bottom one**, because a top border survives
a row being inserted into the block above it. That is the reason the convention
exists.

**Negatives in parentheses.** Never a minus sign, and never coloured red — red
means something else in a model, and using it for negatives destroys the code.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import structlog

from forecaster.data.history import History
from forecaster.data.lineitems import LINE_ITEMS

log = structlog.get_logger()

Origin = Literal["actual", "derived", "link"]
Style = Literal["header", "line", "subtotal", "total", "memo", "check"]
Unit = Literal["usd", "pct", "days", "shares", "per_share", "ratio"]

BY_KEY = {item.key: item for item in LINE_ITEMS}


# --------------------------------------------------------------------------- #
# the linkages
# --------------------------------------------------------------------------- #
#
# The canonical set, restricted to line items we actually carry. Direction is
# from the statement the number is COMPUTED on to the one that consumes it, which
# is what decides where the green font goes: the consuming cell is the link.
#
# This is the part of a three-statement model that makes it a model rather than
# three tables. A reader's first question about any linked cell is "where does
# this come from", and the answer travels with the cell.

@dataclass(frozen=True)
class Link:
    """Where a cell's value crosses a statement boundary."""

    statement: str
    row: str
    direction: Literal["from", "to"]
    note: str


LINKS: dict[tuple[str, str], tuple[Link, ...]] = {
    ("income", "net_income"): (
        Link("cashflow", "net_income", "to", "the first line of cash from operations"),
        Link("balance", "retained_earnings", "to",
             "retained earnings = opening + net income − dividends"),
    ),
    ("income", "tax"): (
        Link("balance", "taxes_payable", "to", "income taxes payable"),
    ),
    ("cashflow", "net_income"): (
        Link("income", "net_income", "from", "net income, as reported"),
    ),
    ("cashflow", "depreciation"): (
        Link("balance", "ppe_net", "to", "accumulated depreciation reduces net PP&E"),
    ),
    ("cashflow", "capex"): (
        Link("balance", "ppe_net", "to", "capital expenditure increases net PP&E"),
    ),
    ("cashflow", "cf_receivables"): (
        Link("balance", "receivables", "from", "the period-over-period change in AR"),
    ),
    ("cashflow", "cf_inventory"): (
        Link("balance", "inventory", "from",
             "the period-over-period change in inventory"),
    ),
    ("cashflow", "cf_payables"): (
        Link("balance", "payables", "from", "the period-over-period change in AP"),
    ),
    ("cashflow", "buyback"): (
        Link("balance", "treasury_stock", "to", "repurchases increase treasury stock"),
    ),
    ("cashflow", "dividends"): (
        Link("balance", "retained_earnings", "to", "dividends reduce retained earnings"),
    ),
    ("cashflow", "sbc"): (
        Link("balance", "paid_in_capital", "to", "SBC increases paid-in capital"),
    ),
    ("cashflow", "debt_issued"): (
        Link("balance", "long_term_debt", "to", "issuance increases long-term debt"),
    ),
    ("cashflow", "debt_repaid"): (
        Link("balance", "long_term_debt", "to", "repayment decreases long-term debt"),
    ),
    ("cashflow", "cash_close"): (
        Link("balance", "cash", "to", "ending cash IS the balance sheet cash line"),
    ),
    ("balance", "cash"): (
        Link("cashflow", "cash_close", "from",
             "ending cash from the cash flow statement"),
    ),
    ("balance", "retained_earnings"): (
        Link("income", "net_income", "from", "opening + net income − dividends"),
    ),
    ("balance", "ppe_net"): (
        Link("cashflow", "capex", "from", "opening + capex − depreciation"),
    ),
    ("balance", "long_term_debt"): (
        Link("income", "interest_expense", "to",
             "interest expense = average debt balance × rate"),
    ),
    ("income", "interest_expense"): (
        Link("balance", "long_term_debt", "from", "average debt balance × rate"),
    ),
}


# --------------------------------------------------------------------------- #
# row specifications
# --------------------------------------------------------------------------- #
#
# Order and hierarchy follow the standard layout: section headers, line items
# indented under them, subtotals struck where a banker expects to read one, and
# ratio rows in italic directly beneath the line they describe.
#
# `source` is either a line-item key (fetched from history), a computed row id,
# or None for a pure header.

@dataclass(frozen=True)
class RowSpec:
    id: str
    label: str
    style: Style = "line"
    level: int = 0
    unit: Unit = "usd"
    source: str | None = None
    # A ratio row's numerator and denominator, both row ids on this statement.
    ratio: tuple[str, str] | None = None
    # Rows summed to produce a subtotal, when it is not simply reported.
    fallback_sum: tuple[str, ...] | None = None
    note: str = ""


INCOME_ROWS: tuple[RowSpec, ...] = (
    RowSpec("revenue", "Revenue", "line", 0, "usd", "revenue"),
    RowSpec("revenue_growth", "% growth YoY", "memo", 1, "pct"),
    RowSpec("cost_of_revenue", "Cost of revenue", "line", 0, "usd", "cost_of_revenue"),
    RowSpec("gross_profit", "Gross profit", "subtotal", 0, "usd", "gross_profit"),
    RowSpec("gross_margin", "Gross margin %", "memo", 1, "pct",
            ratio=("gross_profit", "revenue")),
    RowSpec("rnd", "Research and development", "line", 1, "usd", "rnd"),
    RowSpec("rnd_pct", "% of revenue", "memo", 2, "pct", ratio=("rnd", "revenue")),
    RowSpec("sgna", "Selling, general and administrative", "line", 1, "usd", "sgna"),
    RowSpec("sgna_pct", "% of revenue", "memo", 2, "pct", ratio=("sgna", "revenue")),
    RowSpec("opex", "Total operating expenses", "subtotal", 0, "usd", "opex",
            fallback_sum=("rnd", "sgna")),
    RowSpec("opex_pct", "% of revenue", "memo", 1, "pct", ratio=("opex", "revenue")),
    RowSpec("operating_income", "Operating income", "subtotal", 0, "usd",
            "operating_income"),
    RowSpec("operating_margin", "Operating margin %", "memo", 1, "pct",
            ratio=("operating_income", "revenue")),
    RowSpec("ebitda", "EBITDA", "subtotal", 0, "usd",
            note="operating income + D&A; D&A is taken from the cash flow statement, "
                 "where it is reported, rather than stripped out of cost of revenue"),
    RowSpec("ebitda_margin", "EBITDA margin %", "memo", 1, "pct",
            ratio=("ebitda", "revenue")),
    RowSpec("interest_expense", "Interest expense", "line", 0, "usd",
            "interest_expense"),
    RowSpec("interest_income", "Interest income", "line", 0, "usd", "interest_income"),
    RowSpec("other_income", "Other income, net", "line", 0, "usd", "other_income"),
    RowSpec("pretax_income", "Pre-tax income", "subtotal", 0, "usd", "pretax_income"),
    RowSpec("tax", "Income tax expense", "line", 0, "usd", "tax"),
    RowSpec("tax_rate", "Effective tax rate %", "memo", 1, "pct",
            ratio=("tax", "pretax_income")),
    RowSpec("net_income", "Net income", "total", 0, "usd", "net_income"),
    RowSpec("net_margin", "Net margin %", "memo", 1, "pct",
            ratio=("net_income", "revenue")),
    RowSpec("diluted_shares", "Diluted shares, weighted average", "line", 0, "shares",
            "diluted_shares"),
    RowSpec("eps_diluted", "Diluted EPS", "total", 0, "per_share", "eps_diluted"),
    RowSpec("eps_growth", "% growth YoY", "memo", 1, "pct"),
)

BALANCE_ROWS: tuple[RowSpec, ...] = (
    RowSpec("assets_header", "Assets", "header"),
    RowSpec("cash", "Cash and equivalents", "line", 1, "usd", "cash"),
    RowSpec("short_term_investments", "Short-term investments", "line", 1, "usd",
            "short_term_investments"),
    RowSpec("receivables", "Accounts receivable", "line", 1, "usd", "receivables"),
    RowSpec("dso", "DSO", "memo", 2, "days"),
    RowSpec("inventory", "Inventory", "line", 1, "usd", "inventory"),
    RowSpec("dio", "DIO", "memo", 2, "days"),
    RowSpec("other_current_assets", "Other current assets", "line", 1, "usd",
            "other_current_assets"),
    RowSpec("current_assets", "Total current assets", "subtotal", 1, "usd",
            "current_assets"),
    RowSpec("ppe_net", "Property, plant and equipment, net", "line", 1, "usd",
            "ppe_net"),
    RowSpec("goodwill", "Goodwill", "line", 1, "usd", "goodwill"),
    RowSpec("intangibles", "Intangible assets, net", "line", 1, "usd", "intangibles"),
    RowSpec("long_term_investments", "Long-term investments", "line", 1, "usd",
            "long_term_investments"),
    RowSpec("operating_lease_assets", "Operating lease right-of-use assets", "line", 1,
            "usd", "operating_lease_assets"),
    RowSpec("deferred_tax_assets", "Deferred tax assets, net", "line", 1, "usd",
            "deferred_tax_assets"),
    RowSpec("other_assets", "Other non-current assets", "line", 1, "usd", "other_assets"),
    RowSpec("total_assets", "Total assets", "total", 0, "usd", "total_assets"),

    RowSpec("liabilities_header", "Liabilities and shareholders' equity", "header"),
    RowSpec("payables", "Accounts payable", "line", 1, "usd", "payables"),
    RowSpec("dpo", "DPO", "memo", 2, "days"),
    RowSpec("accrued_liabilities", "Accrued liabilities", "line", 1, "usd",
            "accrued_liabilities"),
    RowSpec("deferred_revenue", "Deferred revenue", "line", 1, "usd", "deferred_revenue"),
    RowSpec("taxes_payable", "Income taxes payable", "line", 1, "usd", "taxes_payable"),
    RowSpec("short_term_debt", "Short-term debt", "line", 1, "usd", "short_term_debt"),
    RowSpec("current_liabilities", "Total current liabilities", "subtotal", 1, "usd",
            "current_liabilities"),
    RowSpec("long_term_debt", "Long-term debt", "line", 1, "usd", "long_term_debt"),
    RowSpec("other_liabilities", "Other non-current liabilities", "line", 1, "usd",
            "other_liabilities"),
    RowSpec("total_liabilities", "Total liabilities", "subtotal", 0, "usd",
            "total_liabilities"),
    RowSpec("paid_in_capital", "Common stock and paid-in capital", "line", 1, "usd",
            "paid_in_capital"),
    RowSpec("retained_earnings", "Retained earnings", "line", 1, "usd",
            "retained_earnings"),
    RowSpec("treasury_stock", "Treasury stock", "line", 1, "usd", "treasury_stock"),
    RowSpec("aoci", "Accumulated other comprehensive income", "line", 1, "usd", "aoci"),
    RowSpec("equity", "Total shareholders' equity", "subtotal", 0, "usd", "equity"),
    RowSpec("liabilities_and_equity", "Total liabilities and equity", "total", 0, "usd",
            "liabilities_and_equity", fallback_sum=("total_liabilities", "equity")),
    RowSpec("balance_check", "Check", "check", 0, "usd",
            note="total assets − (total liabilities + equity). Zero, or the model "
                 "does not balance and no figure resting on it can be used."),
    RowSpec("nwc", "Net working capital", "memo", 0, "usd",
            note="receivables + inventory − payables"),
    RowSpec("net_debt", "Net debt", "memo", 0, "usd",
            note="short-term debt + long-term debt − cash"),
)

CASHFLOW_ROWS: tuple[RowSpec, ...] = (
    RowSpec("operating_header", "Cash flow from operating activities", "header"),
    RowSpec("net_income", "Net income", "line", 1, "usd", "net_income"),
    RowSpec("depreciation", "Depreciation and amortisation", "line", 1, "usd",
            "depreciation"),
    RowSpec("sbc", "Stock-based compensation", "line", 1, "usd", "sbc"),
    RowSpec("wc_header", "Changes in operating assets and liabilities", "header", 1),
    RowSpec("cf_receivables", "(Increase) / decrease in receivables", "line", 2, "usd",
            "cf_receivables"),
    RowSpec("cf_inventory", "(Increase) / decrease in inventory", "line", 2, "usd",
            "cf_inventory"),
    RowSpec("cf_payables", "Increase / (decrease) in payables", "line", 2, "usd",
            "cf_payables"),
    RowSpec("cfo", "Cash flow from operating activities", "subtotal", 0, "usd", "cfo"),

    RowSpec("investing_header", "Cash flow from investing activities", "header"),
    RowSpec("capex", "Capital expenditure", "line", 1, "usd", "capex"),
    RowSpec("capex_pct", "% of revenue", "memo", 2, "pct"),
    RowSpec("acquisitions", "Acquisitions, net of cash", "line", 1, "usd",
            "acquisitions"),
    RowSpec("cfi", "Cash flow from investing activities", "subtotal", 0, "usd", "cfi"),

    RowSpec("financing_header", "Cash flow from financing activities", "header"),
    RowSpec("debt_issued", "Debt issued", "line", 1, "usd", "debt_issued"),
    RowSpec("debt_repaid", "Debt repaid", "line", 1, "usd", "debt_repaid"),
    RowSpec("stock_issued", "Stock issued", "line", 1, "usd", "stock_issued"),
    RowSpec("buyback", "Share repurchases", "line", 1, "usd", "buyback"),
    RowSpec("dividends", "Dividends paid", "line", 1, "usd", "dividends"),
    RowSpec("cff", "Cash flow from financing activities", "subtotal", 0, "usd", "cff"),

    RowSpec("fx_on_cash", "Effect of FX on cash", "line", 0, "usd", "fx_on_cash"),
    RowSpec("net_change_cash", "Net change in cash", "subtotal", 0, "usd",
            "net_change_cash", fallback_sum=("cfo", "cfi", "cff", "fx_on_cash")),
    RowSpec("cash_open", "Cash — beginning of period", "line", 0, "usd"),
    RowSpec("cash_close", "Cash — end of period", "total", 0, "usd"),
    RowSpec("fcf", "Free cash flow", "memo", 0, "usd",
            note="cash from operations less capital expenditure"),
)

SPECS: dict[str, tuple[RowSpec, ...]] = {
    "income": INCOME_ROWS,
    "balance": BALANCE_ROWS,
    "cashflow": CASHFLOW_ROWS,
}

TITLES = {
    "income": "Income statement",
    "balance": "Balance sheet",
    "cashflow": "Cash flow statement",
}


# --------------------------------------------------------------------------- #
# periods
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Period:
    """One column."""

    id: str          # "2024Q3" or "FY2024"
    label: str       # "3Q24A" or "FY2024A"
    kind: Literal["quarter", "annual"]
    fy: int
    fp: str          # "Q1".."Q4" or "FY"
    # An annual column built from fewer than four quarters is not a year. Named
    # rather than hidden, because a short year that looks complete is the kind of
    # error that survives every other check.
    quarters: int = 4
    complete: bool = True


_PERIOD = re.compile(r"^(\d{4})Q([1-4])$")


def _quarter_periods(history: History) -> list[Period]:
    out = []
    for period in history.periods():
        match = _PERIOD.match(period)
        if not match:
            continue
        fy, q = int(match.group(1)), int(match.group(2))
        out.append(
            Period(period, f"{q}Q{str(fy)[2:]}A", "quarter", fy, f"Q{q}")
        )
    return out


def _annual_periods(quarters: list[Period]) -> list[Period]:
    counts: dict[int, int] = {}
    for period in quarters:
        counts[period.fy] = counts.get(period.fy, 0) + 1
    return [
        Period(f"FY{fy}", f"FY{fy}A", "annual", fy, "FY",
               quarters=n, complete=n == 4)
        for fy, n in sorted(counts.items())
    ]


# --------------------------------------------------------------------------- #
# cells and rows
# --------------------------------------------------------------------------- #


@dataclass
class Cell:
    value: float | None = None
    # What the cell CONTAINS, which is what sets its colour. Not what it means.
    origin: Origin = "derived"
    # The filing this number was read out of, when it was read rather than
    # computed. A blue cell with no source would be an assertion.
    source_uri: str | None = None
    filed: str | None = None
    form: str | None = None
    note: str | None = None


@dataclass
class Row:
    id: str
    label: str
    style: Style
    level: int
    unit: Unit
    cells: dict[str, Cell] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    note: str = ""

    def empty(self) -> bool:
        return all(c.value is None for c in self.cells.values())


@dataclass
class Grid:
    statement: str
    title: str
    ticker: str
    periods: list[Period]
    rows: list[Row]
    # Where the quarters do not sum to the year the company itself filed. Not
    # repaired — closing it would mean inventing a third number — but never
    # silent either.
    annual_variances: dict[str, dict[int, tuple[float, float]]] = field(
        default_factory=dict
    )


# --------------------------------------------------------------------------- #


def _value(history: History, key: str, period: Period) -> tuple[float | None, Cell]:
    """One cell, with the provenance that decides its colour."""
    if period.kind == "quarter":
        observation = history.get(key, period.id)
        if observation is None:
            return None, Cell()
        return observation.value, Cell(
            value=observation.value,
            origin="actual",
            source_uri=observation.accession or None,
            filed=observation.filed.isoformat(),
            form=observation.form,
        )

    item = BY_KEY.get(key)
    if item is None:
        return None, Cell()

    rows = [
        history.get(key, f"{period.fy}Q{q}") for q in (1, 2, 3, 4)
    ]
    present = [r for r in rows if r is not None]
    if not present:
        return None, Cell()

    if not item.additive:
        # A weighted-average share count does not sum and neither does EPS — the
        # denominator changes every quarter. Averaging the weighted averages is
        # the standard reconstruction of a full-year figure, and it is derived,
        # not reported.
        if len(present) < 4:
            return None, Cell(note=f"only {len(present)} of 4 quarters reported")
        mean = sum(r.value for r in present) / len(present)
        return mean, Cell(
            value=mean, origin="derived",
            note="average of four quarterly weighted averages; a weighted-average "
                 "share count is not additive",
        )

    if item.kind == "stock":
        # A balance is an instant, not a period. The year takes the CLOSING
        # balance. Summing four quarters of cash gives a number that looks like a
        # year of cash generation and is meaningless.
        closing = next((r for r in reversed(rows) if r is not None), None)
        if closing is None:
            return None, Cell()
        return closing.value, Cell(
            value=closing.value, origin="actual",
            source_uri=closing.accession or None,
            filed=closing.filed.isoformat(), form=closing.form,
            note=f"closing balance at {closing.period_end.isoformat()}",
        )

    total = sum(r.value for r in present)
    return total, Cell(
        value=total, origin="derived",
        note=(f"sum of {len(present)} quarters"
              + ("" if len(present) == 4 else " — an incomplete year")),
    )


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _days(balance: float | None, flow: float | None, period: Period) -> float | None:
    """DSO/DIO/DPO — a balance divided by a flow, scaled to days.

    Scaled on the period's ACTUAL length rather than a fixed 365. A balance is a
    full instant even in a part-finished year while the flow is only the quarters
    filed so far, so a partial FY2027 against 365 days printed DSO of 182 for a
    company that collects in 65. The balance was right, the flow was a quarter,
    and the ratio was three times reality.
    """
    if balance is None or not flow:
        return None
    days = 91.25 * (period.quarters if period.kind == "annual" else 1)
    return abs(balance) / abs(flow) * days


def build(history: History, kind: Literal["quarter", "annual"] = "quarter") -> dict[
    str, Grid
]:
    """The three statements as laid-out grids, from reported history alone.

    No forecast, no assumptions, no model call — this is what the company filed,
    arranged the way a model arranges it.
    """
    quarters = _quarter_periods(history)
    periods = quarters if kind == "quarter" else _annual_periods(quarters)
    if not periods:
        raise ValueError(f"{history.ticker}: no periods to lay out")

    grids: dict[str, Grid] = {}
    for statement, specs in SPECS.items():
        rows: list[Row] = []
        # Values already resolved on this statement, so a ratio row can divide
        # two rows above it without going back to history.
        resolved: dict[str, dict[str, float | None]] = {}

        for spec in specs:
            row = Row(spec.id, spec.label, spec.style, spec.level, spec.unit,
                      note=spec.note)
            row.links = list(LINKS.get((statement, spec.id), ()))
            values: dict[str, float | None] = {}

            for period in periods:
                cell = Cell()
                value: float | None = None

                if spec.source:
                    value, cell = _value(history, spec.source, period)

                if value is None and spec.fallback_sum:
                    parts = [
                        resolved.get(r, {}).get(period.id) for r in spec.fallback_sum
                    ]
                    if any(p is not None for p in parts):
                        value = sum(p for p in parts if p is not None)
                        cell = Cell(
                            value=value, origin="derived",
                            note="not reported; summed from "
                                 + ", ".join(spec.fallback_sum),
                        )

                if spec.ratio:
                    value = _ratio(
                        resolved.get(spec.ratio[0], {}).get(period.id),
                        resolved.get(spec.ratio[1], {}).get(period.id),
                    )
                    cell = Cell(value=value, origin="derived")

                values[period.id] = value
                if value is not None or cell.note:
                    cell.value = value
                    row.cells[period.id] = cell

            resolved[spec.id] = values
            rows.append(row)

        _computed_rows(statement, rows, resolved, periods, history)
        grids[statement] = Grid(
            statement=statement,
            title=TITLES[statement],
            ticker=history.ticker,
            periods=periods,
            rows=[r for r in rows if r.style in ("header", "check") or not r.empty()],
            annual_variances={
                item: {fy: tuple(pair) for fy, pair in years.items()}
                for item, years in (history.annual_gaps or {}).items()
                if BY_KEY.get(item) and BY_KEY[item].statement == _statement_of(statement)
            },
        )

    log.info(
        "grid_built", ticker=history.ticker, kind=kind, periods=len(periods),
        rows={k: len(g.rows) for k, g in grids.items()},
    )
    return grids


def _statement_of(statement: str) -> str:
    return {"income": "income", "balance": "balance", "cashflow": "cashflow"}[statement]


def _computed_rows(
    statement: str,
    rows: list[Row],
    resolved: dict[str, dict[str, float | None]],
    periods: list[Period],
    history: History,
) -> None:
    """Fill the rows that are arithmetic over other rows rather than filings.

    Kept separate from the main pass because these need a completed `resolved`
    map — a year-over-year growth row reads the column four periods back, and a
    check row reads two subtotals that appear after it in reading order.
    """
    index = {row.id: row for row in rows}

    def put(row_id: str, period: Period, value: float | None, note: str = "",
            origin: Origin = "derived") -> None:
        if row_id not in index or value is None:
            return
        index[row_id].cells[period.id] = Cell(value=value, origin=origin, note=note)
        resolved.setdefault(row_id, {})[period.id] = value

    def get(row_id: str, period_id: str) -> float | None:
        return resolved.get(row_id, {}).get(period_id)

    # Year-over-year growth: four quarters back, or one year back.
    step = 4 if periods[0].kind == "quarter" else 1
    for i, period in enumerate(periods):
        # A growth row is only meaningful between two periods of the same length.
        # The current fiscal year is partial by definition — NVDA's FY2027 held
        # one quarter — and comparing it to a full prior year printed −62%, which
        # is not a decline, it is three missing quarters.
        prior_period = periods[i - step] if i >= step else None
        comparable = (
            prior_period is not None
            and period.complete
            and prior_period.complete
        )
        prior = prior_period.id if comparable else None

        if statement == "income":
            for row_id, base in (("revenue_growth", "revenue"),
                                 ("eps_growth", "eps_diluted")):
                if prior:
                    now, was = get(base, period.id), get(base, prior)
                    if now is not None and was:
                        put(row_id, period, (now - was) / abs(was))

            # EBITDA is struck rather than reported: operating income plus the
            # D&A the cash flow statement discloses. Taking it from there rather
            # than trying to strip depreciation out of cost of revenue is the
            # only version that ties to something the company filed.
            operating = get("operating_income", period.id)
            da, _ = _value(history, "depreciation", period)
            if operating is not None and da is not None:
                put("ebitda", period, operating + da,
                    "operating income + D&A from the cash flow statement")
                margin = _ratio(operating + da, get("revenue", period.id))
                put("ebitda_margin", period, margin)

        elif statement == "balance":
            assets = get("total_assets", period.id)
            liabilities = get("total_liabilities", period.id)
            equity = get("equity", period.id)
            if assets is not None and liabilities is not None and equity is not None:
                put("balance_check", period, assets - (liabilities + equity),
                    "total assets − (total liabilities + equity)")

            receivables = get("receivables", period.id)
            inventory = get("inventory", period.id)
            payables = get("payables", period.id)
            if receivables is not None and payables is not None:
                put("nwc", period,
                    receivables + (inventory or 0.0) - payables,
                    "receivables + inventory − payables")

            cash = get("cash", period.id)
            debt = (get("long_term_debt", period.id) or 0.0) + (
                get("short_term_debt", period.id) or 0.0
            )
            if cash is not None and debt:
                put("net_debt", period, debt - cash,
                    "short-term debt + long-term debt − cash")

            revenue, _ = _value(history, "revenue", period)
            cogs, _ = _value(history, "cost_of_revenue", period)
            put("dso", period, _days(receivables, revenue, period),
                "receivables / revenue, annualised")
            put("dio", period, _days(inventory, cogs, period),
                "inventory / cost of revenue, annualised")
            put("dpo", period, _days(payables, cogs, period),
                "payables / cost of revenue, annualised")

        elif statement == "cashflow":
            # Opening and closing cash come off the balance sheet, which is what
            # makes them the link that closes the model.
            closing, closing_cell = _value(history, "cash", period)
            opening = None
            if i > 0:
                opening, _ = _value(history, "cash", periods[i - 1])
            put("cash_open", period, opening,
                "the prior period's closing balance-sheet cash", origin="link")
            put("cash_close", period, closing,
                "cash on the balance sheet at period end", origin="link")

            cfo = get("cfo", period.id)
            capex = get("capex", period.id)
            if cfo is not None and capex is not None:
                put("fcf", period, cfo - abs(capex),
                    "cash from operations less capital expenditure")

            revenue, _ = _value(history, "revenue", period)
            put("capex_pct", period, _ratio(abs(capex) if capex else None, revenue))

            # Net income on the cash flow statement is the income statement's
            # number, not an independent one. Marked as a link so it reads as
            # arriving from elsewhere.
            if "net_income" in index and period.id in index["net_income"].cells:
                index["net_income"].cells[period.id].origin = "link"
                index["net_income"].cells[period.id].note = (
                    "net income, from the income statement"
                )


# --------------------------------------------------------------------------- #


def _cell_json(cell: Cell, filings: dict[tuple, int]) -> dict[str, Any]:
    """A cell with its empty fields dropped and its filing referenced by index.

    Not micro-optimisation. `asdict` on every cell of 74 quarters × 87 rows × 3
    statements produced 1.9 MB, most of it the string "null"; dropping the nulls
    left 1.3 MB, most of THAT being the same accession number, filing date and
    form type repeated for every line item in a quarter — a 10-Q has one
    accession and sixty rows read out of it.

    Interning them into a table the cells index into takes it under 250 KB. The
    UI fetches this on page load, and a model sheet that takes two seconds to
    appear is one nobody scrolls.
    """
    row: dict[str, Any] = {"v": cell.value}
    if cell.origin != "derived":
        row["o"] = cell.origin
    if cell.source_uri or cell.filed or cell.form:
        key = (cell.source_uri, cell.filed, cell.form)
        row["s"] = filings.setdefault(key, len(filings))
    if cell.note:
        row["n"] = cell.note
    return row


def to_json(grids: dict[str, Grid]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, statement_grid in grids.items():
        # One table per statement, indexed by the cells. A 10-Q has a single
        # accession and sixty rows read out of it.
        filings: dict[tuple, int] = {}
        rows = [
            {
                "id": row.id,
                "label": row.label,
                "style": row.style,
                "level": row.level,
                "unit": row.unit,
                **({"note": row.note} if row.note else {}),
                **({"links": [asdict(link) for link in row.links]}
                   if row.links else {}),
                "cells": {k: _cell_json(c, filings) for k, c in row.cells.items()},
            }
            for row in statement_grid.rows
        ]
        out[name] = {
            "statement": statement_grid.statement,
            "title": statement_grid.title,
            "ticker": statement_grid.ticker,
            "periods": [asdict(p) for p in statement_grid.periods],
            "rows": rows,
            "filings": [
                {"uri": uri, "filed": filed, "form": form}
                for (uri, filed, form) in filings
            ],
            "annual_variances": {
                item: {str(fy): list(pair) for fy, pair in years.items()}
                for item, years in statement_grid.annual_variances.items()
            },
        }
    return out
