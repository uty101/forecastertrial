"""A discounted cash flow, and an honest account of what it is doing here.

**A DCF does not forecast a quarter.** This system is scored on quarterly EPS,
and nothing below moves that number. Building one anyway is a deliberate choice,
for one reason that survives scrutiny and one that does not.

The reason that survives: **run backwards, a DCF is the only instrument that
states what consensus is actually assuming.** Every other lens argues about the
next ninety days. Invert the model at today's share price and it answers a
different question — what long-run growth does this price require? — and that is
the thesis of the whole project stated in a single number. A quarter is a
rounding error in an intrinsic value; a *decade of assumed growth* is not, and
where the market's implied growth sits against the company's own realised growth
is a structural claim consensus cannot easily defend.

The reason that does not survive, and is therefore not claimed anywhere: that
our fair value is more right than the market's. It is not. A DCF is an opinion
with arithmetic wrapped round it, and the arithmetic is the easy part.

So this module reports the reverse DCF first and the forward valuation second,
and every input declares whether it was MEASURED from filings or ASSUMED. That
distinction is the only thing separating a DCF from a number-shaped opinion, and
professional models bury it in an assumptions tab nobody opens.

**Three things a DCF gets wrong that look right:**

*Terminal value is usually most of the answer.* If 80% of enterprise value sits
in the terminal calculation, the ten years of carefully projected cash flow are
decoration and the model is really a single Gordon-growth division. That share is
computed and reported, not hidden.

*WACC below terminal growth produces a negative denominator* and a valuation that
is confidently negative or absurdly large. It is a modelling error, not a market
view, and it raises here rather than returning a number.

*The discount rate is where the answer actually lives.* Move WACC 100bp and the
value moves 15–25%. A single point estimate with no sensitivity around it
implies a precision the method does not have, so a grid is always produced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

log = structlog.get_logger()

# Ten years. Long enough that a high-growth company's fade is inside the explicit
# window rather than buried in the terminal value, short enough that nobody
# pretends year 11 was forecast. Five would push more of NVDA's value into the
# terminal calculation, which is the failure mode above.
FORECAST_YEARS = 10

# The long-run growth a mature business can compound at forever. Above nominal
# GDP the company eventually becomes the economy, which is the one assumption in
# a DCF that is falsifiable on arithmetic alone.
DEFAULT_TERMINAL_GROWTH = 0.025

# The equity risk premium is an assumption in every model that has ever been
# built. Damodaran's implied ERP has sat near 4.5–5.5% for a decade.
DEFAULT_EQUITY_RISK_PREMIUM = 0.055

# Beta needs a regression against an index return series, which this system does
# not carry — the price source is deliberately unadjusted for splits, which makes
# it wrong for returns. 1.0 is the honest placeholder: it says "we did not
# measure this" rather than dressing an assumption as a finding.
DEFAULT_BETA = 1.0

DEFAULT_RISK_FREE = 0.042


Provenance = Literal["measured", "assumed", "market"]


@dataclass(frozen=True)
class Input:
    """One number and where it came from.

    The provenance is the point. A DCF where the reader cannot tell the measured
    inputs from the invented ones is a number-shaped opinion, and every input
    below is one or the other.
    """

    value: float
    provenance: Provenance
    note: str

    def __float__(self) -> float:
        return self.value


@dataclass
class Assumptions:
    """Everything the valuation rests on, each declaring its own provenance."""

    # discount rate build-up
    risk_free: Input
    equity_risk_premium: Input
    beta: Input
    cost_of_debt: Input
    tax_rate: Input
    # cash flow drivers, as a share of revenue
    revenue_growth: Input
    ebit_margin: Input
    da_pct: Input
    capex_pct: Input
    nwc_pct: Input
    # terminal
    terminal_growth: Input
    forecast_years: int = FORECAST_YEARS
    # Mid-year discounting. Cash arrives through the year rather than in a lump
    # on 31 December, and the half-year convention is standard for that reason.
    mid_year: bool = True

    def cost_of_equity(self) -> float:
        """CAPM. Not because it is right — because it is the one build-up a
        reader can check line by line."""
        return self.risk_free.value + self.beta.value * self.equity_risk_premium.value

    def wacc(self, equity_value: float, debt: float) -> float:
        total = equity_value + debt
        if total <= 0:
            return self.cost_of_equity()
        after_tax_debt = self.cost_of_debt.value * (1 - self.tax_rate.value)
        return (
            equity_value / total * self.cost_of_equity()
            + debt / total * after_tax_debt
        )


@dataclass
class YearRow:
    """One projected year, laid out the way a DCF schedule is laid out."""

    year: int
    label: str
    # The fading rate this year grew at. On the sheet it is the row that shows
    # the projection is a projection rather than an extrapolation.
    growth: float
    revenue: float
    ebit: float
    nopat: float
    da: float
    capex: float
    delta_nwc: float
    fcf: float
    discount_factor: float
    present_value: float


@dataclass
class Valuation:
    ticker: str
    base_revenue: float
    rows: list[YearRow]
    wacc: float
    terminal_growth: float
    terminal_value: float
    pv_terminal: float
    pv_explicit: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    shares: float
    value_per_share: float
    market_price: float | None = None
    assumptions: Assumptions | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def terminal_share(self) -> float:
        """How much of the answer is the terminal calculation.

        Above ~75% the ten years of projection are decoration and the model is a
        single Gordon-growth division wearing a DCF costume. Reported rather than
        buried, because it is the fastest way to know how much to trust it.
        """
        return self.pv_terminal / self.enterprise_value if self.enterprise_value else 0.0

    @property
    def upside(self) -> float | None:
        if not self.market_price:
            return None
        return self.value_per_share / self.market_price - 1


def _growth_for(assumptions: Assumptions, year: int) -> float:
    """Growth in a given year, fading linearly to the terminal rate.

    **A flat growth rate is the single most misleading thing a DCF can do**, and
    it is what the first version of this did. NVDA's trailing revenue growth is
    well over 100%; even capped hard at 35% and held flat, ten years of
    compounding produced a fair value of $747 against a $201 price — a +272%
    "finding" that is entirely an artefact of assuming a company keeps growing at
    its current rate for a decade.

    No business does. Growth decays as the addressable market fills and
    competition arrives, and every serious model handles that with an explicit
    fade from the current rate to the perpetual one. The fade is not a
    conservatism adjustment — it is the difference between a projection and an
    extrapolation.

    Linear because it is the version a reader can check in their head. Year 1
    grows at the measured rate; the final year grows at terminal growth, which is
    also what makes the Gordon handover continuous rather than a step change.
    """
    start = assumptions.revenue_growth.value
    end = assumptions.terminal_growth.value
    years = assumptions.forecast_years
    if years <= 1:
        return end
    fraction = (year - 1) / (years - 1)
    return start + (end - start) * fraction


def _fcf_series(assumptions: Assumptions, base_revenue: float) -> list[YearRow]:
    """Unlevered free cash flow, projected off the ratio base.

    FCF = EBIT × (1 − t) + D&A − capex − ΔNWC.

    D&A is added back because it is a non-cash charge already deducted inside the
    EBIT margin; capex is subtracted because it is cash that left. Getting those
    two the same way round is the commonest arithmetic error in a hand-built DCF
    and it flatters the answer.
    """
    rows: list[YearRow] = []
    revenue = base_revenue

    for year in range(1, assumptions.forecast_years + 1):
        previous_revenue = revenue
        revenue = previous_revenue * (1 + _growth_for(assumptions, year))
        ebit = revenue * assumptions.ebit_margin.value
        nopat = ebit * (1 - assumptions.tax_rate.value)
        da = revenue * assumptions.da_pct.value
        capex = revenue * assumptions.capex_pct.value
        # Working capital consumes cash as the business grows: it is the CHANGE
        # in the balance that is a cash flow, never the balance itself.
        delta_nwc = (revenue - previous_revenue) * assumptions.nwc_pct.value
        fcf = nopat + da - capex - delta_nwc
        rows.append(
            YearRow(
                year=year, label=f"Y{year}", growth=_growth_for(assumptions, year),
                revenue=revenue, ebit=ebit, nopat=nopat,
                da=da, capex=capex, delta_nwc=delta_nwc, fcf=fcf,
                discount_factor=0.0, present_value=0.0,
            )
        )
    return rows


def value(
    ticker: str,
    base_revenue: float,
    assumptions: Assumptions,
    net_debt: float,
    shares: float,
    market_price: float | None = None,
    equity_value_hint: float | None = None,
) -> Valuation:
    """Discount the projected cash flows and the terminal value.

    `equity_value_hint` seeds the capital-structure weights in WACC. A DCF is
    circular here — the discount rate depends on the market value of equity,
    which is what we are computing — and the standard resolution is to weight on
    the CURRENT market capitalisation rather than iterate to a fixed point.
    Iterating makes the model converge on its own opinion.
    """
    if shares <= 0:
        raise ValueError(f"{ticker}: no share count, so there is no per-share value")

    equity_for_weights = equity_value_hint
    if equity_for_weights is None and market_price and shares:
        equity_for_weights = market_price * shares

    warnings: list[str] = []
    if equity_for_weights is None:
        # No market capitalisation, so there is nothing to weight the debt
        # against. An earlier version substituted trailing revenue, which made
        # the discount rate depend on an unrelated number: adding debt to the
        # same company then RAISED its equity value, because the fake weights
        # let the tax shield cut WACC by more than the debt subtracted.
        #
        # Unlevered is the honest fallback. It says "we could not weight this"
        # instead of weighting it against a number that is not a market value.
        wacc = assumptions.cost_of_equity()
        warnings.append(
            "no market capitalisation to weight the capital structure against, "
            "so the discount rate is the unlevered cost of equity — the debt tax "
            "shield is not credited"
        )
    else:
        wacc = assumptions.wacc(equity_for_weights, max(net_debt, 0.0))

    growth = assumptions.terminal_growth.value

    if wacc <= growth:
        # Not a market view. A negative denominator produces a confidently
        # negative or absurdly large valuation, and the number looks like a
        # finding rather than the arithmetic error it is.
        raise ValueError(
            f"{ticker}: WACC of {wacc:.2%} is at or below terminal growth of "
            f"{growth:.2%}. The Gordon denominator is non-positive, so the "
            "terminal value is meaningless — not a bearish signal, a broken model."
        )

    rows = _fcf_series(assumptions, base_revenue)

    for row in rows:
        # Mid-year: cash arrives through the year rather than in a lump on the
        # last day of it.
        exponent = row.year - 0.5 if assumptions.mid_year else row.year
        row.discount_factor = 1 / (1 + wacc) ** exponent
        row.present_value = row.fcf * row.discount_factor

    final = rows[-1]
    terminal_value = final.fcf * (1 + growth) / (wacc - growth)
    # The terminal value is a lump at the END of the final year, whatever
    # convention the explicit flows used.
    pv_terminal = terminal_value / (1 + wacc) ** assumptions.forecast_years
    pv_explicit = sum(row.present_value for row in rows)
    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - net_debt

    if any(row.fcf < 0 for row in rows):
        warnings.append(
            "at least one projected year burns cash — the terminal value is then "
            "carrying more than the whole explicit period"
        )
    if assumptions.ebit_margin.value > 0.35:
        # Growth is faded; the margin is not. A 60% operating margin held flat
        # while revenue quadruples assumes no competitor ever arrives, and on a
        # company earning that today it is the heroic assumption in the model —
        # larger than the discount rate and invisible next to it.
        warnings.append(
            f"the {assumptions.ebit_margin.value:.0%} operating margin is held "
            f"flat for {assumptions.forecast_years} years while revenue compounds. "
            "Growth fades here; margins do not, and on a business earning this "
            "much that is the largest untested assumption in the valuation"
        )
    if final.revenue > base_revenue * 8:
        warnings.append(
            f"revenue reaches {final.revenue / base_revenue:.0f}x the trailing year "
            "by the final projected year"
        )
    if equity_value < 0:
        warnings.append(
            "equity value is negative: net debt exceeds the discounted cash flows"
        )

    valuation = Valuation(
        ticker=ticker,
        base_revenue=base_revenue,
        rows=rows,
        wacc=wacc,
        terminal_growth=growth,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        pv_explicit=pv_explicit,
        enterprise_value=enterprise_value,
        net_debt=net_debt,
        equity_value=equity_value,
        shares=shares,
        value_per_share=equity_value / shares,
        market_price=market_price,
        assumptions=assumptions,
        warnings=warnings,
    )

    if valuation.terminal_share > 0.75:
        warnings.append(
            f"{valuation.terminal_share:.0%} of enterprise value is the terminal "
            "calculation — the explicit years are close to decoration"
        )

    log.info(
        "dcf_valued", ticker=ticker, wacc=round(wacc, 4),
        per_share=round(valuation.value_per_share, 2),
        terminal_share=round(valuation.terminal_share, 3),
        warnings=len(warnings),
    )
    return valuation


# --------------------------------------------------------------------------- #
# the reverse DCF — the reason this module exists
# --------------------------------------------------------------------------- #


def implied_growth(
    ticker: str,
    base_revenue: float,
    assumptions: Assumptions,
    net_debt: float,
    shares: float,
    market_price: float,
    bounds: tuple[float, float] = (-0.30, 1.20),
    tolerance: float = 1e-4,
    max_iterations: int = 80,
) -> tuple[float | None, str]:
    """The revenue growth the current share price requires. Returns (rate, note).

    This is the only output here that makes no claim about fair value. It takes
    the price as given and inverts the model, so the answer is a statement about
    what the market is assuming rather than about what the company is worth. That
    makes it the one DCF number this project can defend: consensus is the thing
    we are trying to find structural weakness in, and this is consensus written
    as a growth rate over a decade.

    Bisection rather than Newton: the function is monotone in growth over any
    range that matters, and bisection cannot diverge. A DCF that fails to solve
    should say so, not wander off and return whatever it landed on.
    """
    low, high = bounds

    def per_share(growth: float) -> float | None:
        trial = Assumptions(**{**assumptions.__dict__,
                              "revenue_growth": Input(growth, "assumed", "solved")})
        try:
            return value(
                ticker, base_revenue, trial, net_debt, shares,
                market_price=market_price,
            ).value_per_share
        except ValueError:
            return None

    low_value, high_value = per_share(low), per_share(high)
    if low_value is None or high_value is None:
        return None, "the model does not solve across the search range"
    if not (low_value <= market_price <= high_value):
        return None, (
            f"the price of {market_price:,.2f} sits outside the value this model "
            f"produces between {low:.0%} and {high:.0%} growth "
            f"({low_value:,.2f} to {high_value:,.2f}) — no growth rate explains it, "
            "which is itself the finding"
        )

    for _ in range(max_iterations):
        mid = (low + high) / 2
        mid_value = per_share(mid)
        if mid_value is None:
            return None, "the model stopped solving mid-search"
        if abs(mid_value - market_price) < tolerance * max(market_price, 1.0):
            return mid, (
                f"at {market_price:,.2f} the market is pricing {mid:.1%} annual "
                f"revenue growth for {assumptions.forecast_years} years, on this "
                "model's margin and reinvestment assumptions"
            )
        if mid_value < market_price:
            low = mid
        else:
            high = mid

    return None, "did not converge"


def sensitivity(
    ticker: str,
    base_revenue: float,
    assumptions: Assumptions,
    net_debt: float,
    shares: float,
    market_price: float | None,
    wacc_steps: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
    growth_steps: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
) -> dict[str, Any]:
    """Value per share across a WACC × terminal-growth grid.

    Always produced, never optional. Move the discount rate 100bp and the answer
    moves 15–25%; a single point estimate implies a precision the method does not
    have, and the grid is the honest way to say so.

    The rate is perturbed by overriding the risk-free leg, which shifts the whole
    build-up — moving WACC directly would leave the cost of equity and the stated
    build-up disagreeing with the number actually used.
    """
    grid: list[list[float | None]] = []
    for wacc_delta in wacc_steps:
        row: list[float | None] = []
        for growth_delta in growth_steps:
            shifted = Assumptions(**{
                **assumptions.__dict__,
                "risk_free": Input(
                    assumptions.risk_free.value + wacc_delta,
                    assumptions.risk_free.provenance,
                    f"{assumptions.risk_free.note} (shifted {wacc_delta:+.2%})",
                ),
                "terminal_growth": Input(
                    assumptions.terminal_growth.value + growth_delta,
                    assumptions.terminal_growth.provenance,
                    f"{assumptions.terminal_growth.note} (shifted {growth_delta:+.2%})",
                ),
            })
            try:
                row.append(
                    value(ticker, base_revenue, shifted, net_debt, shares,
                          market_price=market_price).value_per_share
                )
            except ValueError:
                # WACC crossed terminal growth. A blank cell is the correct
                # answer; a number there would be nonsense.
                row.append(None)
        grid.append(row)

    return {
        "wacc_steps": list(wacc_steps),
        "growth_steps": list(growth_steps),
        "values": grid,
    }


# --------------------------------------------------------------------------- #


def to_json(valuation: Valuation, implied: tuple[float | None, str],
            grid: dict[str, Any]) -> dict[str, Any]:
    assumptions = valuation.assumptions
    return {
        "ticker": valuation.ticker,
        "wacc": valuation.wacc,
        "cost_of_equity": assumptions.cost_of_equity() if assumptions else None,
        "terminal_growth": valuation.terminal_growth,
        "forecast_years": assumptions.forecast_years if assumptions else None,
        "mid_year": assumptions.mid_year if assumptions else None,
        "rows": [
            {
                "year": row.year, "label": row.label, "growth": row.growth,
                "revenue": row.revenue,
                "ebit": row.ebit, "nopat": row.nopat, "da": row.da,
                "capex": row.capex, "delta_nwc": row.delta_nwc, "fcf": row.fcf,
                "discount_factor": row.discount_factor,
                "present_value": row.present_value,
            }
            for row in valuation.rows
        ],
        "terminal_value": valuation.terminal_value,
        "pv_terminal": valuation.pv_terminal,
        "pv_explicit": valuation.pv_explicit,
        "terminal_share": valuation.terminal_share,
        "enterprise_value": valuation.enterprise_value,
        "net_debt": valuation.net_debt,
        "equity_value": valuation.equity_value,
        "shares": valuation.shares,
        "value_per_share": valuation.value_per_share,
        "market_price": valuation.market_price,
        "upside": valuation.upside,
        # The reverse DCF first, because it is the only output that makes no
        # claim about fair value.
        "implied_growth": implied[0],
        "implied_note": implied[1],
        "sensitivity": grid,
        # Every input, and whether it was measured or invented.
        "assumptions": (
            {
                name: {
                    "value": item.value,
                    "provenance": item.provenance,
                    "note": item.note,
                }
                for name, item in vars(assumptions).items()
                if isinstance(item, Input)
            }
            if assumptions
            else {}
        ),
        "warnings": valuation.warnings,
    }


def to_block(valuation: Valuation, implied: tuple[float | None, str]) -> str:
    """The valuation as prose for a lens prompt.

    Deliberately leads with the reverse DCF. A lens told "fair value is $X" will
    anchor on it; a lens told "the price requires 22% growth for a decade" has
    been handed a testable claim about consensus, which is what the lenses exist
    to attack.
    """
    lines = [
        f"REVERSE DCF — {valuation.ticker}.",
        f"  {implied[1]}",
        "",
        f"Forward DCF at {valuation.wacc:.2%} WACC and {valuation.terminal_growth:.2%} "
        f"terminal growth: {valuation.value_per_share:,.2f} per share",
    ]
    if valuation.market_price:
        lines.append(
            f"  against a market price of {valuation.market_price:,.2f} "
            f"({valuation.upside:+.1%})"
        )
    lines.append(
        f"  {valuation.terminal_share:.0%} of enterprise value is the terminal "
        "calculation"
    )
    if valuation.warnings:
        lines += ["", "Cautions:"] + [f"  {w}" for w in valuation.warnings]
    lines += [
        "",
        "This does not forecast a quarter and is not evidence about one. It is "
        "here because the reverse figure states what the current price assumes "
        "over a decade, which is a claim about consensus that can be argued with.",
    ]
    return "\n".join(lines)


def finite(value_: float | None) -> bool:
    return value_ is not None and math.isfinite(value_)
