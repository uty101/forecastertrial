"""Layer D — the three-statement model, built before anyone reasons about it.

Until now the model existed and nothing called it. `inputs_for()` and
`statements.build()` were exercised only by their own tests, so the pipeline
handed the lenses a bag of claims and asked them to reason about a company from
loose numbers. This stage is what turns those claims into a model.

**Why it sits before the lenses and not after.**

The obvious objection is that a three-statement model needs a revenue forecast,
and the forecast is what the lenses produce — so surely the model belongs after
the judge. That is true of the *projection*, and false of everything else. What
this stage builds is the part that does not depend on anyone's view:

- the last N quarters as three linked, balance-checked statements, from actuals
- the ratio base a projection rolls forward from — margins, opex intensity,
  effective tax rate, working-capital ratios — each a median, each with the
  quarters it was taken over
- the opening balance sheet the next quarter starts from

All of it is arithmetic on filings. None of it needs a forecast. And a lens that
can see the company's actual margin trajectory and working-capital rhythm is
reasoning about a company; one handed forty disconnected claims is reasoning
about a spreadsheet.

**The backtest is the point, though.**

Anyone can build a model. The question a judge should ask is whether it is any
good, and this stage answers it without a single model call: take a quarter we
have actuals for, feed the model that quarter's REAL revenue, and compare the
EPS it produces against the EPS the company reported. Revenue is the only input
that would have been a forecast; everything else comes from prior quarters. So
the error that comes back is the model's own structural error — the part that is
not the lenses' fault and never will be.

If the model cannot reproduce a quarter whose revenue it was handed, it cannot
project one. That number belongs on screen next to the forecast, and it is a
measurement rather than an assertion, which is more than λ can currently say.

Deterministic throughout. No model calls, no prompts, nothing to hallucinate.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

import structlog

from forecaster.data.history import History
from forecaster.data.prices import PriceBar, vwap
from forecaster.model.inputs import (
    RATIO_WINDOW,
    claim_for,
    inputs_for,
    next_period,
)
from forecaster.model.statements import build as build_statements
from forecaster.model.statements import check_balance, to_statements
from forecaster.schemas import Claim

log = structlog.get_logger()

# How many past quarters to reproduce. Four covers a full seasonal cycle, which
# matters: a model that nails three quarters and misses the December one has a
# seasonality problem, and an average over fewer than four would hide it.
BACKTEST_QUARTERS = 4

# A quarter is only a fair test if the model can see enough prior quarters to
# form its ratios. Testing against a base period with two quarters behind it
# measures the thinness of the history, not the model.
MIN_PRIOR_QUARTERS = 4


def _finite(value: float | None) -> bool:
    """A real number, not None and not NaN.

    Exists because `if not x` is the wrong test in a numeric pipeline: it treats
    0.0 as absent and NaN as present, which are both backwards. A NaN reaching
    `avg_price` from one unfinished price bar is what made this necessary.
    """
    return value is not None and math.isfinite(value)


@dataclass
class QuarterCheck:
    """One past quarter, modelled from its own revenue and compared to actuals."""

    period: str
    modelled_eps: float | None
    actual_eps: float | None
    modelled_net_income: float | None
    actual_net_income: float | None
    balanced: bool
    detail: str

    @property
    def eps_error(self) -> float | None:
        """Signed relative error. Positive means the model ran hot.

        Explicitly finite-checked rather than merely truthy-checked. `bool(nan)`
        is True, so a NaN slips through `if not value` and then survives every
        arithmetic operation downstream — which is how a headline accuracy
        figure ends up reading "nan%" instead of failing.
        """
        if not _finite(self.modelled_eps) or not _finite(self.actual_eps):
            return None
        return (self.modelled_eps - self.actual_eps) / abs(self.actual_eps)


@dataclass
class ModelResult:
    """What stage D hands the lenses."""

    ticker: str
    base_period: str
    forecast_period: str
    # The base quarter rebuilt from its own actuals: the model as it stands
    # today, balance-checked, ready for a revenue view to be dropped into it.
    statements: dict[str, list[dict]] = field(default_factory=dict)
    balanced: bool = False
    balance_detail: str = ""
    # The ratio base, and the note saying what each was taken over. These are
    # the numbers a projection moves; a lens arguing margins is arguing with
    # this dict.
    ratios: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    checks: list[QuarterCheck] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def median_abs_eps_error(self) -> float | None:
        """The model's structural error: median |modelled − actual| / |actual|.

        Median rather than mean, and absolute rather than signed, because one
        quarter with a one-off charge would otherwise dominate — the same robust
        -statistics rule the rest of the system runs on.
        """
        errors = [abs(c.eps_error) for c in self.checks if c.eps_error is not None]
        return statistics.median(errors) if errors else None

    @property
    def bias(self) -> float | None:
        """Signed median. Tells you whether the model runs hot or cold, which
        `median_abs_eps_error` deliberately cannot."""
        errors = [c.eps_error for c in self.checks if c.eps_error is not None]
        return statistics.median(errors) if errors else None


def _avg_price(prices: list[PriceBar] | None, fallback: float | None = None) -> float:
    """Volume-weighted average price, for the buyback share-retirement maths.

    A filing reports what a buyback COST and never how many shares it retired,
    so this cannot come from SEC data. Without it `inputs_for` refuses to build,
    which is correct: a placeholder silently retires `buyback_spend` shares and
    produces an EPS that looks reasonable and is badly wrong.
    """
    if prices:
        weighted = vwap(prices)
        if _finite(weighted) and weighted > 0:
            return weighted
    if _finite(fallback) and fallback > 0:
        return fallback
    raise ValueError(
        "no price history — avg_price cannot be inferred from filings, and a "
        "placeholder silently misstates the share count that EPS divides by"
    )


def _actual(history: History, key: str, period: str) -> float | None:
    observation = history.get(key, period)
    return observation.value if observation else None


def _backtest(
    history: History,
    price: float,
    shares_open: float | None,
    quarters: int,
) -> tuple[list[QuarterCheck], list[str]]:
    """Reproduce the last `quarters` reported quarters from their own revenue.

    Each check uses the quarter BEFORE it as the base, so every ratio and every
    opening balance is information that existed at the time. Only revenue is
    handed forward — which is exactly the input a forecast would have to supply,
    and exactly why what comes back is the model's error rather than a lens's.
    """
    periods = history.periods()
    checks: list[QuarterCheck] = []
    skipped: list[str] = []

    # Newest first, but never so far back that the base has no ratios to form.
    candidates = list(reversed(periods))[:quarters]
    for target in candidates:
        index = periods.index(target)
        if index < MIN_PRIOR_QUARTERS:
            skipped.append(
                f"{target}: only {index} prior quarters, below the "
                f"{MIN_PRIOR_QUARTERS} needed to form ratios"
            )
            continue

        base = periods[index - 1]
        revenue = _actual(history, "revenue", target)
        if not revenue:
            skipped.append(f"{target}: no reported revenue to drive the model with")
            continue

        try:
            inputs = inputs_for(
                history, revenue=revenue, avg_price=price,
                base_period=base, shares_open=shares_open,
            )
            model = build_statements(inputs, name=f"{history.ticker} {target}")
            values = model.evaluate()
            balanced, detail = check_balance(model)
        except (ValueError, KeyError) as exc:
            # A quarter the model cannot build is a finding, not a crash. It
            # usually means a line item the filer stopped tagging.
            skipped.append(f"{target}: {type(exc).__name__}: {exc}")
            continue

        modelled_eps = values.get("eps")
        if not _finite(modelled_eps):
            # A check that cannot produce a number is not a data point. Counting
            # it would put a NaN into the median and report the model's accuracy
            # as "nan%", which reads as a rendering glitch rather than as the
            # broken input it is.
            skipped.append(
                f"{target}: model produced a non-finite EPS — an input is NaN"
            )
            continue

        checks.append(
            QuarterCheck(
                period=target,
                modelled_eps=modelled_eps,
                actual_eps=_actual(history, "eps_diluted", target),
                modelled_net_income=values.get("net_income"),
                actual_net_income=_actual(history, "net_income", target),
                balanced=balanced,
                detail=detail,
            )
        )
    return checks, skipped


def build(
    history: History,
    prices: list[PriceBar] | None = None,
    shares_open: float | None = None,
    avg_price: float | None = None,
    window: int = RATIO_WINDOW,
    backtest_quarters: int = BACKTEST_QUARTERS,
) -> ModelResult:
    """Build the model and measure it. Deterministic — no model calls.

    `shares_open` is an override for the multi-class issuers whose EPS and share
    count are tagged against a class dimension that `companyfacts` excludes.
    Visa has neither; without the override `inputs_for` raises rather than
    quietly dividing by one share.
    """
    base = history.latest_period()
    if base is None:
        raise ValueError(f"{history.ticker}: no history to build a model from")

    price = _avg_price(prices, avg_price)

    # The base quarter, rebuilt from its own actuals. Using the reported top
    # line rather than a forecast keeps this stage free of anyone's view — the
    # revenue slot is where the judge's number lands later.
    base_revenue = _actual(history, "revenue", base)
    if not base_revenue:
        raise ValueError(f"{history.ticker}: no revenue reported for {base}")

    inputs = inputs_for(
        history, revenue=base_revenue, avg_price=price,
        base_period=base, window=window, shares_open=shares_open,
    )

    # `inputs_for` treats revenue as a forecast — the one number that cannot come
    # from history — and so leaves it a note rather than a claim. Here it IS
    # history: the base quarter's reported top line. Attaching its claim is the
    # difference between a sheet where every figure reads "derived" and one where
    # the line everything else is computed from traces to a filing.
    observation = history.get("revenue", base)
    if observation is not None:
        inputs.claims = dict(inputs.claims or {})
        inputs.claims["revenue"] = claim_for(history, observation)
        (inputs.notes or {}).pop("revenue", None)

    model = build_statements(inputs, name=f"{history.ticker} {base}")
    balanced, balance_detail = check_balance(model)

    ratios = {
        "gross_margin": inputs.gross_margin,
        "tax_rate": inputs.tax_rate,
        "opex": inputs.opex,
        "da": inputs.da,
        "capex": inputs.capex,
    }
    if base_revenue:
        ratios["opex_pct_revenue"] = inputs.opex / base_revenue
        ratios["da_pct_revenue"] = inputs.da / base_revenue
        ratios["capex_pct_revenue"] = inputs.capex / base_revenue

    checks, skipped = _backtest(history, price, shares_open, backtest_quarters)

    result = ModelResult(
        ticker=history.ticker,
        base_period=base,
        forecast_period=next_period(base),
        statements=to_statements(model),
        balanced=balanced,
        balance_detail=balance_detail,
        ratios=ratios,
        notes=dict(inputs.notes or {}),
        claims=list((inputs.claims or {}).values()),
        checks=checks,
        skipped=skipped,
    )

    log.info(
        "model_built",
        ticker=history.ticker,
        base=base,
        balanced=balanced,
        quarters_checked=len(checks),
        median_abs_eps_error=result.median_abs_eps_error,
        skipped=len(skipped),
    )
    return result


def to_block(result: ModelResult) -> str:
    """The model as prose for a lens prompt.

    A lens is given the ratio base and the model's own measured error, not the
    cell graph. The error matters as much as the ratios: a lens arguing for a
    30bp margin change should know the model it feeds cannot resolve 30bp.
    """
    lines = [
        f"THREE-STATEMENT MODEL — {result.ticker}, base quarter {result.base_period}, "
        f"projecting {result.forecast_period}.",
        result.balance_detail,
        "",
        "Ratio base (each a median over prior quarters; a projection moves these):",
    ]
    for key in ("gross_margin", "opex_pct_revenue", "da_pct_revenue",
                "capex_pct_revenue", "tax_rate"):
        if key in result.ratios:
            lines.append(f"  {key:20} {result.ratios[key]:.4f}")

    if result.checks:
        lines += ["", "Model reproduced against reported quarters (fed each "
                  "quarter's ACTUAL revenue, so this is the model's own error, "
                  "not a forecasting error):"]
        for check in result.checks:
            if check.eps_error is None:
                lines.append(f"  {check.period:8} no comparable EPS")
                continue
            lines.append(
                f"  {check.period:8} modelled {check.modelled_eps:.3f} vs reported "
                f"{check.actual_eps:.3f}  ({check.eps_error:+.1%})"
            )
        median = result.median_abs_eps_error
        if median is not None:
            lines.append(
                f"  median absolute error {median:.1%}, bias {result.bias:+.1%}. "
                "Do not argue for a change smaller than this — the model cannot "
                "resolve it."
            )
    if result.skipped:
        lines += ["", "Not reproduced:"] + [f"  {s}" for s in result.skipped]
    return "\n".join(lines)


def to_json(result: ModelResult) -> dict[str, Any]:
    """For `out/model.json`, which the UI reads. No API between the two."""
    return {
        "ticker": result.ticker,
        "base_period": result.base_period,
        "forecast_period": result.forecast_period,
        "balanced": result.balanced,
        "balance_detail": result.balance_detail,
        "statements": result.statements,
        "ratios": result.ratios,
        "notes": result.notes,
        "checks": [
            {
                "period": c.period,
                "modelled_eps": c.modelled_eps,
                "actual_eps": c.actual_eps,
                "modelled_net_income": c.modelled_net_income,
                "actual_net_income": c.actual_net_income,
                "eps_error": c.eps_error,
                "balanced": c.balanced,
            }
            for c in result.checks
        ],
        "median_abs_eps_error": result.median_abs_eps_error,
        "bias": result.bias,
        # As prominent as what worked.
        "skipped": result.skipped,
    }
