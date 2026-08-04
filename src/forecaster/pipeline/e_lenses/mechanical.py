"""The Mechanical lens. No LLM. Cannot hallucinate.

Four things that move a quarterly EPS number, are fully disclosed, are pure
arithmetic, and — crucially — *change after consensus is set*:

  1. FX translation. Consensus is struck at a point in time; currencies move
     continuously. A 3% move against a 60%-international revenue base is a ~1.8%
     revenue swing that most published models never refresh.
  2. Diluted share count. EPS is a ratio. Buybacks change the denominator every
     quarter and the authorisations are public. Model net income perfectly and
     miss the divisor and you still miss the print.
  3. Net interest. Net cash or debt times prevailing rates. Arithmetic.
  4. Calendar. 53rd weeks, quarter-end shifts, extra selling days.

Build this first. It is deterministic, unit-testable, will be working while
every LLM stage is still flaky, and it guarantees you have a defensible number
even if the reasoning layers disappoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from forecaster.schemas import Basis, LensName, LensOutput


@dataclass(frozen=True)
class GeoMix:
    """Revenue share by reporting currency, from the 10-K geographic table."""

    currency: str
    share: float  # fraction of total revenue


def fx_translation_impact(
    mix: list[GeoMix],
    rate_start: dict[str, float],
    rate_avg_quarter: dict[str, float],
) -> float:
    """Revenue impact of currency moves, as a fraction of total revenue.

    Rates are quoted as units of reporting currency per unit of foreign currency
    (i.e. higher = the foreign currency strengthened = a tailwind for a US filer).

    Returns e.g. +0.018 for a 1.8% tailwind.
    """
    impact = 0.0
    for geo in mix:
        if geo.currency not in rate_start or geo.currency not in rate_avg_quarter:
            continue
        start = rate_start[geo.currency]
        if start == 0:
            continue
        move = (rate_avg_quarter[geo.currency] - start) / start
        impact += geo.share * move
    return impact


def project_diluted_shares(
    shares_prior: float,
    buyback_spend: float,
    avg_price: float,
    sbc_dilution: float = 0.0,
) -> float:
    """Diluted share count for the quarter being forecast.

    shares_prior     diluted weighted-average from the last 10-Q cover page
    buyback_spend    run-rate repurchase spend for the quarter
    avg_price        average share price over the quarter
    sbc_dilution     gross new shares from stock comp and option exercise

    Note this is the *weighted average*, so a buyback executed evenly through the
    quarter removes roughly half its shares from this quarter's denominator.
    """
    if avg_price <= 0:
        raise ValueError("avg_price must be positive")
    retired = (buyback_spend / avg_price) * 0.5
    return shares_prior - retired + sbc_dilution


def net_interest(
    cash: float, debt: float, rate_cash: float, rate_debt: float, days: int = 91
) -> float:
    """Quarterly net interest income (positive) or expense (negative)."""
    year = 365.0
    return (cash * rate_cash - debt * rate_debt) * (days / year)


def calendar_adjustment(
    days_this_quarter: int, days_year_ago: int, revenue_is_daily: bool = True
) -> float:
    """Revenue impact of an uneven quarter, as a fraction.

    Retail and restaurant names run 4-5-4 calendars and periodically drop a
    53rd week. Ignoring it produces a ~7.7% error that looks like a forecasting
    miss and is actually a counting one.
    """
    if not revenue_is_daily or days_year_ago == 0:
        return 0.0
    return (days_this_quarter - days_year_ago) / days_year_ago


@dataclass
class MechanicalInputs:
    revenue_prior_year: float
    organic_growth: float  # from the Drivers lens, or a naive seasonal estimate
    geo_mix: list[GeoMix]
    rate_start: dict[str, float]
    rate_avg_quarter: dict[str, float]
    gross_margin: float
    opex: float
    tax_rate: float
    shares_prior: float
    buyback_spend: float
    avg_price: float
    sbc_dilution: float = 0.0
    cash: float = 0.0
    debt: float = 0.0
    rate_cash: float = 0.0
    rate_debt: float = 0.0
    days_this_quarter: int = 91
    days_year_ago: int = 91


def run(inputs: MechanicalInputs, claim_ids: list[str]) -> LensOutput:
    """Build the whole thing arithmetically. Every step is inspectable."""
    fx = fx_translation_impact(
        inputs.geo_mix, inputs.rate_start, inputs.rate_avg_quarter
    )
    cal = calendar_adjustment(inputs.days_this_quarter, inputs.days_year_ago)

    revenue = inputs.revenue_prior_year * (1 + inputs.organic_growth) * (1 + fx) * (
        1 + cal
    )

    gross_profit = revenue * inputs.gross_margin
    operating_income = gross_profit - inputs.opex
    interest = net_interest(
        inputs.cash,
        inputs.debt,
        inputs.rate_cash,
        inputs.rate_debt,
        inputs.days_this_quarter,
    )
    pretax = operating_income + interest
    net_income = pretax * (1 - inputs.tax_rate)

    shares = project_diluted_shares(
        inputs.shares_prior,
        inputs.buyback_spend,
        inputs.avg_price,
        inputs.sbc_dilution,
    )
    eps = net_income / shares

    reasoning = (
        f"FX {fx:+.2%} on a {sum(g.share for g in inputs.geo_mix):.0%} international "
        f"revenue base; calendar {cal:+.2%}; share count {inputs.shares_prior:,.0f} "
        f"-> {shares:,.0f} ({(shares / inputs.shares_prior - 1):+.2%}) from "
        f"${inputs.buyback_spend:,.0f} of buyback at ${inputs.avg_price:,.2f}; "
        f"net interest {interest:+,.0f}. No model judgment — arithmetic only."
    )

    return LensOutput(
        lens=LensName.MECHANICAL,
        eps=eps,
        revenue=revenue,
        basis=Basis.NON_GAAP,
        reasoning=reasoning,
        claim_ids=claim_ids,
        # Deterministic, so confidence reflects input quality, not model doubt.
        confidence=0.9,
        model_used=None,
    )
