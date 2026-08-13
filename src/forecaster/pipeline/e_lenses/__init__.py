"""Layer E — seven lenses, blind to each other, fanned out in parallel.

They share one cached prefix (the evidence corpus) and nothing else. The fan-out
is threaded rather than async because the SDK call is blocking and the pool is
six wide; asyncio would buy nothing and cost a lifecycle bug at 18:40.

**Results are sorted before returning.** The threads finish in whatever order
the API returns them, and `make verify` diffs the output byte for byte — an
unsorted result list would fail that diff for a reason that has nothing to do
with the pipeline.

A lens that raises is dropped with its reason and surfaced. It is never retried
into the ensemble and never silently omitted: the judge is told what is missing,
because an ensemble that quietly shrinks is an ensemble whose weights no longer
mean anything.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import structlog

from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.pipeline.e_lenses import (
    demand,
    drivers,
    forensics,
    guidance,
    macro,
    margins,
    market,
    peer_read,
)
from forecaster.pipeline.e_lenses.base import LensContext, LensFailure
from forecaster.schemas import EventType, LensName, LensOutput

log = structlog.get_logger()

# The Mechanical lens is not in this list: it has no model in it, runs in
# microseconds, and takes a different input shape. It is called directly by the
# pipeline and joins the ensemble alongside these six.
LLM_LENSES = [
    (LensName.GUIDANCE, guidance.run),
    (LensName.DRIVERS, drivers.run),
    (LensName.MARGINS, margins.run),
    (LensName.FORENSICS, forensics.run),
    (LensName.PEER_READ, peer_read.run),
    (LensName.MACRO, macro.run),
    # Two more angles of attack, both on revenue but from opposite directions:
    # Market asks whether the growth is the sector's or this company's, Demand
    # asks what the people who actually write the cheques have said.
    (LensName.MARKET, market.run),
    (LensName.DEMAND, demand.run),
]


@dataclass
class LensResults:
    kept: list[LensOutput] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "ran": len(self.kept) + len(self.dropped),
            "kept": [lens.lens.value for lens in self.kept],
            "dropped": self.dropped,
        }


def run_all(
    client: LLMClient,
    store: EvidenceStore,
    ctx: LensContext,
    events: EventLog | None = None,
    run_index: int = 0,
    only: list[LensName] | None = None,
) -> LensResults:
    """Fan the six LLM lenses out against the shared corpus.

    `only` restricts the set, which is how leave-one-out ablation works: the
    marginal contribution of a lens is measured by removing it and re-scoring,
    never by asking whether it looks useful.
    """
    selected = [(name, fn) for name, fn in LLM_LENSES if only is None or name in only]
    results = LensResults()
    outputs: dict[LensName, LensOutput] = {}

    def _one(item):
        name, fn = item
        if events:
            events.emit(EventType.NODE_START, f"E_{name.value}")
        try:
            return name, fn(client, store, ctx, run_index), None
        except LensFailure as exc:
            return name, None, str(exc)
        except Exception as exc:  # noqa: BLE001 — one lens must not end the run
            return name, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max(len(selected), 1)) as pool:
        for name, output, error in pool.map(_one, selected):
            if error:
                results.dropped[name.value] = error
                log.warning("lens_dropped", lens=name.value, why=error)
                if events:
                    events.emit(EventType.NODE_FAILED, f"E_{name.value}", error=error)
            else:
                outputs[name] = output
                if events:
                    events.emit(
                        EventType.NODE_DONE,
                        f"E_{name.value}",
                        eps=output.eps,
                        confidence=output.confidence,
                        latency_ms=output.latency_ms,
                    )

    # Deterministic order, independent of thread completion order.
    results.kept = [outputs[name] for name, _ in LLM_LENSES if name in outputs]
    log.info("lenses_complete", **results.summary())
    return results
