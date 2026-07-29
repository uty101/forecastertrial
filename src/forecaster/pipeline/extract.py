"""Guidance extraction — 8-K EX-99.1 and prepared remarks to structured guides.

Prior-quarter guidance is the strongest single predictor of the coming print and
it is free, but it lives in prose rather than XBRL, which is why this is the one
extraction step that needs a model at all.

**The verbatim quote is the load-bearing field, and it is verified here rather
than trusted.** Every extracted guide is string-matched back against the source
document before it is allowed into the evidence store. A quote that does not
appear in its source is dropped with the extraction, because the alternative is
a guided range that the model composed out of two different sentences — which
reads perfectly and is wrong.

That check is also what turns "we cite sources" into "we verify every citation",
which is a measured property with a number attached rather than a claim.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from forecaster.llm.client import LLMClient, LLMError
from forecaster.pipeline.v1_reconcile import verify_citation
from forecaster.schemas import Basis, Claim, Guidance, Source, SourceKind

log = structlog.get_logger()

# Releases run long and the guidance paragraph is near the end. Truncating from
# the front would cut exactly the part we want.
MAX_DOC_CHARS = 60_000


class ExtractedGuide(BaseModel):
    metric: str = Field(description="eps or revenue")
    period: str = Field(description="The period guided, as the company labels it.")
    low: float | None = None
    high: float | None = None
    point: float | None = None
    basis: str = Field(default="non_gaap", description="gaap or non_gaap")
    constant_currency: bool = False
    quote: str = Field(
        min_length=1,
        description="The verbatim sentence, copied exactly from the source.",
    )


class ExtractionResult(BaseModel):
    guides: list[ExtractedGuide] = Field(default_factory=list)


def extract_guidance(
    client: LLMClient,
    ticker: str,
    document: str,
    source_uri: str,
    filed_date,
    source_kind: SourceKind = SourceKind.FILING_8K,
) -> tuple[list[Guidance], list[Claim], list[str]]:
    """Returns (guides, claims, rejections).

    Each surviving guide comes with the Claim that carries its quote, so the
    downstream lens can cite it and the UI can link to the sentence.

    `rejections` is not an error list to swallow — it is the count that goes on
    the eval screen. A high rejection rate on a company means the extractor is
    paraphrasing, which is worth knowing before the forecast rests on it.
    """
    if not document.strip():
        return [], [], ["empty document"]

    body = document[:MAX_DOC_CHARS]
    try:
        result, _ = client.call(
            "extract_guidance",
            schema=ExtractionResult,
            variables={
                "ticker": ticker,
                "source_uri": source_uri,
                "filed_date": str(filed_date),
                "document": body,
            },
            max_tokens=4000,
        )
    except LLMError as exc:
        log.warning("guidance_extraction_failed", uri=source_uri, error=str(exc))
        return [], [], [f"extraction failed: {exc}"]

    source = Source(kind=source_kind, uri=source_uri, as_of=filed_date)
    guides: list[Guidance] = []
    claims: list[Claim] = []
    rejections: list[str] = []

    for i, extracted in enumerate(result.guides):
        claim_id = f"guide:{ticker}:{extracted.period}:{extracted.metric}:{i}"
        claim = Claim(
            id=claim_id,
            label=f"{extracted.metric} guidance for {extracted.period}",
            value=_representative(extracted),
            unit="USD/share" if extracted.metric == "eps" else "USD",
            period=extracted.period,
            source=source,
            verbatim_quote=extracted.quote,
        )

        # The check. A quote assembled from two sentences reads perfectly and is
        # not what the company said.
        if not verify_citation(claim, document):
            rejections.append(
                f"{extracted.metric} {extracted.period}: quote not found in "
                f"source — {extracted.quote[:80]!r}"
            )
            log.warning(
                "guidance_quote_rejected",
                ticker=ticker,
                metric=extracted.metric,
                period=extracted.period,
            )
            continue

        if extracted.metric not in ("eps", "revenue"):
            rejections.append(f"unrecognised metric {extracted.metric!r}")
            continue

        claims.append(claim)
        guides.append(
            Guidance(
                metric=extracted.metric,  # type: ignore[arg-type]
                period=extracted.period,
                low=extracted.low,
                high=extracted.high,
                point=extracted.point,
                basis=Basis.GAAP if extracted.basis == "gaap" else Basis.NON_GAAP,
                constant_currency=extracted.constant_currency,
                claim_id=claim_id,
            )
        )

    log.info(
        "guidance_extracted",
        ticker=ticker,
        kept=len(guides),
        rejected=len(rejections),
        uri=source_uri,
    )
    return guides, claims, rejections


def _representative(guide: ExtractedGuide) -> float | None:
    """A single number for the Claim's value. The range is preserved on the
    Guidance object; this is only so the claim has something to display."""
    if guide.point is not None:
        return guide.point
    if guide.low is not None and guide.high is not None:
        return (guide.low + guide.high) / 2
    return guide.low if guide.low is not None else guide.high
