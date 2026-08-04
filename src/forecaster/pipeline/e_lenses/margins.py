"""The Margins lens — revenue to EPS.

Gross margin mix, opex trajectory, tax rate, below-the-line items. Takes the top
line as given and argues about what falls through it.

**On blindness.** This lens needs a working revenue figure, and the obvious
source is the Drivers lens. That would be a mistake: Margins would become a
restatement of Drivers rather than an independent view, the two would agree by
construction, and the judge would read that agreement as corroboration. So the
working top line comes from prior-year revenue and a naive seasonal growth rate,
and the prompt says explicitly that it is a working assumption and not a number
to defend.

The mix point is the one that earns this lens its tokens. A shift between
segments with different margins moves the blended number without either
segment's margin changing — a margin model that ignores mix is wrong in the same
direction every quarter, which looks like bias and is actually arithmetic.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.pipeline.e_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.MARGINS,
        prompt_id="lens_margins",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "revenue_block": ctx.working_revenue
            or "(no working revenue assumption — derive one from the evidence "
               "and state it)",
            "margin_history_block": ctx.margin_history
            or "(no margin history available)",
        },
    )
