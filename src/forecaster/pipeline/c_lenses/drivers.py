"""The Drivers lens — revenue built from the bottom up.

Units × ASP, subscribers × ARPU, comps × stores, backlog conversion. The point
is to forecast the *drivers* and multiply, rather than extrapolating the revenue
line and calling it a model. Extrapolation cannot tell you why a quarter turns,
and a quarter that turns is the only kind worth forecasting.

A small YAML of driver definitions for the likely universe means this lens
starts warm on a company we prepared for, and derives the decomposition from the
10-K if we did not. Slower, still works — nothing here is ticker-specific.
"""

from __future__ import annotations

from forecaster.llm.client import LLMClient
from forecaster.pipeline.b_structure import EvidenceStore
from forecaster.pipeline.c_lenses.base import LensContext, common_vars, run_lens
from forecaster.schemas import LensName, LensOutput

NO_DRIVERS = (
    "(no prepared driver definitions for this company — derive the "
    "decomposition from the segment and operating-metric disclosure in the "
    "evidence, and say which you used)"
)


def run(
    client: LLMClient, store: EvidenceStore, ctx: LensContext, run_index: int = 0
) -> LensOutput:
    return run_lens(
        client=client,
        lens=LensName.DRIVERS,
        prompt_id="lens_drivers",
        store=store,
        basis=ctx.basis,
        run_index=run_index,
        variables={
            **common_vars(ctx.ticker, ctx.period, ctx.basis),
            "prior_year_block": ctx.prior_year or "(prior-year quarter not available)",
            "driver_block": ctx.drivers or NO_DRIVERS,
        },
    )
