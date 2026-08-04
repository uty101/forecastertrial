"""The Guidance lens — the highest-signal input in the system.

Prior-quarter guidance is the strongest single predictor of the coming print,
and it is free: it lives in the 8-K EX-99.1 the company filed three months ago.
Everyone reads it.

What almost nobody builds is the second half — where this company historically
lands *inside its own guided range*. Some companies hit the midpoint like
clockwork. Some clear the top end every quarter. That is a computable, per-
company distribution, and it is the difference between "management guided
$2.10-2.20" and "management guided $2.10-2.20 and this company has landed above
the top end in six of its last eight quarters."

With n≈8 the raw landing statistic is mostly sampling noise, so the shrunk
figure is the one handed to the model and the one the prompt tells it to weight.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import (
    EvidenceStore,
    guidance_block,
    landing_block,
)
from forecaster.pipeline.e_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.GUIDANCE,
        prompt_id="lens_guidance",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "guidance_block": guidance_block(store.guidance),
            "landing_block": landing_block(store.landing),
            "n_quarters": store.landing.n_quarters if store.landing else 0,
        },
    )
