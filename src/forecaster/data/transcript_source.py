"""Earnings call transcripts — the one thing filings do not contain.

Checked against EDGAR before building this: of NVDA, AMD, MSFT, AAPL, TSLA,
COST, ORCL and AVGO, **not one files a transcript**. Every one furnishes the
press release as EX-99.1 and some add a second exhibit (NVDA a CFO commentary,
AMD earnings slides), but the call itself is never filed. It is not required to
be — Regulation FD is satisfied by webcasting publicly, so the transcript
belongs to whoever transcribes it.

So what this source buys, precisely, is **the Q&A**: analysts pushing on the
guidance and management qualifying it. The guidance numbers, the non-GAAP bridge
and the segment table are already in the exhibits the SEC source pulls.

**Why an API and not a scraper.** The obvious free route is Motley Fool, whose
robots.txt permits the transcript path. It fails on discovery rather than on
fetching: the URL is
`/earnings/call-transcripts/<date>/<company-slug>-<ticker>-q<n>-<fy>-earnings[-call]-transcript/`,
and both the slug suffix and the company slug vary per filer. Constructing them
worked for NVDA and returned 404 for AMD, MSFT and AAPL. That is the failure
mode that matters here — it works for the company you tested and breaks at 10am
on a company you have never seen. An API takes `(ticker, year, quarter)` and has
no discovery step.

Point-in-time is enforced on the `date` the API returns, not on our own idea of
when the call happened. A transcript published after `as_of` is a leak in the
most direct possible way: it contains the answer.
"""

from __future__ import annotations

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

log = structlog.get_logger()

BASE = "https://api.api-ninjas.com/v1"

# Politeness, and the same shape as the SEC source so the two behave alike.
_MIN_REQUEST_INTERVAL_S = 0.25
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# The developer tier carries five years of transcript text, which is ~20
# quarters per company — enough for a 200-case backtest across ten names.
# Anything older comes back empty rather than erroring, so a deep backtest
# degrades by losing the lens rather than by crashing.


class _TransientTranscript(RuntimeError):
    """A response worth retrying. 401/403 are deliberately NOT in this set —
    a bad key is a configuration error and retrying it just burns the clock."""


class TranscriptSource:
    name = "transcripts"
    # Below SEC and yfinance: this answers exactly one method and should never
    # win a call another source can serve.
    priority = 40

    def __init__(self, api_key: str, cache: Cache) -> None:
        if not api_key:
            raise ValueError(
                "TranscriptSource needs an API key. Set API_NINJAS_KEY, or leave "
                "it unset and the CLI will simply not register this source."
            )
        self.api_key = api_key
        self.cache = cache
        self._client = None
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------ #

    @retry(
        retry=retry_if_exception_type(_TransientTranscript),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(self, path: str, **params: Any) -> Any | None:
        import httpx

        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    headers={"X-Api-Key": self.api_key}, timeout=30.0
                )
            elapsed = time.monotonic() - self._last_request
            if elapsed < _MIN_REQUEST_INTERVAL_S:
                time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
            self._last_request = time.monotonic()

        response = self._client.get(f"{BASE}/{path}", params=params)
        if response.status_code == 404:
            return None
        if response.status_code in _RETRY_STATUSES:
            raise _TransientTranscript(f"{response.status_code} from {path}")

        # Anything else in the 4xx range means this source cannot answer: a bad
        # key, or a plan that does not include the endpoint. Both are permanent
        # for the run, and neither should raise — a raising source burns the
        # Loader's three-failure budget and trips the breaker, turning "no
        # transcripts" into a dead source. Log the server's own words once and
        # return absence.
        #
        # Note the entitlement case arrives as 400, not 402 or 403: a free
        # api-ninjas key returns `{"error": "This endpoint is available to
        # premium subscribers only."}` with a 400. Handling only 401/403 let it
        # escape as an HTTPStatusError.
        if 400 <= response.status_code < 500:
            log.error(
                "transcript_source_unavailable",
                status=response.status_code,
                path=path,
                detail=response.text[:200],
            )
            return None

        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------ #

    def available(self, ticker: str, as_of: date) -> list[dict]:
        """Every transcript published on or before `as_of`, newest first.

        Uses the search endpoint rather than guessing which fiscal quarter was
        most recently reported. The fiscal label a vendor uses need not match the
        one we derive from period end dates, and a mismatch would silently return
        nothing — the same class of bug as the calendar-vs-fiscal one that made
        peer reads come back empty.
        """
        key = self.cache.key("transcript_list", as_of, ticker=ticker)
        rows = self.cache.fetch(
            key,
            lambda: self._get(
                "earningstranscriptsearch",
                ticker=ticker,
                start_date="2000-01-01",
                end_date=as_of.isoformat(),
                limit=200,
            ),
        )
        if not rows:
            return []
        dated = [r for r in rows if r.get("date")]
        return sorted(dated, key=lambda r: r["date"], reverse=True)

    def get_transcript(self, ticker: str, as_of: date) -> str | None:
        """The most recent call transcript knowable at `as_of`."""
        rows = self.available(ticker, as_of)
        if not rows:
            log.info("no_transcript", ticker=ticker, as_of=as_of.isoformat())
            return None
        latest = rows[0]
        return self.get_quarter(
            ticker, int(latest["year"]), int(latest["quarter"]), as_of
        )

    def get_quarter(
        self, ticker: str, year: int, quarter: int, as_of: date, qa_only: bool = False
    ) -> str | None:
        """One specific quarter's transcript, point-in-time checked.

        The published date comes from the API rather than from us. A transcript
        dated after `as_of` is the most direct leak available — it contains the
        result we are forecasting — so this raises rather than filtering, in
        line with every other source.
        """
        key = self.cache.key(
            "transcript", as_of, ticker=ticker, year=year, q=quarter, qa=qa_only
        )

        def produce():
            payload = self._get(
                "earningstranscript",
                ticker=ticker,
                year=year,
                quarter=quarter,
                **({"qa_only": "true"} if qa_only else {}),
            )
            return payload or None

        payload = self.cache.fetch(key, produce)
        if not payload:
            return None

        published = payload.get("date")
        if published:
            assert_point_in_time(
                datetime.strptime(published, "%Y-%m-%d").date(),
                as_of,
                f"{ticker} {year}Q{quarter} transcript",
            )

        text = (payload.get("transcript") or "").strip()
        if not text:
            # The developer tier returns the row without body text for calls
            # outside its five-year window. Say so — an empty string would read
            # downstream as "this call had nothing in it".
            log.info(
                "transcript_empty", ticker=ticker, year=year, quarter=quarter,
                why="outside the tier's history window, or not transcribed",
            )
            return None
        return text

    # ------------------------------------------------------------------ #
    # DataSource protocol — this source answers exactly one question.
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

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None

    def get_macro(self, series_ids: list[str], as_of: date):
        return None
