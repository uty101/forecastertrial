"""The company's own website, when there is no registry to read.

EDGAR is a US registry, and the registries elsewhere do not rhyme with it: the UK
has the National Storage Mechanism, Japan has EDINET, Canada has SEDAR+,
Switzerland has essentially nothing centralised at all. Building an adapter per
country is weeks of work and still leaves a hole the day a ticker arrives from a
country nobody wired up.

**But there is one publisher every listed company on earth has: itself.** A
half-year report, a results release and a results presentation are on the
company's own domain, in the same three formats, for Nestlé and Toyota and LVMH
alike. That is the universal route, and it is the one this module takes.

Two steps, both cheap:

    1. the domain    from the exchange profile — `nestle.com`, `global.toyota`.
                     Not guessed from the company name, which produces
                     `nestle.com` for Nestlé and something wrong for almost
                     everyone else.
    2. the documents a date-bounded search restricted to that domain, ranked by
                     what actually carries numbers.

**The point-in-time rule survives intact**, and this is the part worth being
careful about. The search is bounded by `as_of` exactly as the news search is, so
a document published after the forecast date is never returned. That matters more
here than for news: a results release published the day after `as_of` contains
the answer.

**What this is not.** It is not a replacement for a registry where one exists. A
filing is a signed document with a filing date; a page on a corporate site can be
edited silently. For a US filer, EDGAR is used and this never runs.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

import structlog

from forecaster.schemas import Claim, Source, SourceKind

log = structlog.get_logger()

# Ranked by how much of a forecast the document actually carries. The release is
# first because it has the reconciliation and the outlook paragraph in it; the
# annual report is last because it is 300 pages, most of which is governance.
#
# Each is a separate search rather than one broad one: a single query returns
# eight near-identical hits on whichever page ranks best, and the point is
# COVERAGE of document types, not depth on one.
QUERIES: tuple[tuple[str, str], ...] = (
    ("half-year results press release", "the release — outlook and reconciliation"),
    ("full year results announcement", "the annual print"),
    ("results presentation slides", "segment detail, usually clearer than prose"),
    ("interim report financial statements", "the statements themselves"),
    ("trading statement outlook guidance", "any between-report update"),
)

# Enough to cover the document types, few enough that acquisition stays bounded.
PER_QUERY = 2

# Below this a "document" is a landing page listing links, not a report.
MIN_BODY_CHARS = 2_000

# A domain filter matches SUBDOMAINS, and a large company's domain hosts a great
# deal that is not investor relations. Searching nestle.com for "interim report
# financial statements" returned four job adverts and one results release —
# `jobdetails.nestle.com` carries postings for financial-reporting managers,
# which match the query almost perfectly and are worth nothing.
#
# Feeding those into the evidence store is worse than finding nothing: a lens
# would cite a recruitment page as disclosure, and the quote would verify,
# because the page really does say it.
REJECT_HOSTS = ("job", "career", "recruit", "talent", "workday", "shop", "store")
REJECT_PATHS = ("/job", "/career", "/vacanc", "/recruit", "/brands/", "/recipes")

# Paths that say "this is the investor material". Not required — a results PDF
# often sits under /sites/default/files — but a strong signal when present.
IR_PATHS = (
    "investor", "/media/", "press", "result", "report", "financial",
    "annual", "interim", "presentation", "regulatory", "asset-library",
)

# Same document, several languages. The corpus is read by a model that handles
# all of them, but a French PDF and its English twin are one fact taking two
# slots, and the English filename is the one that also carries the searchable
# section headings the extractors key on.
NON_ENGLISH = ("-fr.", "-de.", "-es.", "-it.", "-pt.", "-ja.", "-zh.", "-ru.",
               "/fr/", "/de/", "/es/", "/it/", "/ja/", "/zh/")


def _relevance(uri: str) -> int:
    """How much this URL looks like investor material. Negative means reject.

    Scored rather than filtered with a single rule, because the shapes vary: a
    results release can be a PDF under /sites/default/files with nothing
    investor-ish in the path, while an obvious /investors/ page can be a
    navigation stub.
    """
    lowered = uri.lower()
    host = urlparse(lowered).netloc
    path = urlparse(lowered).path

    if any(token in host for token in REJECT_HOSTS):
        return -1
    if any(token in path for token in REJECT_PATHS):
        return -1

    score = 0
    if path.endswith(".pdf"):
        score += 3
    score += sum(2 for token in IR_PATHS if token in path)
    if any(token in lowered for token in NON_ENGLISH):
        score -= 2
    return score


def domain_of(website: str | None) -> str | None:
    """`https://www.nestle.com/investors` -> `nestle.com`.

    The `www.` is stripped because Exa's domain filter matches the registrable
    domain and a `www.` prefix silently returns nothing — a filter that excludes
    everything looks exactly like a company that publishes nothing.
    """
    if not website:
        return None
    host = urlparse(website if "//" in website else f"https://{website}").netloc
    host = host.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def fetch(
    exa,
    ticker: str,
    company_name: str,
    website: str | None,
    as_of: date,
    limit: int = 8,
) -> tuple[list[Claim], dict[str, str], list[str]]:
    """Results documents from the company's own domain.

    Returns `(claims, documents, notes)` in the same shape the filings acquirer
    produces, so the caller does not branch on which route the evidence came
    from. `notes` records what was searched and what came back — an empty result
    from a real search is information, and silently returning nothing reads as
    "we did not look".
    """
    site = domain_of(website)
    if site is None:
        return [], {}, [f"{ticker}: no company website on the exchange profile"]
    if exa is None:
        return [], {}, [f"{ticker}: no search source configured — cannot reach {site}"]

    claims: list[Claim] = []
    documents: dict[str, str] = {}
    notes: list[str] = []
    seen: set[str] = set()

    for phrase, why in QUERIES:
        if len(documents) >= limit:
            notes.append(f"stopped at {limit} documents; {phrase!r} not searched")
            break
        try:
            results = exa.search(
                f"{company_name} {phrase}",
                as_of,
                domains=[site],
                limit=PER_QUERY,
            )
        except Exception as exc:  # noqa: BLE001 — one bad query is not fatal
            notes.append(f"{phrase!r} failed: {exc}")
            continue

        if not results:
            notes.append(f"{phrase!r}: nothing on {site} before {as_of}")
            continue

        # Best-looking first, so the per-query budget is spent on the results
        # release rather than on whatever the search engine happened to rank.
        ranked = sorted(
            results, key=lambda r: -_relevance(str(r.get("url") or ""))
        )
        for result in ranked:
            uri = str(result.get("url") or "")
            body = result.get("text") or ""
            if not uri or uri in seen:
                continue
            seen.add(uri)
            if _relevance(uri) < 0:
                notes.append(f"{uri[:60]}: not investor material — skipped")
                continue
            if len(body) < MIN_BODY_CHARS:
                # A links page, not a report. Admitting it would put an index of
                # PDF filenames into the corpus as though it were disclosure.
                notes.append(f"{uri[:60]}: {len(body)} chars — a landing page, skipped")
                continue

            published = _published(result)
            if published is None:
                notes.append(f"{uri[:60]}: undated — cannot place it against as_of")
                continue
            if published > as_of:
                # Belt and braces. The search is already bounded, but a results
                # release published the day after `as_of` contains the answer.
                notes.append(f"{uri[:60]}: published {published}, after as_of")
                continue

            title = str(result.get("title") or phrase)[:120]
            documents[uri] = body
            claims.append(
                Claim(
                    id=f"ir:{ticker}:{len(claims)}",
                    label=f"{title} ({why})",
                    value=None,
                    source=Source(
                        kind=SourceKind.COMPANY_SITE,
                        uri=uri,
                        as_of=published,
                        page_or_section=phrase,
                    ),
                    verbatim_quote=title,
                )
            )

    log.info(
        "ir_documents",
        ticker=ticker,
        site=site,
        documents=len(documents),
        chars=sum(len(b) for b in documents.values()),
        skipped=len(notes),
    )
    return claims, documents, notes


def _published(result: dict) -> date | None:
    for field in ("publishedDate", "published_date", "date"):
        raw = result.get(field)
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None
