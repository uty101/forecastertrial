"""The forecast side of the model.

The central test is that the balance sheet ties in every projected year. Almost
everything else here exists because there is a way to make it tie that is wrong —
a plug absorbing the error, a link left out, a flow counted on one statement and
not the other. A model that balances while being wrong is worse than one that
does not balance, because nothing downstream will question it.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.history import History, Observation
from forecaster.model import project

AS_OF = date(2026, 8, 4)


def _history(values: dict[str, dict[str, float]]) -> History:
    series: dict[str, list[Observation]] = {}
    for key, by_period in values.items():
        for period, value in by_period.items():
            fy, fp = int(period[:4]), period[4:]
            month = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}[fp]
            series.setdefault(key, []).append(
                Observation(
                    key=key, fy=fy, fp=fp, value=value, unit="USD",
                    period_end=date(fy, month, 28), filed=date(fy, month, 28),
                    form="10-Q", accession=f"000-{period}",
                )
            )
    return History("TEST", AS_OF, series, cik="0000000001")


def _quarters(fy: int, value: float) -> dict[str, float]:
    return {f"{fy}Q{q}": value for q in (1, 2, 3, 4)}


def _driver(value: float) -> project.Driver:
    return project.Driver(value, "held", "test")


def _drivers(fy: int, **overrides) -> project.YearDrivers:
    base = {
        "revenue_growth": _driver(0.10),
        "gross_margin": _driver(0.60),
        "opex_pct_revenue": _driver(0.30),
        "da_pct_revenue": _driver(0.05),
        "capex_pct_revenue": _driver(0.06),
        "tax_rate": _driver(0.20),
        "dso": _driver(60.0),
        "dio": _driver(90.0),
        "dpo": _driver(45.0),
        "sbc_pct_revenue": _driver(0.03),
        "interest_rate_debt": _driver(0.05),
        "interest_rate_cash": _driver(0.03),
        "dividend_pct_net_income": _driver(0.10),
        "buyback_pct_net_income": _driver(0.20),
        "debt_issued": _driver(0.0),
        "debt_repaid": _driver(0.0),
    }
    base.update({k: _driver(v) for k, v in overrides.items()})
    return project.YearDrivers(fy=fy, **base)


OPENING = project.OpeningBalances(
    cash=500.0, short_term_investments=200.0, receivables=160.0, inventory=100.0,
    other_current_assets=40.0, ppe_net=300.0, goodwill=80.0, intangibles=20.0,
    other_assets=60.0, payables=50.0, accrued_liabilities=70.0,
    deferred_revenue=30.0, taxes_payable=20.0, short_term_debt=100.0,
    other_liabilities=40.0, long_term_debt=400.0, equity=750.0,
    diluted_shares=100.0,
)


def _project(n: int = 3, **overrides) -> list[project.ProjectedYear]:
    return project.project(
        OPENING, 1000.0, [_drivers(2027 + i, **overrides) for i in range(n)]
    )


# --------------------------------------------------------------------------- #
# the balance sheet has to tie
# --------------------------------------------------------------------------- #


def test_every_projected_year_balances():
    """The one that matters. Assets = liabilities + equity, in all of them.

    Not approximately, and not because cash absorbed the difference: cash comes
    off the cash flow statement and the check is computed against it afterwards.
    """
    years = _project(9)

    assert all(year.balanced for year in years)
    assert max(abs(year.balance_residual) for year in years) < 1e-6


@pytest.mark.parametrize(
    "field,value",
    [
        ("revenue_growth", 0.80),
        ("revenue_growth", -0.30),
        ("gross_margin", 0.10),
        ("dso", 200.0),
        ("dpo", 5.0),
        ("buyback_pct_net_income", 0.90),
        ("dividend_pct_net_income", 0.50),
        ("capex_pct_revenue", 0.40),
        ("debt_issued", 500.0),
        ("debt_repaid", 200.0),
        ("sbc_pct_revenue", 0.15),
    ],
)
def test_it_still_ties_under_any_single_driver(field: str, value: float):
    """A model that balances only on its default assumptions has a link that
    happens to cancel. Every driver is moved hard, one at a time."""
    years = _project(5, **{field: value})

    assert all(year.balanced for year in years), (
        f"{field}={value} broke the balance sheet"
    )


def test_cash_comes_from_the_cash_flow_statement():
    """Not a plug. If cash were solved backwards from the balance sheet the
    model would tie by construction and the check would test nothing."""
    year = _project(1)[0]

    assert year.balance["cash"] == pytest.approx(
        year.cashflow["cash_open"] + year.cashflow["net_change_cash"]
    )
    assert year.cashflow["net_change_cash"] == pytest.approx(
        year.cashflow["cfo"] + year.cashflow["cfi"] + year.cashflow["cff"]
    )


def test_cash_rolls_from_one_year_to_the_next():
    years = _project(3)

    for previous, current in zip(years, years[1:], strict=False):
        assert current.cashflow["cash_open"] == pytest.approx(
            previous.cashflow["cash_close"]
        )


def test_ppe_rolls_forward_by_capex_less_depreciation():
    """The link that makes capex a balance-sheet event rather than only a cash
    one. Leave it out and PP&E is frozen while the company spends on it."""
    year = _project(1)[0]

    assert year.balance["ppe_net"] == pytest.approx(
        OPENING.ppe_net + abs(year.cashflow["capex"]) - year.cashflow["depreciation"]
    )


def test_equity_rolls_by_earnings_less_returns_plus_stock_compensation():
    year = _project(1)[0]

    assert year.balance["equity"] == pytest.approx(
        OPENING.equity
        + year.income["net_income"]
        - abs(year.cashflow["dividends"])
        - abs(year.cashflow["buyback"])
        + year.cashflow["sbc"]
    )


def test_stock_compensation_hits_both_statements_or_neither():
    """SBC is a non-cash expense that lands in equity: added back on the cash
    flow and added to equity on the balance sheet. Present on one and not the
    other and the sheet stops tying — which is the single commonest way a
    hand-built model breaks."""
    with_sbc = _project(1, sbc_pct_revenue=0.10)[0]
    without = _project(1, sbc_pct_revenue=0.0)[0]

    assert with_sbc.balanced and without.balanced
    assert with_sbc.cashflow["sbc"] > 0
    assert with_sbc.balance["equity"] > without.balance["equity"]


# --------------------------------------------------------------------------- #
# the rates
# --------------------------------------------------------------------------- #


def test_interest_is_computed_on_opening_balances():
    """Deliberately not the average of opening and closing.

    The textbook convention makes interest depend on closing cash, which depends
    on the cash flow, which depends on interest — the circular reference Excel
    resolves with iterative calculation and a circuit breaker. Opening balances
    remove it entirely, and this test is what stops someone "fixing" it back.
    """
    year = _project(1)[0]

    assert year.income["interest_expense"] == pytest.approx(
        (OPENING.long_term_debt + OPENING.short_term_debt) * 0.05
    )
    assert year.income["interest_income"] == pytest.approx(
        (OPENING.cash + OPENING.short_term_investments) * 0.03
    )


def test_interest_follows_the_debt_balance_year_to_year():
    """Issuing debt has to make next year's interest bigger, or the debt
    schedule is decoration."""
    years = _project(3, debt_issued=1000.0)

    assert years[1].income["interest_expense"] > years[0].income["interest_expense"]


def test_a_cash_pile_earns_and_it_reaches_pre_tax_income():
    """A company sitting on tens of billions earns real money on it, and holding
    that at a guess moves pre-tax income by more than most lines an analyst
    argues about."""
    rich = project.project(
        project.OpeningBalances(**{**vars(OPENING), "cash": 50_000.0}),
        1000.0, [_drivers(2027)],
    )[0]
    poor = _project(1)[0]

    assert rich.income["interest_income"] > poor.income["interest_income"]
    assert rich.income["pretax_income"] > poor.income["pretax_income"]


# --------------------------------------------------------------------------- #
# working capital
# --------------------------------------------------------------------------- #


def test_working_capital_is_driven_by_days_not_by_a_share_of_revenue():
    """DSO, DIO and DPO are the form an analyst argues in, and they are what
    makes the working-capital drag on a fast-growing business visible."""
    year = _project(1, dso=73.0)[0]

    assert year.balance["receivables"] == pytest.approx(
        year.income["revenue"] * 73.0 / 365.0
    )
    assert year.balance["dso"] == 73.0


def test_growth_at_constant_days_consumes_cash():
    """Hold DSO flat while revenue doubles and receivables double with it. That
    is cash the company does not have, and a model that misses it reports a
    growth company as far more cash-generative than it is."""
    growing = _project(1, revenue_growth=0.50)[0]
    flat = _project(1, revenue_growth=0.0)[0]

    assert growing.cashflow["cf_receivables"] < flat.cashflow["cf_receivables"]
    assert growing.cashflow["cf_receivables"] < 0


def test_paying_suppliers_more_slowly_releases_cash():
    """The sign convention on the payables line, which is the one that gets
    flipped: a rising liability is a cash inflow."""
    slow = _project(1, dpo=120.0)[0]
    fast = _project(1, dpo=10.0)[0]

    assert slow.cashflow["cf_payables"] > fast.cashflow["cf_payables"]


# --------------------------------------------------------------------------- #
# the seeded scaffold declares itself
# --------------------------------------------------------------------------- #


def _seedable() -> History:
    values: dict[str, dict[str, float]] = {}
    for fy, revenue in ((2025, 200.0), (2026, 250.0)):
        for key, value in (
            ("revenue", revenue), ("cost_of_revenue", revenue * 0.4),
            ("gross_profit", revenue * 0.6), ("opex", revenue * 0.3),
            ("depreciation", revenue * 0.05), ("capex", revenue * 0.06),
            ("sbc", revenue * 0.03), ("tax", revenue * 0.06),
            ("pretax_income", revenue * 0.3), ("net_income", revenue * 0.24),
            ("dividends", revenue * 0.02), ("buyback", revenue * 0.05),
            ("interest_expense", 5.0), ("interest_income", 3.0),
        ):
            values.setdefault(key, {}).update(_quarters(fy, value))
        for key, value in (
            ("cash", 500.0), ("receivables", 160.0), ("inventory", 100.0),
            ("payables", 50.0), ("ppe_net", 300.0), ("long_term_debt", 400.0),
            ("equity", 750.0), ("total_assets", 1460.0),
            ("total_liabilities", 710.0), ("diluted_shares", 100.0),
        ):
            values.setdefault(key, {}).update(_quarters(fy, value))
    # A partial third year, so the base-year rule has something to reject.
    for key in list(values):
        values[key]["2027Q1"] = values[key]["2026Q1"]
    return _history(values)


def test_the_base_year_is_the_last_COMPLETE_fiscal_year():
    """A forecast starting from a part-finished year silently understates the
    base, and every projected year inherits it."""
    assert project.last_complete_fiscal_year(_seedable()) == 2026


def test_every_seeded_driver_is_marked_held_rather_than_forecast():
    """The scaffold has to declare itself. A model whose forecast columns are all
    `held` is an extrapolation, and a reader who cannot see that will read it as
    a view somebody formed."""
    drivers = project.seed_drivers(_seedable(), 2026, through_fy=2030)

    assert all(d.all_held() for d in drivers)
    assert all("held flat" in d.gross_margin.note for d in drivers)


def test_the_seed_runs_to_the_requested_fiscal_year():
    drivers = project.seed_drivers(_seedable(), 2026, through_fy=2035)

    assert [d.fy for d in drivers] == list(range(2027, 2036))


def test_seeded_growth_fades_rather_than_compounding_flat():
    """NVDA grew 65% in FY2026. Held flat to 2035 that reaches $4.4 TRILLION of
    revenue, which discredits every other number on the sheet — including the
    balance check, which is real. The fade encodes only "growth decays", which is
    the weakest claim available and true of every business."""
    drivers = project.seed_drivers(_seedable(), 2026, through_fy=2035)

    assert drivers[0].revenue_growth.value == pytest.approx(0.25)
    assert drivers[-1].revenue_growth.value == pytest.approx(project.TERMINAL_GROWTH)
    rates = [d.revenue_growth.value for d in drivers]
    assert rates == sorted(rates, reverse=True)


def test_the_opening_sheet_ties_to_the_reported_totals():
    """The residual that broke it the first time.

    Enumerating line items always misses one for some filer — NVDA carries
    long-term investments, operating-lease assets and deferred tax assets a
    general model has no reason to project separately, and leaving them out left
    the opening 42.7bn short. The projection then inherited that gap into every
    forecast year as a constant residual, which is the signature of a broken
    opening rather than broken articulation.
    """
    opening = project.opening_from(_seedable(), 2026)

    assert opening.total_assets() == pytest.approx(1460.0)
    assert opening.total_assets() == pytest.approx(
        opening.total_liabilities() + opening.equity
    )


def test_a_seeded_projection_balances_end_to_end():
    """The whole scaffold, from filings to 2035, without anyone supplying a
    view."""
    history = _seedable()
    base = project.last_complete_fiscal_year(history)

    years = project.project(
        project.opening_from(history, base),
        project._fy_totals(history, base, "revenue"),
        project.seed_drivers(history, base, through_fy=2035),
    )

    assert len(years) == 9
    assert all(year.balanced for year in years)


def test_the_json_carries_every_driver_and_its_origin():
    years = _project(2)

    payload = project.to_json(years)

    assert payload[0]["label"] == "FY2027E"
    assert payload[0]["drivers"]["gross_margin"]["origin"] == "held"
    assert "balance_check" in payload[0]["balance"]
