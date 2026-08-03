"""News and industry publications, date-bounded.

This is the only source in the system whose point-in-time story is weak, and it
is worth being blunt about why. A filing carries a `filed` date SEC assigned. A
transcript carries the date the call happened. An article carries whatever date
Exa could infer from the HTML — their own documentation calls `publishedDate`
"an estimate of the creation date, from parsing HTML content".

So the rule here is stricter than elsewhere: a result with NO date is dropped,
never assumed old enough. An undated article is a leak we cannot detect, and one
leaked article about the quarter we are forecasting is worth more to the model
than the entire rest of the corpus.

**Why not a general web search.** Anthropic's `web_search` tool has no
published-date parameter at all, so it returns today's internet for a historical
`as_of`. That is fine on the day and useless for the backtest that fits lambda —
and a lens that cannot be backtested cannot be weighed against one that can.

**Claims from here are PROSE, and deliberately so.** `v1_reconcile` string-
matches every prose quote against its source document, so a fabricated quote
from an article drops the lens that cited it. Of everything in the corpus this
is the likeliest place for a model to invent a sentence that reads perfectly, so
the article body is stored and the quote must be found in it.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import date, datetime
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from forecaster.data.cache import Cache
from forecaster.data.protocol import assert_point_in_time
from forecaster.schemas import Claim, Source, SourceKind

log = structlog.get_logger()

BASE = "https://api.exa.ai"
_MIN_REQUEST_INTERVAL_S = 0.2
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Exa's own vocabulary. "news" for company coverage, "financial report" for the
# research houses and consultancies, "publication" for central banks and papers.
CATEGORY_NEWS = "news"
CATEGORY_REPORT = "financial report"
CATEGORY_PUBLICATION = "publication"


class _TransientExa(RuntimeError):
    """Worth retrying. 4xx is not — a bad key or a spent quota is permanent for
    the run, and retrying it burns the clock on a day where the clock binds."""


class ExaSource:
    name = "exa"
    # Last. This answers questions no filing can, and should never win a call
    # another source can serve from a document the company signed.
    priority = 50

    def __init__(self, api_key: str, cache: Cache) -> None:
        if not api_key:
            raise ValueError("ExaSource needs an API key; set EXA_API_KEY.")
        self.api_key = api_key
        self.cache = cache
        self._client = None
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------ #

    @retry(
        retry=retry_if_exception_type(_TransientExa),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _post(self, path: str, payload: dict[str, Any]) -> dict | None:
        import httpx

        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    headers={"x-api-key": self.api_key}, timeout=60.0
                )
            elapsed = time.monotonic() - self._last_request
            if elapsed < _MIN_REQUEST_INTERVAL_S:
                time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
            self._last_request = time.monotonic()

        response = self._client.post(f"{BASE}/{path}", json=payload)
        if response.status_code in _RETRY_STATUSES:
            raise _TransientExa(f"{response.status_code} from {path}")
        if 400 <= response.status_code < 500:
            log.error(
                "exa_unavailable",
                status=response.status_code, detail=response.text[:200],
            )
            return None
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        as_of: date,
        category: str | None = None,
        domains: list[str] | None = None,
        limit: int = 10,
        lookback_days: int = 120,
    ) -> list[dict]:
        """Results published in the window ending at `as_of`, newest first.

        `lookback_days` is not tidiness. An article from two years ago is
        already fully absorbed into consensus and tells us nothing the Street
        has not had years to price — the same reasoning as the peer-print
        lookback in acquisition.
        """
        start = date.fromordinal(as_of.toordinal() - lookback_days)
        payload: dict[str, Any] = {
            "query": query,
            "numResults": limit,
            "startPublishedDate": f"{start.isoformat()}T00:00:00.000Z",
            "endPublishedDate": f"{as_of.isoformat()}T23:59:59.999Z",
            "contents": {"text": True},
        }
        if category:
            payload["category"] = category
        if domains:
            payload["includeDomains"] = domains

        key = self.cache.key(
            "exa_search", as_of,
            q=query, category=category, domains=sorted(domains or []), limit=limit,
            lookback=lookback_days,
        )
        found = self.cache.fetch(key, lambda: self._post("search", payload))
        results = (found or {}).get("results") or []

        kept = []
        for result in results:
            published = _published(result)
            if published is None:
                # Exa infers the date from HTML and sometimes cannot. Undated
                # means unverifiable, and an unverifiable date is a leak we
                # would never see.
                log.info("exa_undated", url=str(result.get("url"))[:120])
                continue
            assert_point_in_time(published, as_of, f"exa result {result.get('url')}")
            kept.append(result)

        # Persist the bodies so quotes can be verified against them later.
        for result in kept:
            text = (result.get("text") or "").strip()
            if text and result.get("url"):
                self.cache.fetch(
                    self.cache.key("exa_doc", date(2000, 1, 1), uri=result["url"]),
                    lambda text=text: text,
                )
        log.info(
            "exa_search",
            query=query[:70], category=category,
            returned=len(results), kept=len(kept),
        )
        return kept

    def get_document(self, uri: str) -> str | None:
        """The article body, so `verify_citations` has something to match.

        Named to match the SEC source, which is what lets acquisition's existing
        document loop pick these up without knowing which source produced them.
        """
        if not uri.startswith("http"):
            return None
        return self.cache.get(self.cache.key("exa_doc", date(2000, 1, 1), uri=uri))

    def get_news(
        self,
        ticker: str,
        as_of: date,
        query: str,
        category: str | None = CATEGORY_NEWS,
        domains: list[str] | None = None,
        limit: int = 8,
        lookback_days: int = 120,
    ) -> list[Claim] | None:
        """Articles as citable claims, each quoting its own opening sentence.

        The quote is lifted FROM the stored body rather than composed, so it
        verifies by construction and a lens can cite the article immediately
        instead of waiting on an extraction pass.
        """
        results = self.search(
            query, as_of, category=category, domains=domains,
            limit=limit, lookback_days=lookback_days,
        )
        claims = []
        for result in results:
            text = (result.get("text") or "").strip()
            url = result.get("url")
            if not text or not url:
                continue
            published = _published(result)
            claims.append(
                Claim(
                    id=f"exa:{ticker}:{hashlib.sha1(url.encode()).hexdigest()[:12]}",
                    label=str(result.get("title") or url)[:200],
                    value=None,
                    source=Source(
                        kind=SourceKind.NEWS,
                        uri=url,
                        as_of=published,
                        page_or_section=str(result.get("author") or "")[:80] or None,
                    ),
                    verbatim_quote=_opening(text),
                )
            )
        return claims or None

    # ------------------------------------------------------------------ #
    # DataSource protocol — this source answers questions filings cannot.
    # ------------------------------------------------------------------ #

    def get_consensus(self, ticker: str, as_of: date):
        return None

    def get_actuals(self, ticker: str, period: str, as_of: date):
        return None

    def get_guidance(self, ticker: str, as_of: date):
        return None

    def get_filings(self, ticker: str, as_of: date, forms: list[str],
                    limit: int = 10, items: str | None = None):
        return None

    def get_transcript(self, ticker: str, as_of: date):
        return None

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None

    def get_macro(self, series_ids: list[str], as_of: date):
        return None


def _published(result: dict) -> date | None:
    stamp = result.get("publishedDate")
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _opening(text: str, floor: int = 40, ceiling: int = 280) -> str:
    """The article's first sentence, as an exact substring of the body.

    Taken from the text rather than composed, because `verify_citations`
    string-matches the quote against the document — a descriptive quote such as
    "article published 2026-05-20" appears nowhere in the article and would fail
    every news claim, dropping the lens that cited it.

    Scans every sentence end and takes the first that clears `floor`, rather
    than starting the search at `floor`: an article opening with a short
    headline sentence would otherwise have that boundary skipped and return the
    whole window, which is a quote nobody can read and a weaker match.
    """
    flat = re.sub(r"\s+", " ", text).strip()
    window = flat[:ceiling]
    for match in re.finditer(r"[.!?](?=\s|$)", window):
        if match.end() >= floor:
            return window[: match.end()]
    return window
