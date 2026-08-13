"""The Market lens — is this growth the market's, or is it share?

    company growth  =  market growth  +  share change

The two halves are completely different forecasts. A company growing 60% in a
market growing 55% is riding a wave that can stop; one growing 60% in a market
growing 8% is taking share from named competitors, which is durable until they
respond. Consensus forecasts company revenue directly and the split lives in an
analyst's head if anywhere, so this is a place the Street is structurally thin.

The industry block is built bottom-up from the filed revenue of every SIC peer —
not a purchased market-size number, which is a consultancy's estimate of a
boundary they drew, published on a lag and unauditable.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.pipeline.e_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput

NO_INDUSTRY = (
    "(no industry picture — fewer than three peers filed under this company's "
    "SIC code with reported revenue. Say you cannot separate market growth from "
    "share rather than guessing at the split.)"
)


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.MARKET,
        prompt_id="lens_market",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "industry_block": ctx.industry or NO_INDUSTRY,
        },
    )
