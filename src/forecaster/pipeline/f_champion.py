"""Layer D — champion development. Argue each case, then argue against it.

This is the step that took the reference system from failing outright to ~92%,
and it is the one most teams skip. The failure mode it fixes is specific:
comparing raw findings and taking the plurality rewards the finding that is
easiest to reach from the evidence, not the one that is most material. A weak
signal that five lenses can all see beats a strong signal only one lens found.

So nothing is compared until every case has been developed into its strongest
honest form *and then attacked in good faith*. What reaches the judge is not
seven opinions; it is seven cases and what survived of each.

Two rules the prompt enforces and this module relies on:

- **The champion never changes the number.** It assesses the case; restating the
  estimate here would make the judge's inputs untraceable to the lens that
  produced them.
- **`surviving_confidence` replaces the lens's own confidence** for the judge's
  purposes. A lens grading its own work is uncalibrated in a predictable
  direction; a pass that was specifically instructed to attack it is less so.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import structlog
from pydantic import BaseModel, Field

from forecaster.events import EventLog
from forecaster.llm.client import LLMClient, LLMError
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.schemas import EventType, LensOutput

log = structlog.get_logger()


class ChampionResponse(BaseModel):
    thesis: str = Field(
        description="The strongest honest version of this case: which evidence, "
        "what mechanism, what number. Not the version its author wrote — the "
        "version its author would have written with more time."
    )
    counterargument: str = Field(
        description="The case against, argued hard and in good faith. Looking "
        "for the reason this is wrong, not for a balanced view."
    )
    surviving_confidence: Annotated[float, Field(ge=0, le=1)] = Field(
        description="Honest read of the case AFTER the attack. Often much lower "
        "than the lens claimed; occasionally higher."
    )
    material_weakness: str = Field(
        description="The single most material weakness, in one sentence."
    )

    # ---- Phase 6: the three things that separate a view from a number ----
    #
    # A case that survives its own counterargument is still not a variant view.
    # These are what make it one, and each is deliberately hard to answer with
    # nothing — which is the point.
    variant_perception: str = Field(
        default="",
        description="What this case believes that consensus does not. State the "
        "belief itself, not the conclusion — 'datacentre units grow faster than "
        "the Street models', not 'we are above consensus'.",
    )
    why_it_persists: str = Field(
        default="",
        description="WHY the market has not already priced this. The harder half, "
        "and a variant view without an answer here is not a variant view — it is "
        "an assertion that everyone else is simply wrong. Acceptable answers name "
        "a mechanism: a disclosure nobody aggregates, a horizon nobody is paid "
        "for, a constraint that only shows up in a supplier's filing. If there is "
        "no such mechanism, say so plainly.",
    )
    premortem: str = Field(
        default="",
        description="It is three months on and this case was wrong. What happened? "
        "Usually an unevidenced driver assumption or a comparability break. Name "
        "the specific assumption that failed, not 'the market moved against us'.",
    )
    kill_criteria: list[str] = Field(
        default_factory=list,
        description="Observable events BEFORE the print that would say this case "
        "is wrong. Each must name a thing that can be checked and where it would "
        "be seen — 'AMD guides datacentre revenue down' is a criterion; 'the "
        "thesis breaks' is not. Two or three, no more.",
    )


def develop(
    client: LLMClient,
    lenses: list[LensOutput],
    store: EvidenceStore,
    ticker: str,
    period: str,
    events: EventLog | None = None,
    run_index: int = 0,
) -> list[LensOutput]:
    """Develop and attack every surviving case, in parallel.

    Returns new LensOutput objects with `thesis` and `counterargument` filled
    and `confidence` replaced by the surviving confidence. A champion call that
    fails leaves its lens untouched rather than dropping it — the lens's own
    analysis is still valid, it just has not been stress-tested, and losing a
    good case to a flaky second call would be the worse error.
    """

    def _one(lens: LensOutput):
        if events:
            events.emit(EventType.NODE_START, f"F_{lens.lens.value}")
        try:
            response, _ = client.call(
                "champion",
                schema=ChampionResponse,
                variables={
                    "ticker": ticker,
                    "period": period,
                    "lens_name": lens.lens.value,
                    "lens_eps": "not stated" if lens.eps is None else f"{lens.eps:.4f}",
                    "lens_confidence": f"{lens.confidence:.2f}",
                    "lens_reasoning": lens.reasoning,
                    "cited_claims_block": store.cited_block(lens.claim_ids),
                },
                run_index=run_index,
            )
        except LLMError as exc:
            log.warning("champion_failed", lens=lens.lens.value, error=str(exc))
            if events:
                events.emit(EventType.NODE_FAILED, f"F_{lens.lens.value}",
                            error=str(exc))
            return lens

        if events:
            events.emit(
                EventType.NODE_DONE,
                f"F_{lens.lens.value}",
                surviving_confidence=response.surviving_confidence,
            )
        log.info(
            "champion_done",
            lens=lens.lens.value,
            stated=round(lens.confidence, 2),
            surviving=round(response.surviving_confidence, 2),
        )
        # The variant view and the pre-mortem ride in the counterargument text
        # rather than in new schema fields, so the judge and every UI surface
        # that already renders it pick them up without a migration.
        #
        # `why_it_persists` is placed immediately after the variant perception on
        # purpose: the two are one claim, and a variant view whose persistence
        # paragraph is empty should be read as an assertion that everyone else is
        # simply wrong — which is the state the judge most needs to see.
        extra = []
        if response.variant_perception:
            extra.append(f"Variant perception: {response.variant_perception}")
        if response.why_it_persists:
            extra.append(f"Why it persists: {response.why_it_persists}")
        elif response.variant_perception:
            extra.append(
                "Why it persists: NO MECHANISM OFFERED — this is an assertion "
                "that the market is simply wrong, and should be weighed as one."
            )
        if response.premortem:
            extra.append(f"Pre-mortem: {response.premortem}")
        if response.kill_criteria:
            extra.append(
                "Kill criteria: " + "; ".join(response.kill_criteria[:3])
            )

        return lens.model_copy(
            update={
                "thesis": response.thesis,
                "counterargument": "\n\n".join(
                    [
                        response.counterargument,
                        f"Most material weakness: {response.material_weakness}",
                        *extra,
                    ]
                ),
                "confidence": response.surviving_confidence,
            }
        )

    if not lenses:
        return []

    with ThreadPoolExecutor(max_workers=len(lenses)) as pool:
        developed = list(pool.map(_one, lenses))

    # Input order is already deterministic (layer C sorts); preserve it.
    return developed


def cases_block(lenses: list[LensOutput]) -> str:
    """Render the developed cases for the judge.

    Each case leads with its evidence and mechanism, not with its lens name.
    The judge weighs by materiality, and a lens label is an invitation to weigh
    by reputation instead.
    """
    if not lenses:
        return "(no cases survived — every lens was dropped)"

    parts = []
    for lens in lenses:
        eps = "no estimate" if lens.eps is None else f"{lens.eps:.4f}"
        block = [
            f"### {lens.lens.value}  —  EPS {eps}  "
            f"(confidence after attack: {lens.confidence:.2f})",
            "",
            f"Analysis: {lens.reasoning}",
        ]
        if lens.thesis:
            block += ["", f"Thesis: {lens.thesis}"]
        if lens.counterargument:
            block += ["", f"Counterargument: {lens.counterargument}"]
        else:
            block += [
                "",
                "Counterargument: NOT DEVELOPED — this case was never attacked, "
                "so its confidence is self-reported. Discount it accordingly.",
            ]
        block += ["", f"Evidence cited: {', '.join(lens.claim_ids)}", ""]
        parts.append("\n".join(block))
    return "\n".join(parts)
