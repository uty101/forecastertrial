"""The Macro lens — sector series against what estimates appear to assume.

The justification is a specific measured finding rather than a general belief
that macro matters: a Federal Reserve paper finds the gap between a macro model
and analyst assumptions predicts roughly half the variance in current-quarter
analyst error (R² 0.48–0.51). Analysts update their macro assumptions slowly;
the data does not.

So the output is not "conditions are soft, cut the number". It is the gap
between where the relevant series actually went and where the Street's estimate
appears to assume they went, transmitted through a stated sensitivity.

One deliberate boundary: the Mechanical lens already handles FX *translation*
arithmetically, and double-counting it would be the easiest way for this
ensemble to be confidently wrong twice. This lens is told to stay off that and
address the FX regime and hedging instead.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.b_structure import EvidenceStore
from forecaster.pipeline.c_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput

NO_SERIES = (
    "(no macro series were acquired for this sector. Return null rather than "
    "reasoning from general economic conditions — an unsourced macro view is "
    "the least falsifiable thing this system could produce.)"
)


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.MACRO,
        prompt_id="lens_macro",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "as_of": ctx.as_of.isoformat(),
            "sector": ctx.sector,
            "macro_block": ctx.macro or NO_SERIES,
        },
    )
