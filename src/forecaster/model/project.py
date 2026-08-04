"""The forecast side of the model: the machinery, with the view left out.

A three-statement model is two halves. The left half is what the company
reported; `grid.py` builds that. The right half is what it will report, and it is
the half that makes the thing a model rather than a filing viewer — every
forecast column is a formula over a small set of DRIVERS, and the drivers are
where a human being's opinion enters.

**This module is the right half with the opinion left out.** Everything here is
the articulation: how a revenue growth rate becomes an income statement, how that
becomes a cash flow, how that becomes a balance sheet that ties. What it does not
contain is any view about what the drivers should be. Stage D seeds them by
holding the historical ratios flat and says so on every column; when the pipeline
produces a real forecast it overwrites them and nothing else changes.

That separation is deliberate. A model where the projection logic and the
projection assumptions are tangled together cannot be handed a different view
without being rewritten, and the whole point of the lens ensemble is that the
view is contested.

**Three things the articulation has to get right, or the model is decoration:**

*The balance sheet must tie in every forecast year.* Not approximately. If cash
is a plug that absorbs the error, the model will balance while being wrong, which
is worse than not balancing. Here cash comes from the cash flow statement and the
check is computed independently — see `_TIE` below for the identity it rests on.

*Interest is computed on OPENING balances, not average ones.* The textbook uses
the average of opening and closing, which makes interest depend on the cash
balance, which depends on the cash flow, which depends on interest. Excel
resolves that circularity with iterative calculation and a circuit-breaker
toggle; in code it is a fixed-point solve that can fail to converge. Opening
balances remove the circularity entirely at a cost of one year's drift on the
smallest line in the model, and the trade is worth it.

*Working capital is driven by DAYS, not by a percentage of revenue.* DSO, DIO and
DPO are the form an analyst actually argues in, they are comparable across
companies, and they make the working-capital drag on a fast-growing business
visible instead of buried in a ratio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import structlog

from forecaster.data.history import History

log = structlog.get_logger()

# How far out. Long enough for a growth company's fade to complete inside the
# explicit window rather than being buried in a terminal value.
FORECAST_TO_FISCAL_YEAR = 2035

DAYS_IN_YEAR = 365.0

# Where the scaffold fades growth to. Long-run nominal GDP: above it a company
# eventually becomes the economy.
TERMINAL_GROWTH = 0.025

Origin = Literal["held", "forecast", "identity"]


@dataclass
class Driver:
    """One assumption for one year, and where it came from.

    `held` means we took the historical ratio and did not touch it — a
    placeholder that declares itself rather than passing as a view. `forecast`
    means something actually formed an opinion. The distinction has to survive to
    the screen, because a model whose forecast columns are all `held` is an
    extrapolation and should be read as one.
    """

    value: float
    origin: Origin = "held"
    note: str = ""


@dataclass
class YearDrivers:
    """The full driver set for one forecast year.

    Everything a forecast column needs. Nothing here is computed from anything
    else here — these are the inputs, and the whole rest of the module is the
    formula over them.
    """

    fy: int
    revenue_growth: Driver
    gross_margin: Driver
    opex_pct_revenue: Driver
    da_pct_revenue: Driver
    capex_pct_revenue: Driver
    tax_rate: Driver
    dso: Driver
    dio: Driver
    dpo: Driver
    sbc_pct_revenue: Driver
    # rates
    interest_rate_debt: Driver
    interest_rate_cash: Driver
    # capital returns and financing
    dividend_pct_net_income: Driver
    buyback_pct_net_income: Driver
    debt_issued: Driver
    debt_repaid: Driver

    def all_held(self) -> bool:
        return all(
            d.origin == "held"
            for d in vars(self).values()
            if isinstance(d, Driver)
        )


@dataclass
class OpeningBalances:
    """The last reported balance sheet — where the forecast starts from."""

    cash: float = 0.0
    short_term_investments: float = 0.0
    receivables: float = 0.0
    inventory: float = 0.0
    other_current_assets: float = 0.0
    ppe_net: float = 0.0
    goodwill: float = 0.0
    intangibles: float = 0.0
    other_assets: float = 0.0
    payables: float = 0.0
    accrued_liabilities: float = 0.0
    deferred_revenue: float = 0.0
    taxes_payable: float = 0.0
    short_term_debt: float = 0.0
    other_liabilities: float = 0.0
    long_term_debt: float = 0.0
    equity: float = 0.0
    diluted_shares: float = 0.0

    def total_assets(self) -> float:
        return (
            self.cash + self.short_term_investments + self.receivables
            + self.inventory + self.other_current_assets + self.ppe_net
            + self.goodwill + self.intangibles + self.other_assets
        )

    def total_liabilities(self) -> float:
        return (
            self.payables + self.accrued_liabilities + self.deferred_revenue
            + self.taxes_payable + self.short_term_debt + self.other_liabilities
            + self.long_term_debt
        )


@dataclass
class ProjectedYear:
    """One forecast year, as three statements.

    Keys match `grid.py`'s row ids exactly, so a projected year drops into the
    same rows as a reported one and the sheet does not need to know which is
    which — only how to colour it.
    """

    fy: int
    label: str
    drivers: YearDrivers
    income: dict[str, float] = field(default_factory=dict)
    cashflow: dict[str, float] = field(default_factory=dict)
    balance: dict[str, float] = field(default_factory=dict)
    balanced: bool = False
    balance_residual: float = 0.0


def _days_balance(days: float, flow: float) -> float:
    """A working-capital balance implied by a days ratio.

    DSO, DIO and DPO are the form an analyst argues in, and they make the
    working-capital drag on a fast-growing business visible: hold DSO flat while
    revenue doubles and receivables double with it, which is cash the company
    does not have.
    """
    return days / DAYS_IN_YEAR * abs(flow)


def project(
    opening: OpeningBalances,
    base_revenue: float,
    drivers: list[YearDrivers],
) -> list[ProjectedYear]:
    """Roll the statements forward. Deterministic, and the balance check is real.

    The order is the order a model is built in and it is not arbitrary: the
    income statement needs interest, which needs opening debt and cash; the cash
    flow needs net income and the working-capital movements; the balance sheet
    needs the cash the cash flow produced. Anything else creates a circular
    reference.
    """
    # An opening sheet that does not tie can never produce a forecast year that
    # does: the articulation preserves the gap exactly, so it turns up as the
    # SAME residual in every projected column. That is a confusing symptom —
    # NVDA showed −42.7bn in all nine years and it read as broken projection
    # logic when the logic was fine and the opening was short three line items.
    # Failing here names the actual problem.
    opening_gap = opening.total_assets() - (
        opening.total_liabilities() + opening.equity
    )
    if abs(opening_gap) > max(abs(opening.total_assets()), 1.0) * 1e-6:
        raise ValueError(
            f"the opening balance sheet does not tie: assets "
            f"{opening.total_assets():,.0f} against liabilities and equity "
            f"{opening.total_liabilities() + opening.equity:,.0f}, a gap of "
            f"{opening_gap:,.0f}. Every projected year would carry this same "
            "residual and none of them would be the projection's fault."
        )

    years: list[ProjectedYear] = []
    revenue = base_revenue
    balances = OpeningBalances(**asdict(opening))

    for driver in drivers:
        opening_year = OpeningBalances(**asdict(balances))
        revenue = revenue * (1 + driver.revenue_growth.value)

        # ---- income statement ------------------------------------------- #
        gross_profit = revenue * driver.gross_margin.value
        cost_of_revenue = revenue - gross_profit
        opex = revenue * driver.opex_pct_revenue.value
        operating_income = gross_profit - opex
        da = revenue * driver.da_pct_revenue.value
        sbc = revenue * driver.sbc_pct_revenue.value

        # Interest on OPENING balances. The average-balance convention makes
        # interest depend on closing cash, which depends on the cash flow, which
        # depends on interest — a circular reference Excel resolves with
        # iterative calculation and a circuit breaker. Opening balances remove it
        # entirely for one year of drift on the smallest line in the model.
        opening_debt = opening_year.long_term_debt + opening_year.short_term_debt
        opening_cash = opening_year.cash + opening_year.short_term_investments
        interest_expense = opening_debt * driver.interest_rate_debt.value
        interest_income = opening_cash * driver.interest_rate_cash.value

        pretax_income = operating_income - interest_expense + interest_income
        tax = pretax_income * driver.tax_rate.value
        net_income = pretax_income - tax

        # ---- working capital, from days --------------------------------- #
        receivables = _days_balance(driver.dso.value, revenue)
        inventory = _days_balance(driver.dio.value, cost_of_revenue)
        payables = _days_balance(driver.dpo.value, cost_of_revenue)

        delta_receivables = receivables - opening_year.receivables
        delta_inventory = inventory - opening_year.inventory
        delta_payables = payables - opening_year.payables

        # ---- cash flow --------------------------------------------------- #
        capex = revenue * driver.capex_pct_revenue.value
        cfo = (
            net_income + da + sbc
            - delta_receivables - delta_inventory + delta_payables
        )
        cfi = -capex
        dividends = max(net_income, 0.0) * driver.dividend_pct_net_income.value
        buyback = max(net_income, 0.0) * driver.buyback_pct_net_income.value
        cff = (
            driver.debt_issued.value - driver.debt_repaid.value
            - dividends - buyback
        )
        net_change_cash = cfo + cfi + cff

        # ---- balance sheet ----------------------------------------------- #
        cash = opening_year.cash + net_change_cash
        ppe_net = opening_year.ppe_net + capex - da
        long_term_debt = (
            opening_year.long_term_debt
            + driver.debt_issued.value - driver.debt_repaid.value
        )
        # SBC is a non-cash expense that lands in equity, which is why it is
        # added back on the cash flow statement and added to equity here. Omit it
        # from one of the two and the sheet stops tying.
        equity = opening_year.equity + net_income - dividends - buyback + sbc

        balances = OpeningBalances(
            cash=cash,
            short_term_investments=opening_year.short_term_investments,
            receivables=receivables,
            inventory=inventory,
            other_current_assets=opening_year.other_current_assets,
            ppe_net=ppe_net,
            goodwill=opening_year.goodwill,
            intangibles=opening_year.intangibles,
            other_assets=opening_year.other_assets,
            payables=payables,
            accrued_liabilities=opening_year.accrued_liabilities,
            deferred_revenue=opening_year.deferred_revenue,
            taxes_payable=opening_year.taxes_payable,
            short_term_debt=opening_year.short_term_debt,
            other_liabilities=opening_year.other_liabilities,
            long_term_debt=long_term_debt,
            equity=equity,
            diluted_shares=opening_year.diluted_shares,
        )

        total_assets = balances.total_assets()
        total_liabilities = balances.total_liabilities()
        residual = total_assets - (total_liabilities + balances.equity)
        # Relative to total assets, not absolute: a $3 gap is rounding on a
        # $400bn sheet and a real bug on a $2m one.
        balanced = abs(residual) <= max(abs(total_assets), 1.0) * 1e-6

        shares = opening_year.diluted_shares
        years.append(
            ProjectedYear(
                fy=driver.fy,
                label=f"FY{driver.fy}E",
                drivers=driver,
                income={
                    "revenue": revenue,
                    "cost_of_revenue": cost_of_revenue,
                    "gross_profit": gross_profit,
                    "opex": opex,
                    "operating_income": operating_income,
                    "ebitda": operating_income + da,
                    "interest_expense": interest_expense,
                    "interest_income": interest_income,
                    "pretax_income": pretax_income,
                    "tax": tax,
                    "net_income": net_income,
                    "diluted_shares": shares,
                    "eps_diluted": net_income / shares if shares else 0.0,
                },
                cashflow={
                    "net_income": net_income,
                    "depreciation": da,
                    "sbc": sbc,
                    "cf_receivables": -delta_receivables,
                    "cf_inventory": -delta_inventory,
                    "cf_payables": delta_payables,
                    "cfo": cfo,
                    "capex": -capex,
                    "cfi": cfi,
                    "debt_issued": driver.debt_issued.value,
                    "debt_repaid": -driver.debt_repaid.value,
                    "buyback": -buyback,
                    "dividends": -dividends,
                    "cff": cff,
                    "net_change_cash": net_change_cash,
                    "cash_open": opening_year.cash,
                    "cash_close": cash,
                    "fcf": cfo - capex,
                },
                balance={
                    "cash": cash,
                    "short_term_investments": balances.short_term_investments,
                    "receivables": receivables,
                    "inventory": inventory,
                    "other_current_assets": balances.other_current_assets,
                    "current_assets": (
                        cash + balances.short_term_investments + receivables
                        + inventory + balances.other_current_assets
                    ),
                    "ppe_net": ppe_net,
                    "goodwill": balances.goodwill,
                    "intangibles": balances.intangibles,
                    "other_assets": balances.other_assets,
                    "total_assets": total_assets,
                    "payables": payables,
                    "accrued_liabilities": balances.accrued_liabilities,
                    "deferred_revenue": balances.deferred_revenue,
                    "taxes_payable": balances.taxes_payable,
                    "short_term_debt": balances.short_term_debt,
                    "current_liabilities": (
                        payables + balances.accrued_liabilities
                        + balances.deferred_revenue + balances.taxes_payable
                        + balances.short_term_debt
                    ),
                    "long_term_debt": long_term_debt,
                    "other_liabilities": balances.other_liabilities,
                    "total_liabilities": total_liabilities,
                    "equity": equity,
                    "liabilities_and_equity": total_liabilities + equity,
                    "balance_check": residual,
                    "dso": driver.dso.value,
                    "dio": driver.dio.value,
                    "dpo": driver.dpo.value,
                    "nwc": receivables + inventory - payables,
                    "net_debt": long_term_debt + balances.short_term_debt - cash,
                },
                balanced=balanced,
                balance_residual=residual,
            )
        )

    log.info(
        "projected", years=len(years),
        balanced=all(y.balanced for y in years),
        all_held=all(y.drivers.all_held() for y in years),
    )
    return years


# --------------------------------------------------------------------------- #
# seeding the drivers from history
# --------------------------------------------------------------------------- #


def _fy_totals(history: History, fy: int, key: str) -> float | None:
    """A fiscal year of a flow. None unless all four quarters are there."""
    values = [history.get(key, f"{fy}Q{q}") for q in (1, 2, 3, 4)]
    if any(v is None for v in values):
        return None
    return sum(v.value for v in values)


def _closing(history: History, fy: int, key: str) -> float | None:
    for quarter in (4, 3, 2, 1):
        observation = history.get(key, f"{fy}Q{quarter}")
        if observation is not None:
            return observation.value
    return None


def last_complete_fiscal_year(history: History) -> int | None:
    """The most recent fiscal year with four quarters reported.

    A forecast has to start from a complete year. Starting from a part-finished
    one silently understates the base, and every projected year inherits it.
    """
    counts: dict[int, int] = {}
    for period in history.periods():
        fy = int(period[:4])
        counts[fy] = counts.get(fy, 0) + 1
    complete = [fy for fy, n in counts.items() if n == 4]
    return max(complete) if complete else None


def seed_drivers(
    history: History,
    base_fy: int,
    through_fy: int = FORECAST_TO_FISCAL_YEAR,
) -> list[YearDrivers]:
    """Drivers held flat at the last reported year, every one marked `held`.

    This is a SCAFFOLD, not a forecast. Holding every ratio flat produces a model
    that balances, articulates correctly and predicts nothing — which is exactly
    what is wanted until there is a view to put in it. Marking each driver `held`
    is what stops the output being read as an opinion nobody formed.
    """
    revenue = _fy_totals(history, base_fy, "revenue") or 0.0
    cost = _fy_totals(history, base_fy, "cost_of_revenue")
    gross = _fy_totals(history, base_fy, "gross_profit")
    opex = _fy_totals(history, base_fy, "opex")
    da = _fy_totals(history, base_fy, "depreciation")
    capex = _fy_totals(history, base_fy, "capex")
    sbc = _fy_totals(history, base_fy, "sbc")
    tax = _fy_totals(history, base_fy, "tax")
    pretax = _fy_totals(history, base_fy, "pretax_income")
    net_income = _fy_totals(history, base_fy, "net_income")
    dividends = _fy_totals(history, base_fy, "dividends")
    buyback = _fy_totals(history, base_fy, "buyback")
    interest = _fy_totals(history, base_fy, "interest_expense")
    interest_income = _fy_totals(history, base_fy, "interest_income")

    prior_revenue = _fy_totals(history, base_fy - 1, "revenue")
    receivables = _closing(history, base_fy, "receivables") or 0.0
    inventory = _closing(history, base_fy, "inventory") or 0.0
    payables = _closing(history, base_fy, "payables") or 0.0
    debt = (_closing(history, base_fy, "long_term_debt") or 0.0) + (
        _closing(history, base_fy, "short_term_debt") or 0.0
    )
    cash = (_closing(history, base_fy, "cash") or 0.0) + (
        _closing(history, base_fy, "short_term_investments") or 0.0
    )

    def ratio(numerator: float | None, denominator: float | None,
              fallback: float, what: str) -> Driver:
        if numerator is None or not denominator:
            return Driver(fallback, "held", f"{what} not reported — assumed")
        return Driver(numerator / denominator, "held", f"{what}, held flat")

    template = {
        # Filled per year below, because it is the one driver that must not be
        # held flat.
        "revenue_growth": Driver(0.0, "held", ""),
        "gross_margin": ratio(gross, revenue, 0.4, f"FY{base_fy} gross margin"),
        "opex_pct_revenue": ratio(opex, revenue, 0.2,
                                  f"FY{base_fy} opex over revenue"),
        "da_pct_revenue": ratio(da, revenue, 0.03, f"FY{base_fy} D&A over revenue"),
        "capex_pct_revenue": ratio(abs(capex) if capex else None, revenue, 0.04,
                                   f"FY{base_fy} capex over revenue"),
        "tax_rate": ratio(tax, pretax, 0.21, f"FY{base_fy} effective tax rate"),
        "dso": ratio(receivables * DAYS_IN_YEAR, revenue, 45.0,
                     f"FY{base_fy} days sales outstanding"),
        "dio": ratio(inventory * DAYS_IN_YEAR, cost, 60.0,
                     f"FY{base_fy} days inventory outstanding"),
        "dpo": ratio(payables * DAYS_IN_YEAR, cost, 45.0,
                     f"FY{base_fy} days payables outstanding"),
        "sbc_pct_revenue": ratio(sbc, revenue, 0.0,
                                 f"FY{base_fy} SBC over revenue"),
        "interest_rate_debt": ratio(
            abs(interest) if interest else None, debt, 0.05,
            f"FY{base_fy} interest expense over the debt balance",
        ),
        # Measurable where the filer breaks out interest income, which many do.
        # Worth having rather than assuming: a company sitting on $60bn of cash
        # earns real money on it, and holding that at a guess moves pre-tax
        # income by more than most of the lines an analyst argues about.
        "interest_rate_cash": ratio(
            interest_income, cash, 0.03,
            f"FY{base_fy} interest income over cash and investments",
        ),
        "dividend_pct_net_income": ratio(
            abs(dividends) if dividends else None, net_income, 0.0,
            f"FY{base_fy} dividends over net income",
        ),
        "buyback_pct_net_income": ratio(
            abs(buyback) if buyback else None, net_income, 0.0,
            f"FY{base_fy} buybacks over net income",
        ),
        "debt_issued": Driver(0.0, "held", "no new issuance assumed"),
        "debt_repaid": Driver(0.0, "held", "no repayment assumed"),
    }

    # Growth is the one driver a scaffold cannot hold flat. NVDA grew 65% in
    # FY2026; held flat to 2035 that reaches $4.4 TRILLION of revenue, which
    # discredits every other number on the sheet — a reader who sees that stops
    # trusting the balance check too, and the balance check is real.
    #
    # So growth fades linearly from the last reported year to a long-run rate.
    # That is still a mechanical default rather than a view: it encodes only
    # "growth decays", which is the weakest possible claim and true of every
    # business. Anything more opinionated belongs in the forecast that replaces
    # this, not in the scaffold.
    start = revenue / prior_revenue - 1 if prior_revenue else 0.05
    years = list(range(base_fy + 1, through_fy + 1))
    out: list[YearDrivers] = []
    for index, fy in enumerate(years):
        fraction = index / (len(years) - 1) if len(years) > 1 else 1.0
        faded = start + (TERMINAL_GROWTH - start) * fraction
        drivers = {k: Driver(v.value, v.origin, v.note) for k, v in template.items()}
        drivers["revenue_growth"] = Driver(
            faded, "held",
            f"FY{base_fy} growth of {start:.1%} fading to {TERMINAL_GROWTH:.1%} "
            f"by FY{through_fy} — a placeholder, not a view",
        )
        out.append(YearDrivers(fy=fy, **drivers))
    return out


def opening_from(history: History, fy: int) -> OpeningBalances:
    """The closing balance sheet of `fy`, as the forecast's opening.

    **The `other` buckets are residuals against the REPORTED totals, and that is
    deliberate.** A model that enumerates line items will always miss one for
    some filer — NVDA carries long-term investments, operating-lease assets and
    deferred tax assets that a general model has no reason to project separately,
    and leaving them out left the opening sheet 42.7bn short. The projection then
    inherited that gap into every forecast year: a constant residual in all nine
    columns, which is the signature of a broken OPENING rather than broken
    articulation.

    So everything not separately modelled is swept into `other_assets` and
    `other_liabilities` and held flat. The opening then ties to what the company
    actually reported, by construction, and the balance check in the forecast
    years measures the projection instead of measuring this.
    """
    def at(key: str) -> float:
        return _closing(history, fy, key) or 0.0

    modelled_assets = (
        at("cash") + at("short_term_investments") + at("receivables")
        + at("inventory") + at("other_current_assets") + at("ppe_net")
        + at("goodwill") + at("intangibles")
    )
    modelled_liabilities = (
        at("payables") + at("accrued_liabilities") + at("deferred_revenue")
        + at("taxes_payable") + at("short_term_debt") + at("long_term_debt")
    )

    reported_assets = at("total_assets")
    reported_liabilities = at("total_liabilities")
    equity = at("equity")

    # Fall back to the enumerated sum when the filer did not tag a total, so a
    # missing subtotal cannot silently become a huge residual.
    other_assets = (
        reported_assets - modelled_assets if reported_assets else at("other_assets")
    )
    other_liabilities = (
        reported_liabilities - modelled_liabilities
        if reported_liabilities
        else at("other_liabilities")
    )

    return OpeningBalances(
        cash=at("cash"),
        short_term_investments=at("short_term_investments"),
        receivables=at("receivables"),
        inventory=at("inventory"),
        other_current_assets=at("other_current_assets"),
        ppe_net=at("ppe_net"),
        goodwill=at("goodwill"),
        intangibles=at("intangibles"),
        other_assets=other_assets,
        payables=at("payables"),
        accrued_liabilities=at("accrued_liabilities"),
        deferred_revenue=at("deferred_revenue"),
        taxes_payable=at("taxes_payable"),
        short_term_debt=at("short_term_debt"),
        other_liabilities=other_liabilities,
        long_term_debt=at("long_term_debt"),
        equity=equity,
        diluted_shares=at("diluted_shares"),
    )


def to_json(years: list[ProjectedYear]) -> list[dict[str, Any]]:
    return [
        {
            "fy": year.fy,
            "label": year.label,
            "balanced": year.balanced,
            "balance_residual": year.balance_residual,
            "income": year.income,
            "cashflow": year.cashflow,
            "balance": year.balance,
            "drivers": {
                name: {"value": d.value, "origin": d.origin, "note": d.note}
                for name, d in vars(year.drivers).items()
                if isinstance(d, Driver)
            },
        }
        for year in years
    ]
