"""Verification layer 1 — arithmetic and citations.

Nothing else in the pipeline checks anything. This does, and it is plain code.

Two jobs:

  1. Arithmetic. Does the EPS a lens claims actually follow from the revenue,
     margin, opex, tax and share count it also claims? Are units consistent?
     LLMs get this wrong constantly and it is invisible because the output looks
     fine. A millions-vs-thousands error produces a confident, well-argued
     forecast that is off by 1000x.

  2. Citations. Every Claim carries a verbatim_quote. Nothing so far has checked
     the quote actually appears in its source document. It is a string match.

A lens that fails either is DROPPED and logged — never silently averaged in.
That turns "we don't invent figures" from a claim into a measured property, and
gives you a number to put on stage: how many citations failed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from forecaster.schemas import Claim, LensOutput, SourceKind

# Tolerance for the internal-consistency check. Tight enough to catch a real
# error, loose enough to survive rounding in a model with a dozen steps.
REL_TOL = 0.02

# A quarterly EPS change outside this band is almost certainly a units error
# rather than a forecast. Micron has printed +40% surprises, so this is wide on
# purpose — it is a smoke alarm, not a judgment.
SANE_YOY_BAND = (-3.0, 5.0)


@dataclass
class ReconcileResult:
    ok: bool
    errors: list[str]


def _normalise(text: str) -> str:
    """Filings are full of curly quotes, non-breaking spaces and soft hyphens.
    Naive string matching fails on all of them and you spend an hour thinking
    the model hallucinated when it quoted correctly."""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("\xa0", " ").replace("­", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_citation(claim: Claim, source_text: str) -> bool:
    """Does the quote actually appear in the document it claims to come from?"""
    return _normalise(claim.verbatim_quote) in _normalise(source_text)


# Prose sources: a human wrote sentences, a model quoted one of them, and the
# quote must be found in the text. This is where fabrication is possible and
# where string matching earns its keep.
PROSE_SOURCES = {
    SourceKind.FILING_8K,
    SourceKind.FILING_10Q,
    SourceKind.FILING_10K,
    SourceKind.TRANSCRIPT,
    SourceKind.COMPANY_SITE,
    # News belongs here more than anywhere else. A filing is at least a
    # document the company signed; an article is prose from an arbitrary
    # publisher, retrieved by a search engine, and it is the likeliest place for
    # a model to produce a quote that reads perfectly and was never written.
    SourceKind.NEWS,
}

# Structured sources: the "quote" is the tagged fact itself, rendered by the
# source adapter from a typed API response. There is no prose to match against,
# and string-matching a synthetic string against a document that does not exist
# would fail every XBRL claim — which would drop every lens that cited a
# financial figure, i.e. all of them.
#
# This is not a loophole. A model can only cite ids that are already in the
# evidence store, and the store is built entirely from adapter output — so a
# structured claim's VALUE came from the adapter, never from the model. What is
# being trusted here is the SEC's XBRL endpoint, not the model's memory. An id
# that is not in the store is caught separately, in `run_lens`, as a fabricated
# citation.
STRUCTURED_SOURCES = {
    SourceKind.XBRL,
    # The submissions index. Its claims say "this 8-K exists, filed on this date,
    # at this URL" — a fact from a typed JSON feed, not a sentence from the body.
    #
    # These were classified as prose and string-matched against the document they
    # POINT AT, which fails by construction: the descriptor was never written
    # anywhere in the exhibit. A live run dropped the Mechanical lens over it —
    # the one lens with no model in it, so the one place a fabricated citation is
    # impossible. The check was not catching a fabrication; it was measuring the
    # wrong thing against the wrong document.
    SourceKind.FILING_INDEX,
    SourceKind.CONSENSUS,
    SourceKind.SPONSOR,
    SourceKind.MACRO,
    SourceKind.PEER,
}


def verify_citations(
    claims: list[Claim], documents: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Returns (verified_claim_ids, failed_claim_ids).

    Prose claims must string-match their source document, and a prose claim
    whose document is missing counts as unverified rather than passed — absence
    of evidence is not evidence.

    Structured claims are verified by construction; see STRUCTURED_SOURCES.

    `DERIVED` is deliberately in neither set: a derived figure is one this
    pipeline computed, so it is only as good as its own inputs, and it must be
    justified by the claims underneath it rather than by its own existence.
    """
    verified: list[str] = []
    failed: list[str] = []

    for claim in claims:
        kind = claim.source.kind

        if kind in STRUCTURED_SOURCES:
            verified.append(claim.id)
            continue

        doc = documents.get(claim.source.uri)
        if doc is None or not verify_citation(claim, doc):
            failed.append(claim.id)
        else:
            verified.append(claim.id)

    return verified, failed


def check_arithmetic(
    *,
    revenue: float,
    gross_margin: float,
    opex: float,
    tax_rate: float,
    shares: float,
    claimed_eps: float,
    other_income: float = 0.0,
    segment_revenues: list[float] | None = None,
    revenue_prior_year: float | None = None,
) -> ReconcileResult:
    """Recompute EPS from first principles and compare with what was claimed."""
    errors: list[str] = []

    if shares <= 0:
        errors.append(f"share count must be positive, got {shares:,.0f}")
        return ReconcileResult(False, errors)
    if not 0.0 <= gross_margin <= 1.0:
        errors.append(
            f"gross margin {gross_margin} outside [0,1] — probably a percent/fraction "
            "unit error"
        )
    if not 0.0 <= tax_rate < 1.0:
        errors.append(f"tax rate {tax_rate} outside [0,1)")

    implied = ((revenue * gross_margin - opex + other_income) * (1 - tax_rate)) / shares
    if claimed_eps != 0 and abs(implied - claimed_eps) / abs(claimed_eps) > REL_TOL:
        errors.append(
            f"EPS does not reconcile: claimed {claimed_eps:.4f}, "
            f"implied by its own inputs {implied:.4f} "
            f"({abs(implied - claimed_eps) / abs(claimed_eps):.1%} apart)"
        )

    if segment_revenues:
        total = sum(segment_revenues)
        if revenue != 0 and abs(total - revenue) / abs(revenue) > REL_TOL:
            errors.append(
                f"segments sum to {total:,.0f} but total revenue is {revenue:,.0f}"
            )

    if revenue_prior_year:
        yoy = revenue / revenue_prior_year - 1
        lo, hi = SANE_YOY_BAND
        if not lo <= yoy <= hi:
            errors.append(
                f"implied YoY revenue growth {yoy:+.1%} is outside the sane band — "
                "check for a units error (millions vs thousands)"
            )

    return ReconcileResult(not errors, errors)


def reconcile_lens(
    lens: LensOutput,
    arithmetic: ReconcileResult | None,
    failed_claim_ids: list[str],
) -> LensOutput:
    """Stamp the verdict onto the lens. Returns a new object; nothing mutates."""
    errors: list[str] = []
    if arithmetic is not None:
        errors.extend(arithmetic.errors)
    if failed_claim_ids:
        errors.append(
            f"{len(failed_claim_ids)} citation(s) not found in source: "
            f"{', '.join(failed_claim_ids[:5])}"
        )
    if not lens.claim_ids:
        errors.append("lens cited no evidence at all")

    return lens.model_copy(update={"reconciled": not errors, "reconcile_errors": errors})


def drop_failed(lenses: list[LensOutput]) -> tuple[list[LensOutput], dict[str, str]]:
    """Split into survivors and a {lens: reason} map for the judge and the UI.

    The judge is told which lenses are missing — an ensemble that silently
    shrinks is an ensemble whose weights no longer mean anything.
    """
    kept: list[LensOutput] = []
    dropped: dict[str, str] = {}
    for lens in lenses:
        if lens.usable and lens.reconciled is not False:
            kept.append(lens)
        else:
            dropped[lens.lens.value] = "; ".join(lens.reconcile_errors) or "no estimate"
    return kept, dropped
