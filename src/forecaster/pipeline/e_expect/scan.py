"""Scoring what the internet says, and reading eight earnings calls at once.

Two extractions, both on the cheap tier, both producing structure from prose that
no filing contains. They are together because they share the one rule that makes
either usable: **every claim carries a verbatim quote, and a quote that cannot be
found in the source document is dropped.** `v1_reconcile` string-matches, so an
invented sentence takes the whole finding with it.

**Perception.** Articles scored for stance and conviction, per subject. What this
must not become is a word-polarity count: those produce a number that looks
quantitative and measures publication volume, and coverage spikes before every
print regardless of direction. So the model is asked for a STANCE with a QUOTE
that supports it, and the aggregate reads dispersion separately from direction.

**The calls.** This is the reading that no analyst can match — not because the
work is hard, but because it is forty hours of audio and nobody remembers quarter
five well enough to compare it to quarter one. The signal is DISCLOSURE
WITHDRAWAL: a company that gave a segment number for six quarters and stops is
telling you something, and it is a fact rather than an impression. Either the
number was said or it was not.

The prompt asks for what changed ACROSS quarters, never for a summary of one. A
summary of the latest call is the least valuable thing that could be extracted
from eight of them, and it is what a model will produce by default.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import structlog
from pydantic import BaseModel, Field

from forecaster.llm.client import LLMClient, LLMError
from forecaster.pipeline.e_expect.perception import Perception, Read

log = structlog.get_logger()

# Enough to see a pattern, few enough that the cheap tier reads them properly.
# Eight quarters is also what an analyst covering a name would have heard.
MAX_CALLS = 8

# A transcript is 45–70k characters. Eight of them will not fit a cheap-tier
# context alongside anything else, so each is trimmed to the part that carries
# the signal — the Q&A, where somebody has to answer a question they did not
# choose. Prepared remarks are written by IR.
CALL_CHARS = 9_000


class ScoredArticle(BaseModel):
    subject: Literal["company", "industry"]
    stance: Literal["bullish", "neutral", "bearish"]
    conviction: Annotated[float, Field(ge=0, le=1)] = Field(
        description="How strongly the piece commits. A hedged 'may benefit' is "
        "0.3; an unambiguous call is 0.9. Not how much YOU agree."
    )
    claim: str = Field(description="What it actually asserts, in one sentence.")
    quote: str = Field(
        description="A verbatim sentence from the article supporting the stance. "
        "Copied exactly — it is string-matched against the source and a quote "
        "that cannot be found drops the whole item."
    )
    url: str = Field(description="The article URL, exactly as given.")


class PerceptionResponse(BaseModel):
    articles: list[ScoredArticle] = Field(
        description="One entry per article that takes a position. Skip anything "
        "purely factual — a report of what was filed is not a stance."
    )


class DisclosureChange(BaseModel):
    """Something the company used to say and has stopped saying, or vice versa."""

    kind: Literal["withdrawn", "introduced", "reframed", "deflected"] = Field(
        description="withdrawn: a metric or commitment given before and absent "
        "now. introduced: new disclosure. reframed: the same subject described "
        "in materially different terms. deflected: a direct question not answered."
    )
    subject: str = Field(description="What it concerns — a segment, a metric, a "
                         "guidance element, a customer.")
    last_seen: str = Field(
        default="", description="The quarter it was last present, if withdrawn."
    )
    what_changed: str = Field(
        description="Stated as a comparison across quarters, not as a summary of "
        "one call. 'Stopped giving datacentre units after 2026Q2' — not "
        "'management discussed datacentre demand'."
    )
    quote: str = Field(
        description="A verbatim sentence from one of the transcripts. Copied "
        "exactly; it is string-matched and a quote that cannot be found drops "
        "the finding."
    )
    matters_because: str = Field(
        description="The forecasting consequence in one sentence, or say there "
        "is none. A change with no consequence is an observation, not a finding."
    )


class CallsResponse(BaseModel):
    changes: list[DisclosureChange] = Field(
        description="What changed ACROSS the quarters. Empty is a legitimate "
        "and useful answer — a company that discloses consistently is telling "
        "you that too."
    )
    tone_shift: str = Field(
        default="",
        description="Any directional change in how management talks about "
        "demand, pricing or capacity across the sequence, with the quarter it "
        "turned. Say 'none detectable' rather than inventing one.",
    )


def _verified(quote: str, documents: dict[str, str]) -> bool:
    """The quote must exist in one of the source documents.

    Same rule as every other extraction here. A model asked for a verbatim
    sentence will occasionally produce a fluent paraphrase, and a paraphrase
    reads exactly like a quotation.
    """
    needle = " ".join(quote.split())[:180]
    if len(needle) < 25:
        return False
    return any(needle in " ".join(body.split()) for body in documents.values())


def score_articles(
    client: LLMClient,
    ticker: str,
    articles: list[dict],
    documents: dict[str, str],
    run_index: int = 0,
) -> Perception:
    """Score coverage for stance and conviction. Cheap tier.

    `articles` is [{url, title, text, publishedDate}] straight from the news
    search; `documents` is what the quotes are checked against.
    """
    result = Perception(ticker=ticker)
    usable = [a for a in articles if (a.get("text") or "").strip()][:14]
    if not usable:
        result.skipped.append("no article bodies to score")
        return result

    block = "\n\n".join(
        f"URL: {a['url']}\nTITLE: {a.get('title', '')}\n{(a.get('text') or '')[:2400]}"
        for a in usable
    )

    try:
        response, _ = client.call(
            "scan_perception",
            schema=PerceptionResponse,
            variables={"ticker": ticker, "articles": block},
            run_index=run_index,
        )
    except LLMError as exc:
        result.skipped.append(f"perception scan failed: {exc}")
        return result

    by_url = {a["url"]: a for a in usable}
    for item in response.articles:
        source = by_url.get(item.url)
        if source is None:
            result.skipped.append(f"scored a URL that was not supplied: {item.url[:60]}")
            continue
        if not _verified(item.quote, {item.url: source.get("text") or ""}):
            result.skipped.append(
                f"{item.url[:50]}: the quote is not in the article — dropped"
            )
            continue
        try:
            published = date.fromisoformat(str(source.get("publishedDate"))[:10])
        except ValueError:
            result.skipped.append(f"{item.url[:50]}: undated")
            continue
        result.reads.append(
            Read(
                subject=item.subject,
                stance=item.stance,
                conviction=item.conviction,
                claim=item.claim,
                quote=item.quote,
                url=item.url,
                published=published,
            )
        )

    log.info(
        "perception_scored", ticker=ticker, scored=len(result.reads),
        dropped=len(result.skipped),
    )
    return result


def read_calls(
    client: LLMClient,
    ticker: str,
    transcripts: list,
    run_index: int = 0,
) -> tuple[CallsResponse | None, list[str]]:
    """Read eight quarters at once and report what CHANGED. Cheap tier.

    The prompt is built oldest-first so the sequence reads forward, which is how
    a withdrawal becomes visible: you notice the absence only after seeing the
    presence.

    Each call is trimmed to the Q&A. Prepared remarks are written by investor
    relations and say what the company chose to say; the Q&A is where somebody
    has to answer a question they did not choose, and it is where a metric gets
    quietly dropped.
    """
    notes: list[str] = []
    usable = [t for t in transcripts if getattr(t, "period", None)][:MAX_CALLS]
    if len(usable) < 3:
        return None, [
            f"only {len(usable)} identifiable quarters — a change across the "
            "sequence needs at least three to be a change rather than a difference"
        ]

    ordered = sorted(usable, key=lambda t: t.period)
    block = "\n\n".join(
        f"=== {t.period} (call held {t.published}) ===\n{_qa_slice(t.text)}"
        for t in ordered
    )
    documents = {t.url: t.text for t in ordered}

    try:
        response, _ = client.call(
            "scan_calls",
            schema=CallsResponse,
            variables={
                "ticker": ticker,
                "quarters": ", ".join(t.period for t in ordered),
                "transcripts": block,
            },
            run_index=run_index,
        )
    except LLMError as exc:
        return None, [f"call scan failed: {exc}"]

    kept = []
    for change in response.changes:
        if not _verified(change.quote, documents):
            notes.append(
                f"{change.subject[:40]}: the quote is not in any transcript — dropped"
            )
            continue
        kept.append(change)
    response.changes = kept

    log.info(
        "calls_read", ticker=ticker, quarters=len(ordered),
        changes=len(kept), dropped=len(notes),
    )
    return response, notes


def _qa_slice(text: str) -> str:
    """The question-and-answer half, or the tail if it cannot be found."""
    low = text.lower()
    for marker in (
        "question-and-answer", "question and answer", "q&a session",
        "we'll now begin the question", "first question comes from",
    ):
        index = low.find(marker)
        if index != -1:
            return text[index : index + CALL_CHARS]
    return text[-CALL_CHARS:]


def to_block(response: CallsResponse | None, notes: list[str]) -> str:
    """For the lenses. Leads with withdrawals, because that is the finding."""
    if response is None:
        return "(no cross-quarter call reading — " + "; ".join(notes) + ")"
    if not response.changes and not response.tone_shift:
        return (
            "EARNINGS CALLS — nothing changed across the quarters read. A company "
            "that discloses consistently is telling you that too, and it is the "
            "correct answer more often than not."
        )

    lines = [
        "EARNINGS CALLS — what changed ACROSS the quarters, not what was said "
        "in the latest one.",
        "",
    ]
    order = {"withdrawn": 0, "deflected": 1, "reframed": 2, "introduced": 3}
    for change in sorted(response.changes, key=lambda c: order.get(c.kind, 9)):
        seen = f" (last seen {change.last_seen})" if change.last_seen else ""
        lines.append(f"  [{change.kind.upper()}] {change.subject}{seen}")
        lines.append(f"      {change.what_changed}")
        lines.append(f"      matters because: {change.matters_because}")
    if response.tone_shift:
        lines += ["", f"  Tone: {response.tone_shift}"]
    if notes:
        lines += ["", "  Dropped:"] + [f"    {n}" for n in notes[:3]]
    return "\n".join(lines)
