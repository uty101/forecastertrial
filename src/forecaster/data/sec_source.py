"""SEC — ground truth actuals and filings, point-in-time by construction.

The reason this source is special: every XBRL fact from data.sec.gov carries a
`filed` date. That lets you reconstruct exactly what was knowable on any past
date, which is what makes an honest backtest possible. Most teams silently leak
future data through restated figures and never find out.

Two things that cost people hours and are handled here:

* Revenue is not one tag. Companies moved between `Revenues`,
  `SalesRevenueNet` and `RevenueFromContractWithCustomerExcludingAssessedTax`
  across the ASC 606 transition. Try them in order.

* SEC requires a declared User-Agent (`Name email`). Without it you get 403s
  that look like rate limiting. Rate limit is 10 req/sec.

Everything here returns **GAAP**. Consensus is non-GAAP. Do not mix them — see
`bridge` in the schemas.
"""

from __future__ import annotations

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
from forecaster.data.history import History, build_history
from forecaster.data.lineitems import BY_KEY
from forecaster.data.protocol import assert_point_in_time
from forecaster.schemas import Basis, Claim, Source, SourceKind

log = structlog.get_logger()

SEC_BASE = "https://data.sec.gov"

# SEC publishes a 10 req/sec ceiling. Pace just under it rather than at it —
# the limiter is on their clock, not ours, and a burst that arrives inside the
# same millisecond counts as a burst however evenly we think we spaced it.
_MIN_REQUEST_INTERVAL_S = 0.11

_RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})


class _TransientSEC(RuntimeError):
    """A SEC response worth retrying.

    403 is in this set deliberately. SEC answers a missing User-Agent and a
    breached rate limit with the same status, and the constructor has already
    refused to build without an identity — so by the time we are making requests
    a 403 is almost always the rate limiter.

    Letting it through instead would spend `Loader.FAILURES_BEFORE_TRIP` in
    under a second and trip the circuit breaker on the source that provides
    every actual, every filing and every document body. That does not degrade
    the run, it ends it at "every lens was dropped".
    """

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
SHARE_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
)


class SECSource:
    name = "sec"
    priority = 20  # after a sponsor feed, before nothing — this is the floor

    def __init__(self, identity: str, cache: Cache) -> None:
        if not identity or "@" not in identity:
            raise ValueError(
                "SEC requires an identity like 'Your Name you@example.com'. "
                "Set SEC_IDENTITY in .env or you will get 403s that look like "
                "rate limiting."
            )
        self.identity = identity
        self.cache = cache
        self._client = None
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------ #

    @retry(
        retry=retry_if_exception_type(_TransientSEC),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _http_get(self, url: str, timeout: float | None = None):
        """The single network door of this module: throttled, then retried.

        A 404 returns None rather than raising — a company that has never filed
        a given form is an ordinary outcome, not a failure to retry against.

        The lock is held across the sleep but released before the request, so
        the pacing is global while requests may still overlap in flight. Holding
        it across the GET as well would serialise the source completely.
        """
        import httpx

        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    headers={
                        "User-Agent": self.identity,
                        "Accept-Encoding": "gzip, deflate",
                    },
                    timeout=30.0,
                )
            elapsed = time.monotonic() - self._last_request
            if elapsed < _MIN_REQUEST_INTERVAL_S:
                time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
            self._last_request = time.monotonic()

        response = (
            self._client.get(url, timeout=timeout)
            if timeout is not None
            else self._client.get(url)
        )
        if response.status_code == 404:
            return None
        if response.status_code in _RETRY_STATUSES:
            log.warning("sec_transient", url=url, status=response.status_code)
            raise _TransientSEC(f"{response.status_code} from {url}")
        response.raise_for_status()
        return response

    def _fetch_json(self, url: str) -> dict[str, Any] | None:
        response = self._http_get(url)
        return response.json() if response is not None else None

    def _cik(self, ticker: str) -> str | None:
        """Ticker -> zero-padded 10-digit CIK. Cached forever; it never changes."""
        key = self.cache.key("sec_tickers", date(2000, 1, 1))
        mapping = self.cache.fetch(
            key, lambda: self._fetch_json("https://www.sec.gov/files/company_tickers.json")
        )
        if not mapping:
            return None
        for entry in mapping.values():
            if entry["ticker"].upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        return None

    def _company_facts(self, ticker: str, as_of: date) -> dict[str, Any] | None:
        """One call gets every tag. Cheaper than N companyconcept requests.

        Keyed on a fixed date so one payload serves every `as_of` — the response
        is append-only and `_visible` does the point-in-time filtering. But it
        has to have been FETCHED at or after `as_of` or it is simply missing the
        recent filings, and a payload cached last week makes the current quarter
        look like it does not exist. `fetch_dated` enforces that and nothing
        stricter, so backtests still share one payload per ticker.
        """
        cik = self._cik(ticker)
        if cik is None:
            return None
        key = self.cache.key("sec_facts", date(2000, 1, 1), cik=cik)
        return self.cache.fetch_dated(
            key,
            lambda: self._fetch_json(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json"),
            not_before=as_of,
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _visible(facts: list[dict], as_of: date) -> list[dict]:
        """THE point-in-time filter. Everything else here is plumbing.

        Note this drops restatements filed after `as_of` even though the period
        they describe is historical — which is exactly the subtle leak that
        makes backtests look better than they are.
        """
        out = []
        for fact in facts:
            filed = datetime.strptime(fact["filed"], "%Y-%m-%d").date()
            if filed <= as_of:
                out.append(fact)
        return out

    def _concept(
        self, ticker: str, tags: tuple[str, ...], unit: str, as_of: date
    ) -> list[dict]:
        facts = self._company_facts(ticker, as_of)
        if not facts:
            return []
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        # MERGE across tags, do not take the first that answers.
        #
        # Filers change concepts over time, so coverage is split across the tag
        # list rather than concentrated in one. NVDA has 28 facts under
        # RevenueFromContractWithCustomerExcludingAssessedTax and 276 under
        # Revenues; first-wins returned the 28 and silently discarded sixteen
        # years of revenue, which then read as "this company does not report
        # revenue" rather than as a mapping bug.
        #
        # Earlier tags in the list still win a genuine collision: same concept,
        # same period, two spellings. `_dedupe` resolves that on (start, end).
        merged: list[dict] = []
        seen: set[tuple[str, str]] = set()
        used: list[str] = []
        for tag in tags:
            entries = us_gaap.get(tag, {}).get("units", {}).get(unit, [])
            visible = self._visible(entries, as_of)
            if not visible:
                continue
            used.append(tag)
            for fact in visible:
                stamp = (str(fact.get("start", "")), str(fact["end"]))
                if stamp in seen:
                    continue
                seen.add(stamp)
                # Which tag produced this fact. The merge is lossy by design —
                # one value survives per period — and where two tags disagree
                # about the same period that choice is invisible downstream.
                # Stamping the origin lets the history layer also keep each tag
                # as its own series, so the disagreement is inspectable rather
                # than silently resolved.
                merged.append({**fact, "_tag": tag})
        if merged:
            log.debug("sec_tags_used", ticker=ticker, tags=used, n=len(merged))
        return merged

    def _claim(
        self, ticker: str, fact: dict, label: str, unit: str, cid: str
    ) -> Claim:
        filed = datetime.strptime(fact["filed"], "%Y-%m-%d").date()
        accession = fact.get("accn", "")
        cik = self._cik(ticker) or ""
        uri = (
            f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
            f"{accession.replace('-', '')}/"
        )
        return Claim(
            id=cid,
            label=label,
            value=float(fact["val"]),
            unit=unit,
            period=f"{fact.get('fy')}{fact.get('fp', '')}",
            source=Source(
                kind=SourceKind.XBRL,
                uri=uri,
                as_of=filed,
                accession=accession,
                page_or_section=fact.get("form"),
            ),
            # XBRL is structured data, not prose. The "quote" is the tagged
            # fact itself — machine-verifiable against the same endpoint.
            verbatim_quote=(
                f"{label}={fact['val']} for {fact.get('start', '')}..{fact['end']} "
                f"(form {fact.get('form')}, accn {accession})"
            ),
        )

    # ------------------------------------------------------------------ #
    # DataSource protocol
    # ------------------------------------------------------------------ #

    def get_consensus(self, ticker: str, as_of: date):
        return None  # SEC has no forward estimates. yfinance handles this.

    def get_actuals(self, ticker: str, period: str, as_of: date) -> list[Claim] | None:
        """One quarter, as claims — read out of the same series as the model.

        This used to match `f"{fact['fy']}{fact['fp']}" == period` directly.
        Those fields describe the FILING rather than the fact, so the match was
        wrong in two directions at once: a 10-K's comparatives all carry the
        current year's fy, and a ninety-day quarter reprinted in a 10-K carries
        fp='FY'. It returned a plausible number for the wrong three months.

        Going through `get_history` is not just a fix, it removes the class of
        bug: the quarter this returns and the quarter the three-statement model
        forecasts are now the same object, so they cannot drift apart.
        """
        history = self.get_history(ticker, as_of)
        if history is None:
            return None

        claims: list[Claim] = []
        for key in ("revenue", "eps_diluted", "diluted_shares"):
            observation = history.get(key, period)
            if observation is None:
                continue
            item = BY_KEY[key]
            assert_point_in_time(
                observation.filed, as_of, f"{ticker} {item.label} {period}"
            )
            claims.append(
                Claim(
                    id=f"sec:{ticker}:{period}:{item.label}",
                    label=item.label,
                    value=observation.value,
                    unit=item.unit,
                    period=period,
                    source=Source(
                        kind=SourceKind.XBRL,
                        uri=(
                            f"https://www.sec.gov/Archives/edgar/data/"
                            f"{(self._cik(ticker) or '').lstrip('0')}/"
                            f"{observation.accession.replace('-', '')}/"
                        ),
                        as_of=observation.filed,
                        accession=observation.accession,
                        page_or_section=observation.form,
                    ),
                    verbatim_quote=(
                        f"{item.label}={observation.value} for the quarter ended "
                        f"{observation.period_end} (form {observation.form}, "
                        f"accn {observation.accession}"
                        f"{', derived as FY minus Q1-Q3' if observation.derived else ''})"
                    ),
                )
            )
        return claims or None

    def get_history(
        self, ticker: str, as_of: date, keys: tuple[str, ...] | None = None
    ) -> History | None:
        """Every quarter of every mapped line item, point-in-time.

        The facts were always here — `companyfacts` returns a company's entire
        tagged history in one response, and `get_actuals` was filtering it down
        to a single period and throwing the rest away. This costs no extra
        request: same cached payload, reshaped instead of discarded.
        """
        if not self._company_facts(ticker, as_of):
            return None
        return build_history(
            ticker,
            as_of,
            facts_for=lambda item: self._concept(ticker, item.tags, item.unit, as_of),
            keys=keys,
            cik=self._cik(ticker) or "",
        )

    def _submissions(self, ticker: str, as_of: date) -> dict[str, Any] | None:
        cik = self._cik(ticker)
        if cik is None:
            return None
        key = self.cache.key("sec_subs", as_of, cik=cik)
        return self.cache.fetch(
            key, lambda: self._fetch_json(f"{SEC_BASE}/submissions/CIK{cik}.json")
        )

    def get_sic(self, ticker: str, as_of: date) -> tuple[str, str] | None:
        """(SIC code, description) — the industry, from the ticker alone.

        No lookup table and no prior knowledge of the company, which is the
        whole point: on the day we are handed a ticker at 10am and a hardcoded
        sector map covers whatever we thought to prepare.
        """
        subs = self._submissions(ticker, as_of)
        if not subs or not subs.get("sic"):
            return None
        return str(subs["sic"]), str(subs.get("sicDescription", ""))

    def _ticker_index(self) -> dict[int, tuple[int, str]]:
        """CIK -> (rank, ticker), where rank orders companies by SIZE.

        `company_tickers.json` is published in descending market-cap order —
        Apple at 0, NVIDIA 1, Broadcom 5, Micron 12, AMD 14, Intel 23 — so the
        position in the file is a free size ranking. Without it, peers would
        come back in CIK order, which is registration date and puts a shell
        company ahead of the industry leader.
        """
        key = self.cache.key("sec_tickers", date(2000, 1, 1))
        mapping = self.cache.fetch(
            key,
            lambda: self._fetch_json(
                "https://www.sec.gov/files/company_tickers.json"
            ),
        )
        index: dict[int, tuple[int, str]] = {}
        for rank, entry in (mapping or {}).items():
            cik, position = int(entry["cik_str"]), int(rank)
            # LOWEST rank wins, compared numerically. A company with several
            # listed classes appears once per class, and iteration order is no
            # guide: the file's keys are strings, so `"10337"` comes before
            # `"15"` and taking the first occurrence handed Bank of America the
            # ticker BAC-PL at rank 10337. Every multi-class issuer picked up a
            # preferred share and a meaningless size ranking, which quietly
            # dropped BAC, WFC, C and USB out of JPMorgan's peer set while
            # leaving a plausible list of smaller banks in their place.
            held = index.get(cik)
            if held is None or position < held[0]:
                index[cik] = (position, str(entry["ticker"]))
        return index

    def _ciks_for_sic(self, sic: str, as_of: date, pages: int = 25) -> list[int]:
        """Every filer registered under this SIC code.

        EDGAR's company browse serves this as Atom. The company NAMES in that
        feed are corrupt — SEC's serialiser emits `ARRAY(0x558fd3327a30)` where
        the name should be — but the CIKs are sound, and names come from the
        ticker file anyway.

        **Paginate to exhaustion.** The feed is ordered ALPHABETICALLY, not by
        size or CIK, so a truncated read returns the beginning of the alphabet
        rather than a sample. Stopping at 400 filers gave JPMorgan a peer set of
        Amerant, BOK Financial and Camden National — every name A to C — while
        Bank of America sat on page 0, Citigroup page 1, PNC page 7 and Wells
        Fargo page 10. Wrong in the worst way: a plausible list of real banks,
        none of them the comparable ones.

        Exhausting even the most crowded code is cheap. SIC 6021, national
        commercial banks, is 1,057 filers over 11 pages and reads in about 15
        seconds — once, then cached.

        A note on point-in-time: this returns membership as it stands TODAY, not
        as of the date requested, so a company that listed after `as_of` can
        appear. The leak is bounded rather than absent — every figure we then
        pull for that peer is filtered by `as_of`, so a company with no filings
        yet contributes nothing. Worth knowing rather than worth blocking on.
        """
        key = self.cache.key("sec_sic_members", as_of, sic=sic)

        def produce() -> list[int] | None:
            found: list[int] = []
            seen: set[int] = set()
            for page in range(pages):
                response = self._http_get(
                    "https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&SIC={sic}&type=10-K&dateb=&owner=include"
                    f"&count=100&start={page * 100}&output=atom",
                    # browse-edgar is a legacy CGI endpoint and is far slower
                    # than data.sec.gov. A crowded code — SIC 6021, national
                    # commercial banks, runs to hundreds of filers — blew the
                    # 30s default and lost the peer set for every bank.
                    timeout=90.0,
                )
                if response is None:
                    break
                ciks = [int(m) for m in re.findall(r"<cik>(\d+)</cik>", response.text)]
                fresh = [c for c in ciks if c not in seen]
                seen.update(fresh)
                found.extend(fresh)
                if len(ciks) < 100:
                    break
            return found or None

        return self.cache.fetch(key, produce) or []

    def get_peers(self, ticker: str, as_of: date, limit: int = 12) -> list[str] | None:
        """Listed companies sharing this company's SIC code, largest first.

        Replaces a hardcoded peer table that could only work for companies
        somebody thought to prepare. Everything here derives from the ticker:
        SEC supplies the SIC, EDGAR supplies the members, and the ticker file
        supplies both the symbol and the size ordering.

        Unlisted filers are dropped — a private filer has no ticker, and every
        downstream lookup is keyed on one.
        """
        sic = self.get_sic(ticker, as_of)
        if sic is None:
            return None

        index = self._ticker_index()
        own = int(self._cik(ticker) or 0)
        ranked = sorted(
            index[cik]
            for cik in self._ciks_for_sic(sic[0], as_of)
            if cik in index and cik != own
        )
        peers = [symbol for _, symbol in ranked[:limit]]
        log.info(
            "peers_by_sic",
            ticker=ticker, sic=sic[0], industry=sic[1], found=len(peers),
        )
        return peers or None

    def _exhibits(self, cik: str, accession: str) -> list[tuple[str, str]]:
        """(exhibit type, filename) for one accession, from the filing index.

        `index.json` looks like the obvious source and is not: its `type` field
        carries an ICON NAME — every row reads `text.gif` — and never the
        document type. The filing index PAGE is where EDGAR publishes the
        Document Format Files table, and it is the only place `EX-99.1` appears
        as a label.

        Cached on a fixed date because a filed accession never changes.
        """
        naked = accession.replace("-", "")
        key = self.cache.key("sec_index", date(2000, 1, 1), accession=accession)

        def produce() -> list[list[str]] | None:
            response = self._http_get(
                f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                f"{naked}/{accession}-index.html"
            )
            if response is None:
                return None
            rows: list[list[str]] = []
            for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", response.text):
                cells = [
                    _strip_html(cell)
                    for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
                ]
                # seq | description | document | type | size
                if len(cells) >= 4 and cells[2] and cells[3]:
                    # The document cell can carry a trailing " iXBRL" marker.
                    rows.append([cells[3], cells[2].split()[0]])
            return rows or None

        return [(row[0], row[1]) for row in (self.cache.fetch(key, produce) or [])]

    def get_guidance(self, ticker: str, as_of: date):
        # Guidance lives in 8-K EX-99.1 prose, not XBRL. The acquisition layer
        # pulls the exhibit; extraction is an LLM job, not this source's.
        return None

    def get_filings(
        self,
        ticker: str,
        as_of: date,
        forms: list[str],
        limit: int = 10,
        items: str | None = None,
    ) -> list[Claim] | None:
        cik = self._cik(ticker)
        if cik is None:
            return None
        subs = self._submissions(ticker, as_of)
        if not subs:
            return None

        recent = subs.get("filings", {}).get("recent", {})
        rows = zip(
            recent.get("form", []),
            recent.get("filingDate", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            recent.get("items", []),
            strict=False,
        )
        claims: list[Claim] = []
        seen = 0
        for form, filed_str, accession, doc, filed_items in rows:
            if form not in forms:
                continue
            # A large filer publishes many 8-Ks a quarter and the earnings
            # release is only one of them: NVDA's three most recent are a
            # director change (5.02), a shareholder vote (5.07) and a notes
            # offering. Asking for the latest three 8-Ks reliably returns none
            # of the earnings releases, so the guidance paragraph, the non-GAAP
            # bridge and the segment table were all absent from the corpus while
            # the acquisition log reported three 8-Ks acquired.
            if items and items not in (filed_items or ""):
                continue
            filed = datetime.strptime(filed_str, "%Y-%m-%d").date()
            if filed > as_of:
                continue  # not knowable yet
            kind = (
                SourceKind.FILING_8K
                if form.startswith("8-K")
                else SourceKind.FILING_10Q
            )
            folder = (
                f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                f"{accession.replace('-', '')}"
            )
            claims.append(
                Claim(
                    id=f"sec:{ticker}:{accession}",
                    label=f"{form} filed {filed_str}",
                    value=None,
                    source=Source(
                        kind=kind,
                        uri=f"{folder}/{doc}",
                        as_of=filed,
                        accession=accession,
                    ),
                    verbatim_quote=f"{form} filed {filed_str}, accession {accession}",
                )
            )

            # AN 8-K's primary document is a COVER PAGE. It says little beyond
            # "Exhibit 99.1 is furnished herewith"; the earnings release — the
            # guidance paragraph, the GAAP-to-non-GAAP reconciliation and the
            # segment table — is a separate exhibit file in the same folder.
            # Acquiring only the primary document meant the Guidance lens read a
            # cover page, every quote it produced failed citation verification,
            # and the highest-value target in the whole acquisition layer was
            # dropped without a word.
            #
            # Only 8-Ks are indexed. A 10-Q's exhibits are certifications, which
            # cost a request each and carry nothing a forecast can use.
            if form.startswith("8-K"):
                for exhibit_type, filename in self._exhibits(cik, accession):
                    if not exhibit_type.startswith("EX-99"):
                        continue
                    claims.append(
                        Claim(
                            id=f"sec:{ticker}:{accession}:{exhibit_type}",
                            label=f"{form} {exhibit_type} filed {filed_str}",
                            value=None,
                            source=Source(
                                kind=kind,
                                uri=f"{folder}/{filename}",
                                as_of=filed,
                                accession=accession,
                                page_or_section=exhibit_type,
                            ),
                            verbatim_quote=(
                                f"{exhibit_type} to {form} filed {filed_str}, "
                                f"accession {accession}"
                            ),
                        )
                    )

            # `limit` counts FILINGS, not claims — otherwise attaching exhibits
            # would silently halve how far back the acquisition reaches.
            seen += 1
            if seen >= limit:
                break
        return claims or None

    def get_document(self, uri: str) -> str | None:
        """Filing body text, stripped to plain prose.

        This is what makes citation verification possible: `verify_citations`
        string-matches every quote against its source document, so a filing
        acquired as a bare URL means every quote from it fails and every lens
        citing it is dropped. Cached forever — a filed document never changes.
        """
        if not uri.startswith("https://www.sec.gov/"):
            return None

        key = self.cache.key("sec_doc", date(2000, 1, 1), uri=uri)

        def produce() -> str | None:
            response = self._http_get(uri)
            return _strip_html(response.text) if response is not None else None

        try:
            return self.cache.fetch(key, produce)
        except Exception as exc:  # noqa: BLE001
            log.warning("sec_document_failed", uri=uri, error=str(exc))
            return None

    def get_transcript(self, ticker: str, as_of: date):
        return None  # Motley Fool / Kaggle dump

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        return None  # FRED

    def get_macro(self, series_ids: list[str], as_of: date):
        return None  # FRED


def _strip_html(html: str) -> str:
    """HTML to plain text, preserving the sentences quotes are matched against.

    Deliberately conservative: entities are decoded and tags removed, but words
    and punctuation are left exactly as filed. `_normalise` in the reconciler
    handles curly quotes and non-breaking spaces at match time, so anything
    "tidied" here would be tidied twice and could break an otherwise correct
    quote.
    """
    import html as html_mod
    import re

    # Script and style bodies are not prose and would pollute the match space.
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    # Block-level tags become spaces so words either side don't fuse together.
    text = re.sub(r"(?i)<(br|/p|/div|/tr|/td|/h[1-6])[^>]*>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html_mod.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


BASIS = Basis.GAAP  # everything this module returns
