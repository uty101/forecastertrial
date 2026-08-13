"""The Demand lens — the value chain, one link upstream and one down.

A customer's capital budget IS this company's revenue, and it is disclosed on a
different reporting calendar. When the hyperscalers guide capex, they have told
you most of NVIDIA's next two quarters before NVIDIA says anything — and the
same logic runs the other way through suppliers, whose order books lead the
company's shipments.

**Why this is not the Peer read lens.** Peers tell you about the same demand
seen by a competitor. Customers and suppliers tell you about the demand ITSELF,
one step removed from the company's own reporting, and the transmission
mechanism is a contract rather than a correlation. A peer's miss might be
share loss; a customer's capex cut cannot be.

The customer names come from the filing's own concentration disclosure where the
company gives one, so this works on a ticker nobody prepared for.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.pipeline.e_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput

NO_CHAIN = (
    "(no named customers or suppliers in the evidence. Identify the value chain "
    "from the segment and concentration disclosure if you can, and say so if you "
    "cannot — an invented customer is worse than an absent one.)"
)


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.DEMAND,
        prompt_id="lens_demand",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "chain_block": ctx.value_chain or NO_CHAIN,
            "peer_block": ctx.peers or "(no peer prints this cycle)",
        },
    )
