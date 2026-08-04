"""The Forensics lens — reads as an auditor, not a forecaster.

Accruals versus cash conversion, DSO and inventory trends, and the one thing
that matters most here: **changes in the non-GAAP exclusion mix**.

Consensus is struck on the company's own non-GAAP definition. When a company
starts excluding a new category, or an "unusual" item recurs for the fourth
consecutive quarter, the bar has quietly moved without the business moving. That
changes what the reported number *means*, which is a different and larger effect
than being a few cents off on revenue.

This is the lens most likely to disagree with the other five, which is precisely
why it is in the ensemble. It is also the one most likely to correctly find
nothing — and the prompt tells it to say so with low confidence rather than
manufacture a finding, so the judge gives it little weight instead of reading
silence as agreement.
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
        lens=LensName.FORENSICS,
        prompt_id="lens_forensics",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "quality_block": ctx.quality
            or "(no cash flow or balance sheet trend available — say so rather "
               "than inferring earnings quality from the income statement alone)",
            "exclusions_block": ctx.exclusions
            or "(no non-GAAP reconciliation history available)",
        },
    )
