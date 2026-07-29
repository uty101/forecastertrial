"""The Peer Read lens — who already reported, and what did they say?

This lens has a structural edge rather than an analytical one: analyst estimates
are sticky. A supplier or a same-quarter-end peer reports mid-quarter and says
something that plainly implicates this company, and consensus for this company
does not move for weeks. That gap is knowable *now*, from public filings, with
no forecasting skill required at all.

The discipline that makes it work is insisting on a transmission mechanism.
"Semis were strong" is not a read. "Their datacentre segment grew 34% and this
company supplies roughly 40% of that segment's content" is. The prompt refuses
the first kind.

Point-in-time matters more here than anywhere else in the system: this lens is
explicitly reading other companies' recent disclosures, which is exactly the
place where a stray post-`as_of` filing would leak future information and make
the backtest look brilliant for no reason.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.b_structure import EvidenceStore
from forecaster.pipeline.c_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput

NOBODY_YET = (
    "(no peer, supplier or customer with a relevant disclosure has reported "
    "before the as-of date. This is the correct and common situation early in a "
    "reporting cycle — return null rather than reaching for a weaker read.)"
)


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.PEER_READ,
        prompt_id="lens_peer_read",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "as_of": ctx.as_of.isoformat(),
            "peer_block": ctx.peers or NOBODY_YET,
        },
    )
