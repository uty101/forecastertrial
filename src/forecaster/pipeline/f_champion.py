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
        return lens.model_copy(
            update={
                "thesis": response.thesis,
                "counterargument": (
                    f"{response.counterargument}\n\n"
                    f"Most material weakness: {response.material_weakness}"
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
