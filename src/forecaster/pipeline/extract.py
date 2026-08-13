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
from forecaster.model.bridge import Bridge, BridgeItem
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

    seen: set[tuple] = set()
    for i, extracted in enumerate(result.guides):
        if extracted.metric not in ("eps", "revenue"):
            rejections.append(f"unrecognised metric {extracted.metric!r}")
            continue

        # A guide with no number is not guidance. The extractor emits these for
        # companies that decline to guide a metric — NVDA gives revenue and
        # margin but no EPS — and an empty range downstream reads as "guidance
        # exists and is unknown" rather than "none was given".
        if extracted.low is extracted.high is extracted.point is None:
            rejections.append(
                f"{extracted.metric} {extracted.period}: no low, high or point"
            )
            continue

        _rescale(extracted)

        signature = (
            extracted.metric, extracted.period, extracted.basis,
            extracted.low, extracted.high, extracted.point,
        )
        if signature in seen:
            # The same sentence appears in both EX-99.1 and EX-99.2, and the
            # model reports it under each basis. Four copies of one fact.
            continue
        seen.add(signature)

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


class ExtractedItem(BaseModel):
    label: str = Field(description="The company's own words for the line.")
    per_share: float = Field(
        description="Signed so GAAP + all items = non-GAAP. An excluded cost is "
        "positive; an excluded gain is negative."
    )
    quote: str = Field(min_length=1, description="The verbatim line or sentence.")


class ExtractedBridge(BaseModel):
    found: bool = Field(description="False when the release reports GAAP only.")
    period: str = ""
    eps_gaap: float | None = None
    eps_non_gaap: float | None = None
    items: list[ExtractedItem] = Field(default_factory=list)
    units_note: str = Field(
        default="",
        description="Set only when the per-share column was unavailable and the "
        "figures are absolute.",
    )


def extract_bridge(
    client: LLMClient,
    ticker: str,
    document: str,
    source_uri: str,
    filed_date,
    source_kind: SourceKind = SourceKind.FILING_8K,
) -> tuple[Bridge | None, list[Claim], list[str]]:
    """The GAAP↔non-GAAP reconciliation out of one earnings release.

    Returns (bridge, claims, rejections). The bridge is `None` when the release
    reports GAAP only — which is common and correct, not a failure.

    **Every item is dropped unless its quote is in the document, and the bridge
    is checked against the company's own reported non-GAAP figure before it is
    returned.** Both matter more here than anywhere else in the system: a bridge
    that is missing one line is a systematic error in a single direction, which
    is the kind that looks like a bad model rather than a bug. `Bridge.verify`
    is what turns that from an assumption into a number, so a bridge that does
    not tie comes back with the failure recorded rather than silently used.

    The absolute-dollar case is refused outright. Dividing a $1.2bn add-back by
    a share count we inferred is exactly the units error that stays internally
    consistent while being wrong by six orders of magnitude.
    """
    if not document.strip():
        return None, [], ["empty document"]

    try:
        result, _ = client.call(
            "extract_bridge",
            schema=ExtractedBridge,
            variables={
                "ticker": ticker,
                "source_uri": source_uri,
                "filed_date": str(filed_date),
                "document": document[:MAX_DOC_CHARS],
            },
            max_tokens=4000,
        )
    except LLMError as exc:
        log.warning("bridge_extraction_failed", uri=source_uri, error=str(exc))
        return None, [], [f"bridge extraction failed: {exc}"]

    if not result.found or result.eps_gaap is None:
        return None, [], []

    if result.units_note:
        return None, [], [
            f"{source_uri}: reconciliation given in absolute dollars only "
            f"({result.units_note}) — refusing to divide by an inferred share "
            "count, which is the units error that stays self-consistent"
        ]

    source = Source(kind=source_kind, uri=source_uri, as_of=filed_date)
    period = result.period or "unlabelled"
    items: list[BridgeItem] = []
    claims: list[Claim] = []
    rejections: list[str] = []

    for i, extracted in enumerate(result.items):
        claim = Claim(
            id=f"bridge:{ticker}:{period}:{i}",
            label=f"{extracted.label} ({period})",
            value=extracted.per_share,
            unit="USD/share",
            period=period,
            source=source,
            verbatim_quote=extracted.quote,
        )
        if not verify_citation(claim, document):
            rejections.append(
                f"{extracted.label}: quote not found in source — "
                f"{extracted.quote[:80]!r}"
            )
            continue
        claims.append(claim)
        items.append(
            BridgeItem(label=extracted.label, per_share=extracted.per_share,
                       claim=claim)
        )

    built = Bridge(eps_gaap=result.eps_gaap, items=items)

    # The check that makes the rest of it usable. A bridge is only worth having
    # if it reproduces the figure the company itself printed.
    if result.eps_non_gaap is not None:
        ties, message = built.verify(result.eps_non_gaap)
        if not ties:
            rejections.append(message)
            log.warning("bridge_does_not_tie", ticker=ticker, period=period,
                        uri=source_uri)

    log.info(
        "bridge_extracted", ticker=ticker, period=period, items=len(items),
        rejected=len(rejections), gap_pct=round(built.gap_pct, 3),
    )
    return built, claims, rejections


def count_recurrence(bridges: list[Bridge]) -> None:
    """Mark items that keep coming back, across a sequence of quarters.

    In place, oldest-to-newest irrelevant — recurrence is a count, not an order.

    This is the half of the bridge that is analysis rather than bookkeeping. Four
    consecutive quarters of the same "one-off" is not an unusual item; it is a
    permanent cost the company has moved below its own line, and a company whose
    non-GAAP premium is mostly recurring has quietly lowered the bar it is
    measured against. `Bridge.recurring_adjustment` is what Forensics reads.

    Matched on a normalised label because the wording drifts — "Stock-based
    compensation expense" one quarter, "Stock-based compensation" the next.
    """
    counts: dict[str, int] = {}
    for bridge in bridges:
        for item in bridge.items:
            counts[_normalise(item.label)] = counts.get(_normalise(item.label), 0) + 1

    for bridge in bridges:
        bridge.items = [
            BridgeItem(
                label=item.label, per_share=item.per_share, claim=item.claim,
                note=item.note, quarters_recurring=counts[_normalise(item.label)],
            )
            for item in bridge.items
        ]


def _normalise(label: str) -> str:
    """'Stock-based compensation expense' and 'Stock-Based Compensation' are one
    line. Trailing nouns that add nothing are dropped so they match."""
    words = [w for w in label.lower().replace("-", " ").split() if w.isalpha()]
    drop = {"expense", "expenses", "charges", "charge", "costs", "cost", "net",
            "of", "and", "the", "related", "items", "item"}
    kept = [w for w in words if w not in drop]
    return " ".join(kept or words)


SCALES = (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3))


def _rescale(guide: ExtractedGuide) -> None:
    """Put revenue guidance into absolute dollars, using the sentence's own units.

    "Millions vs thousands is the error that will actually bite" — and this is
    where it bites. The release says "Revenue is expected to be $91.0 billion,
    plus or minus 2%", and the extractor faithfully returns 89.18 to 92.82,
    because that is what the sentence says. Stored against a claim whose unit is
    USD, ninety-one billion dollars becomes ninety-one dollars, and every
    comparison downstream is off by nine orders of magnitude while every number
    stays internally consistent.

    The scale is read from the quote we have ALREADY string-matched against the
    filing, so it is the company's own word rather than an inference.

    EPS is deliberately untouched. It is dollars per share, never billions, and
    a release mentioning both in one sentence would otherwise multiply it.
    """
    if guide.metric != "revenue":
        return
    lowered = guide.quote.lower()
    factor = next((mult for word, mult in SCALES if word in lowered), None)
    if factor is None:
        return

    values = [v for v in (guide.low, guide.high, guide.point) if v is not None]
    # Only when the figures are plainly quoted in that scale. A release already
    # reporting absolute dollars must not be multiplied a second time.
    if not values or max(abs(v) for v in values) >= 1e6:
        return

    for field_name in ("low", "high", "point"):
        value = getattr(guide, field_name)
        if value is not None:
            setattr(guide, field_name, value * factor)


def _representative(guide: ExtractedGuide) -> float | None:
    """A single number for the Claim's value. The range is preserved on the
    Guidance object; this is only so the claim has something to display."""
    if guide.point is not None:
        return guide.point
    if guide.low is not None and guide.high is not None:
        return (guide.low + guide.high) / 2
    return guide.low if guide.low is not None else guide.high
