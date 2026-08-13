"""Shared plumbing for the six LLM lenses.

The lenses differ only in what question they ask and what small block of context
they get. Everything else — schema, error handling, citation resolution, run
bookkeeping — is here, so that a new lens is a prompt plus about thirty lines.

THE INVARIANT THIS FILE EXISTS TO ENFORCE: **lenses are blind to each other.**
`run_lens` takes the shared corpus and a dict of variables, and there is no
parameter through which one lens's output could reach another. That is not an
oversight to be fixed later — diversity is the whole point of an ensemble, and
lenses that see each other's work converge. Converging is how you accidentally
rebuild consensus, and consensus scores zero.

A lens that errors is dropped with a reason, never silently omitted. The judge
is told which lenses are missing, because an ensemble that quietly shrinks is an
ensemble whose weights no longer mean anything.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Annotated

import structlog
from pydantic import BaseModel, Field

from forecaster.llm.client import LLMClient, LLMError
from forecaster.pipeline.c_structure import EvidenceStore
from forecaster.schemas import Basis, LensName, LensOutput

log = structlog.get_logger()

# See run_lens. 8000 truncated Peer read; 14000 truncated it again and also cut
# Drivers off mid-string, which surfaces as "Invalid JSON: EOF while parsing"
# rather than as a truncation — the same bug wearing a different error. Output is
# billed on use, so headroom costs nothing until it is taken.
LENS_MAX_TOKENS = 20000


class LensResponse(BaseModel):
    """What every LLM lens must return. Forced as the output schema, so a lens
    that would have rambled instead fails validation and is dropped.

    `eps` is nullable on purpose. "The evidence does not support a number here"
    is a legitimate and useful answer — much more useful than an interpolation —
    and a lens that abstains is dropped from the ensemble rather than dragging
    it toward a made-up figure.
    """

    eps: float | None = Field(
        default=None,
        description="Point EPS estimate on the requested basis, or null if the "
        "evidence does not support one.",
    )
    revenue: float | None = Field(
        default=None, description="Revenue in the same units as the evidence, or null."
    )
    reasoning: str = Field(
        description="The chain: which evidence, what mechanism, what number. "
        "A few sentences. No preamble."
    )
    claim_ids: list[str] = Field(
        min_length=1,
        description="Ids of every claim relied on, exactly as they appear in the "
        "evidence block — at least one, always. If the evidence does not support "
        "an EPS estimate, cite what you DID read and return eps: null; that is a "
        "useful answer. An empty list is not, and this lens is dropped for it.",
    )
    confidence: Annotated[float, Field(ge=0, le=1)] = Field(
        description="How much this lens trusts its own estimate, given its "
        "evidence. Uncalibrated by nature; it is discounted downstream."
    )

    # ---- the model's language ------------------------------------------- #
    #
    # A lens that returns only an EPS has said what it concludes and not what it
    # believes. Two lenses can land on the same number through opposite views —
    # one expecting volume and margin compression, the other the reverse — and an
    # ensemble that sees only the outputs cannot tell agreement from coincidence.
    #
    # These are the drivers the three-statement model actually runs on, so a lens
    # answering in them is answering in the model's language: its view becomes a
    # forecast column rather than a number sitting beside one. Every field is
    # optional, because a lens should only speak to what its evidence covers —
    # the Macro lens has no business asserting a gross margin.
    revenue_growth: float | None = Field(
        default=None,
        description="Year-over-year revenue growth for the forecast period, as a "
        "fraction. 0.12 for 12%, never 12.",
    )
    gross_margin: float | None = Field(
        default=None, description="Gross margin as a fraction in [0,1], or null."
    )
    opex_pct_revenue: float | None = Field(
        default=None,
        description="Operating expenses as a fraction of revenue, or null.",
    )
    tax_rate: float | None = Field(
        default=None, description="Effective tax rate as a fraction in [0,1], or null."
    )


class LensFailure(RuntimeError):
    """Carries the reason so the UI and the judge can both show it."""


def run_lens(
    *,
    client: LLMClient,
    lens: LensName,
    prompt_id: str,
    store: EvidenceStore,
    variables: dict,
    basis: Basis = Basis.NON_GAAP,
    run_index: int = 0,
) -> LensOutput:
    """One lens, one run. Raises LensFailure with a reason on any problem.

    Note what is NOT a parameter: any other lens's output. See the module
    docstring — that omission is load-bearing.
    """
    started = time.monotonic()
    try:
        response, usage = client.call(
            prompt_id,
            schema=LensResponse,
            variables=variables,
            corpus=store.corpus(),
            run_index=run_index,
            # Raised from the 8000 default after a live run lost the Peer read
            # lens to `stop_reason=max_tokens`. A lens that reasons through six
            # peers, cites each and states a mechanism per link is genuinely
            # long, and truncation is the worst way to lose one: the work is
            # done and paid for, and the output is discarded for want of a few
            # hundred tokens. Output is the expensive half, so this is a ceiling
            # rather than a target — nothing is charged for headroom unused.
            max_tokens=LENS_MAX_TOKENS,
        )
    except LLMError as exc:
        raise LensFailure(f"{lens.value}: {exc}") from exc

    if not response.claim_ids:
        # Caught here as well as at construction: a lens that cites nothing has
        # produced an unfalsifiable number, which is the failure mode the whole
        # provenance design exists to prevent.
        raise LensFailure(
            f"{lens.value}: cited no evidence — an uncited estimate is not usable"
        )

    _, unknown = store.resolve(response.claim_ids)
    if unknown:
        # Fabricated citations are a hard failure, not a warning. The claim ids
        # are short and printed in the corpus; getting one wrong means the model
        # referred to evidence that does not exist.
        raise LensFailure(
            f"{lens.value}: cited {len(unknown)} claim id(s) not in the evidence "
            f"store: {', '.join(unknown[:5])}"
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "lens_done",
        lens=lens.value,
        run=run_index,
        eps=response.eps,
        confidence=response.confidence,
        n_claims=len(response.claim_ids),
        latency_ms=latency_ms,
    )

    return LensOutput(
        lens=lens,
        eps=response.eps,
        revenue=response.revenue,
        basis=basis,
        reasoning=response.reasoning,
        claim_ids=response.claim_ids,
        confidence=response.confidence,
        revenue_growth=response.revenue_growth,
        gross_margin=response.gross_margin,
        opex_pct_revenue=response.opex_pct_revenue,
        tax_rate=response.tax_rate,
        run_index=run_index,
        model_used=usage.model,
        input_tokens=usage.input_tokens + usage.cache_read_input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=latency_ms,
    )


def common_vars(ticker: str, period: str, basis: Basis) -> dict:
    """The three variables every lens prompt takes."""
    return {"ticker": ticker, "period": period, "basis": basis.value}


@dataclass
class LensContext:
    """Everything the lenses collectively need, assembled once by layer B.

    Deliberately a bag of *inputs*, never of *outputs*. If you find yourself
    wanting to add a field here so one lens can read another's estimate, that is
    the convergence failure the ensemble exists to avoid — the place to combine
    views is the judge, after each has been argued against.
    """

    ticker: str
    period: str
    as_of: date
    basis: Basis = Basis.NON_GAAP
    sector: str = "unknown"

    # Per-lens context blocks. Each is plain text assembled from the evidence
    # store; an empty one renders as an explicit "not available" rather than a
    # blank, so the model abstains instead of inventing.
    prior_year: str = ""
    drivers: str = ""
    margin_history: str = ""
    quality: str = ""
    exclusions: str = ""
    peers: str = ""
    macro: str = ""

    # The working top line handed to the Margins lens. It comes from prior-year
    # revenue and a naive seasonal growth rate — NOT from the Drivers lens.
    # Sourcing it from Drivers would make Margins a downstream restatement of
    # Drivers rather than an independent view, and the two would agree by
    # construction.
    working_revenue: str = ""
    # Bottom-up market size and this company's share of it, from peers' filed
    # revenue. Feeds the Market lens, which separates riding a wave from taking
    # share — the split consensus forecasts around rather than through.
    industry: str = ""
    # Named customers and suppliers, from the filing's own concentration
    # disclosure. Feeds the Demand lens: a customer's capex IS this revenue.
    value_chain: str = ""

    def missing(self) -> list[str]:
        """Which context blocks are empty. Surfaced in the run manifest so a
        lens that abstained for lack of input is distinguishable from one that
        abstained on judgment."""
        return [
            name
            for name in (
                "prior_year", "drivers", "margin_history", "quality",
                "exclusions", "peers", "macro", "working_revenue", "industry",
                "value_chain",
            )
            if not getattr(self, name).strip()
        ]
