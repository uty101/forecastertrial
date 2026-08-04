"""Layer E — the judge. One expensive call, the highest-leverage in the system.

Two design rules, both of which are the point rather than a detail:

**Weighs by materiality, never by vote count.** This is the documented failure
mode of systems like this one: a boss agent that picks the most *frequent*
finding rather than the most *material* one fails. There is deliberately no
averaging, no plurality and no majority logic anywhere in this module — search
for it and you will not find it, because the aggregation happens inside one
model call that has been told what earns weight. Lens agreement is very weak
evidence in any case: they read overlapping documents, so their errors are
correlated and five being wrong together is about as likely as one.

**Outputs a distribution, not a point.** A distribution is a strict superset —
median for MAE, mean for MSE, quantiles for CRPS, direction for win-rate. Since
the scoring rule is not known until the morning of the event, building this once
turns the metric from a design input into a config value.

The judge is also told which lenses are MISSING and why. Absent information is
not agreement, and a system that treats it as agreement is most confident
exactly where it has least right to be.
"""

from __future__ import annotations

import statistics

import structlog
from pydantic import BaseModel, Field, model_validator

from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import consensus_block, dropped_block
from forecaster.pipeline.f_champion import cases_block
from forecaster.schemas import Basis, Consensus, Distribution, EventType, LensOutput

log = structlog.get_logger()

REQUIRED_QUANTILES = ("0.1", "0.25", "0.5", "0.75", "0.9")


class JudgeResponse(BaseModel):
    median_eps: float = Field(description="Median EPS the evidence supports.")
    mean_eps: float = Field(
        description="Mean EPS. Differs from the median when the evidence implies "
        "a skewed outcome — say so in the rationale when it does."
    )
    quantiles: dict[str, float] = Field(
        description="EPS at the 0.1, 0.25, 0.5, 0.75 and 0.9 quantiles. Keys are "
        "the levels as strings."
    )
    revenue: float | None = Field(
        default=None, description="Revenue, if the evidence supports one."
    )
    rationale: str = Field(
        description="Which case carried the most weight and why, and what set "
        "the width of the distribution."
    )

    @model_validator(mode="after")
    def _quantiles_are_sane(self) -> JudgeResponse:
        missing = [q for q in REQUIRED_QUANTILES if q not in self.quantiles]
        if missing:
            raise ValueError(f"judge omitted quantiles {missing}")

        ordered = [self.quantiles[q] for q in REQUIRED_QUANTILES]
        if ordered != sorted(ordered):
            # A non-monotonic CDF is not a distribution. Fail closed: this would
            # otherwise flow into calibration and produce intervals that are
            # nonsense in a way no chart would reveal.
            raise ValueError(
                f"quantiles are not monotonically increasing: "
                f"{dict(zip(REQUIRED_QUANTILES, ordered, strict=True))}"
            )
        return self


def judge(
    client: LLMClient,
    lenses: list[LensOutput],
    dropped: dict[str, str],
    consensus: Consensus | None,
    ticker: str,
    period: str,
    basis: Basis = Basis.NON_GAAP,
    events: EventLog | None = None,
    run_index: int = 0,
) -> tuple[Distribution, str]:
    """Returns (distribution, rationale).

    Falls back to a deterministic distribution over the surviving lens estimates
    if the judge call fails — a run that reaches this point has real analysis in
    it, and losing all of it to one flaky call at 15:20 would be the worse
    outcome. The fallback is logged loudly and marked in the rationale, because
    silently substituting a weaker method is how a demo lies.
    """
    if events:
        events.emit(EventType.NODE_START, "G_judge")

    if not lenses:
        raise RuntimeError(
            "every lens was dropped — there is nothing to judge. Check the "
            "reconciler output; this is a pipeline failure, not a forecast of zero."
        )

    try:
        response, usage = client.call(
            "judge",
            schema=JudgeResponse,
            variables={
                "ticker": ticker,
                "period": period,
                "basis": basis.value,
                "cases_block": cases_block(lenses),
                "dropped_block": dropped_block(dropped),
                "consensus_block": consensus_block(consensus),
            },
            run_index=run_index,
            max_tokens=12000,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("judge_failed_using_fallback", error=str(exc))
        if events:
            events.emit(EventType.NODE_FAILED, "G_judge", error=str(exc))
        return _fallback(lenses), (
            f"JUDGE CALL FAILED ({exc}). Fell back to a robust spread over the "
            f"{len(lenses)} surviving lens estimates — this is a median, not an "
            "impact-weighted judgment, and it should be treated as degraded."
        )

    distribution = Distribution(
        median=response.median_eps,
        mean=response.mean_eps,
        quantiles=dict(response.quantiles),
        stdev=_implied_stdev(response.quantiles),
        calibrated=False,  # V3 sets this after bootstrapping our own residuals
    )

    if events:
        events.emit(
            EventType.NODE_DONE,
            "G_judge",
            median=distribution.median,
            p10=response.quantiles["0.1"],
            p90=response.quantiles["0.9"],
            cost_usd=round(usage.cost_usd, 4),
        )
    log.info(
        "judge_done",
        median=distribution.median,
        width=round(response.quantiles["0.9"] - response.quantiles["0.1"], 4),
        n_cases=len(lenses),
        n_dropped=len(dropped),
    )
    return distribution, response.rationale


def _implied_stdev(quantiles: dict[str, float]) -> float:
    """Normal-equivalent sigma from the 10-90 span.

    For a normal distribution p90 - p10 = 2 * 1.2816 * sigma. This is only a
    convenience for charts and for the lambda regime check — the quantiles
    themselves are the real object, and V3 replaces this with bootstrapped
    residuals from our own backtest.
    """
    return (quantiles["0.9"] - quantiles["0.1"]) / 2.5631


def _fallback(lenses: list[LensOutput]) -> Distribution:
    """Robust spread over surviving lens estimates. Medians, not means — one
    lens with a runaway number must not set the answer."""
    values = sorted(lens.eps for lens in lenses if lens.eps is not None)
    if not values:
        raise RuntimeError("no lens produced an EPS estimate")

    median = statistics.median(values)
    spread = (max(values) - min(values)) if len(values) > 1 else abs(median) * 0.05
    return Distribution(
        median=median,
        mean=statistics.fmean(values),
        quantiles={
            "0.1": median - spread * 0.8,
            "0.25": median - spread * 0.4,
            "0.5": median,
            "0.75": median + spread * 0.4,
            "0.9": median + spread * 0.8,
        },
        stdev=spread / 2.5631 * 1.6,
        calibrated=False,
    )
