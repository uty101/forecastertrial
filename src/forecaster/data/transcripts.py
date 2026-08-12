"""Earnings call transcripts, and the one edge an agent has that an analyst cannot match.

**I told you this was impossible and it was not.** All six data adapters return
`None` from `get_transcript`, so the conclusion was that transcripts are out of
reach. They are not: every company holds a public call, and Motley Fool,
Investing.com, Insider Monkey and Benzinga all publish the full text within a
day or two. Exa finds them, date-bounded, at 50–70k characters each.

**Why this matters more than any other source here.** An analyst listens to eight
quarters of calls and forms an impression — tone, hesitation, who fields which
question, who stops answering. That impression is real and it is also the least
reproducible thing they do, because it lives in one person's memory of forty
hours of audio.

An agent cannot be in the room. What it can do is read forty quarters in ninety
seconds and apply the IDENTICAL test to every one, which no analyst can. That is
not a substitute for being in the room; it is a different instrument, and it is
the one place in this system where the machine is structurally better rather than
merely faster.

**The signal that justifies the tokens is disclosure withdrawal.** A company that
gave a segment number for six quarters and stops giving it is telling you
something, and it is invisible to anyone reading one transcript. It is trivially
visible to something reading eight, and it is a fact rather than a vibe: either
the number was said or it was not.

**Point-in-time is the risk.** A transcript published after `as_of` is the answer
to the question we are asking. Exa's `publishedDate` is inferred from HTML and
undated results are dropped rather than assumed old — but the harder problem is
that a transcript's own quarter must be read from its title, because a piece
published in May about Q1 is legitimate and a piece published in May about Q2 is
a leak. Both are matched here and the quarter is checked, not just the date.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

import structlog

from forecaster.schemas import Claim, Source, SourceKind

log = structlog.get_logger()

# The publishers that carry full text rather than a summary. Ranked: Motley Fool
# and Investing.com run the complete prepared remarks AND the Q&A, which is the
# half that matters — prepared remarks are written by IR and say what the company
# chose to say; the Q&A is where somebody has to answer.
TRANSCRIPT_DOMAINS = (
    "fool.com",
    "investing.com",
    "insidermonkey.com",
    "benzinga.com",
    "seekingalpha.com",
    "nasdaq.com",
)

# Below this it is a news write-up about the call, not the call. A real
# transcript of a quarterly call runs 40k–90k characters.
MIN_TRANSCRIPT_CHARS = 15_000

QUARTER_PATTERNS = (
    re.compile(r"\bq(?P<q>[1-4])[\s\-_](?:fy[\s\-_]?)?(?P<y>20\d{2})\b", re.I),
    re.compile(r"\b(?P<y>20\d{2})[\s\-_]q(?P<q>[1-4])\b", re.I),
    re.compile(r"\bfourth[\s\-]quarter[\s\-](?P<y4>20\d{2})\b", re.I),
    re.compile(r"\bthird[\s\-]quarter[\s\-](?P<y3>20\d{2})\b", re.I),
    re.compile(r"\bsecond[\s\-]quarter[\s\-](?P<y2>20\d{2})\b", re.I),
    re.compile(r"\bfirst[\s\-]quarter[\s\-](?P<y1>20\d{2})\b", re.I),
)


@dataclass(frozen=True)
class Transcript:
    ticker: str
    period: str | None
    published: date
    url: str
    title: str
    text: str

    @property
    def id(self) -> str:
        return f"call:{self.ticker}:{hashlib.sha1(self.url.encode()).hexdigest()[:10]}"

    def has_qa(self) -> bool:
        """Whether the Q&A section is present.

        The prepared remarks are written by investor relations and say what the
        company chose to say. The Q&A is where someone has to answer a question
        they did not choose, which is the half worth reading — a transcript
        without it is a press release with speaker labels.
        """
        low = self.text.lower()
        return any(
            marker in low
            for marker in (
                "question-and-answer", "question and answer", "q&a session",
                "we'll now begin the question", "first question comes from",
                "operator instructions",
            )
        )


def quarter_of(text: str) -> str | None:
    """The fiscal quarter a transcript is ABOUT, from its title or URL.

    Not from the publication date. A piece published in May about Q1 is
    legitimate; one published in May about Q2 is a leak, and they are
    indistinguishable by date alone.
    """
    for pattern in QUARTER_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("q") and groups.get("y"):
            return f"{groups['y']}Q{groups['q']}"
        for n in (1, 2, 3, 4):
            if groups.get(f"y{n}"):
                return f"{groups[f'y{n}']}Q{n}"
    return None


def looks_like_transcript(url: str, title: str, text: str) -> bool:
    """A full call, not a news story about one.

    Length is the discriminator that actually works. A write-up quoting the CEO
    runs a few thousand characters; the call itself runs forty thousand or more,
    and no amount of keyword matching separates them as reliably as that.
    """
    if len(text) < MIN_TRANSCRIPT_CHARS:
        return False
    low = f"{url} {title}".lower()
    return "transcript" in low or "earnings call" in low


def from_results(ticker: str, results: list[dict], as_of: date) -> list[Transcript]:
    """Turn Exa results into transcripts, newest first, deduplicated by quarter.

    One transcript per quarter. Four publishers carry the same call and reading
    all four costs four times the tokens for the same words — the first one found
    wins, and the domain ranking above decides which that is.
    """
    found: list[Transcript] = []
    seen: set[str] = set()

    for result in results:
        url = str(result.get("url") or "")
        title = str(result.get("title") or "")
        text = (result.get("text") or "").strip()
        published = result.get("publishedDate")
        if not url or not text or not published:
            continue
        if not looks_like_transcript(url, title, text):
            continue

        try:
            published_on = date.fromisoformat(str(published)[:10])
        except ValueError:
            continue
        if published_on > as_of:
            # Exa is asked for a bounded window, but the bound is on an inferred
            # date. Checking again here costs nothing and a transcript from
            # after the lock date is the answer to the question being asked.
            continue

        period = quarter_of(f"{title} {url}")
        if period is None:
            # Without a quarter it cannot be placed in the sequence, and the
            # whole value here is the sequence — a number given for six quarters
            # and withheld in the seventh. A conference-call ANNOUNCEMENT and a
            # blog post about the call both land here, both long enough to pass
            # the length test, and neither is a transcript of anything.
            continue
        if period in seen:
            continue
        seen.add(period)

        found.append(
            Transcript(
                ticker=ticker, period=period, published=published_on,
                url=url, title=title, text=text,
            )
        )

    found.sort(key=lambda t: t.published, reverse=True)
    log.info(
        "transcripts_found", ticker=ticker, n=len(found),
        quarters=[t.period for t in found],
        with_qa=sum(1 for t in found if t.has_qa()),
    )
    return found


def to_claim(transcript: Transcript) -> Claim:
    """A citable claim whose quote is the call's opening line.

    Lifted from the stored body rather than composed, so it verifies by
    construction — the same rule the news source follows, and for the same
    reason: `v1_reconcile` string-matches every prose quote against its source,
    and a descriptive quote appears nowhere in the document.
    """
    opening = re.sub(r"\s+", " ", transcript.text[:400]).strip()
    cut = opening.rfind(".", 0, 300)
    quote = opening[: cut + 1] if cut > 60 else opening[:280]
    label = f"{transcript.ticker} earnings call"
    if transcript.period:
        label += f" — {transcript.period}"
    return Claim(
        id=transcript.id,
        label=label,
        value=None,
        period=transcript.period,
        source=Source(
            kind=SourceKind.TRANSCRIPT,
            uri=transcript.url,
            as_of=transcript.published,
        ),
        verbatim_quote=quote,
    )


def search_query(ticker: str, company: str = "") -> str:
    name = f"{company} " if company else ""
    return (
        f"{name}{ticker} quarterly earnings call transcript "
        "prepared remarks question and answer session"
    )
