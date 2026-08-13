"""Layer B — acquisition, with hard budgets.

Unbounded research is the main way this design loses the day. "Find everything
available online" has no termination condition, and most of what it would find
is noise for a one-quarter forecast: prior-quarter guidance and peer prints that
have already landed are worth an order of magnitude more than news sentiment.

So every acquirer gets a RANKED target list and a budget. When the budget is
spent it returns what it has and LOGS WHAT IT SKIPPED. Silent truncation reads
as "we covered everything" when you didn't.

Four acquirers, run in order here for determinism:

    B1 Numbers    XBRL actuals + consensus
    B2 Filings    8-K EX-99.1, 10-Q, transcript — AND THE DOCUMENT TEXT
    B3 Industry   peers and the value chain who ALREADY reported this cycle
    B4 Macro      sector-relevant FRED series, point-in-time

B2 fetching the actual document text is not an optimisation. Citation
verification string-matches every prose quote against its source, so a filing
acquired as a URL with no body means every quote from it fails and every lens
citing it is dropped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import structlog

from forecaster.config import settings
from forecaster.data import exposure, industry, ir_site, segments, transcripts
from forecaster.data.loader import Loader
from forecaster.data.universe import profile
from forecaster.events import EventLog
from forecaster.schemas import Claim, EventType, Source, SourceKind

log = structlog.get_logger()

# Ranked, highest value first. Everything below the line is optional and is the
# first thing dropped when the budget runs out.
# (form, 8-K item filter, why). Item 2.02 is "Results of Operations and
# Financial Condition" — the earnings release, and the only 8-K that carries the
# guidance paragraph, the GAAP-to-non-GAAP reconciliation and the segment table.
# Without the filter this asked for the three most recent 8-Ks, which for NVDA
# were a director change, a shareholder vote and a notes offering.
FILINGS_PRIORITY = [
    ("8-K", "2.02", "the earnings release — guidance, non-GAAP bridge, segments"),
    ("10-Q", None, "segment table, non-GAAP reconciliation, share count"),
    ("8-K", None, "anything filed since the last earnings call"),
    ("10-K", None, "geographic mix, revenue drivers, buyback authorisation"),
    # --- below here is optional ---
    ("DEF 14A", None, "comp structure — rarely moves a quarterly forecast"),
]

INDUSTRY_PRIORITY = [
    "peers with the same quarter-end that ALREADY REPORTED this cycle",
    "industry volume and price data",
    "customer or supplier disclosures naming the company",
    "trade press",
]

# A peer print older than this is already fully in consensus and tells you
# nothing the Street has not had months to absorb.
PEER_LOOKBACK_DAYS = 100


@dataclass
class Budget:
    """Spend it and stop. Dial these down on the day if you're behind."""

    max_docs: int = settings.max_docs_per_source
    max_tokens: int = settings.max_tokens_per_acquire
    deadline_s: int = settings.acquire_deadline_s

    _docs: int = 0
    _tokens: int = 0
    _t0: float = field(default_factory=time.monotonic)
    skipped: list[str] = field(default_factory=list)

    def spend(self, docs: int = 0, tokens: int = 0) -> None:
        self._docs += docs
        self._tokens += tokens

    def exhausted(self) -> bool:
        return (
            self._docs >= self.max_docs
            or self._tokens >= self.max_tokens
            or (time.monotonic() - self._t0) > self.deadline_s
        )

    def skip(self, what: str) -> None:
        self.skipped.append(what)

    def report(self) -> dict:
        return {
            "docs": self._docs,
            "tokens": self._tokens,
            "elapsed_s": round(time.monotonic() - self._t0, 1),
            "skipped": self.skipped,
        }


@dataclass
class Acquired:
    claims: list[Claim] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)
    consensus: object | None = None
    budgets: dict[str, dict] = field(default_factory=dict)

    # Rendered context blocks for the lenses that need more than the corpus.
    peer_block: str = ""
    macro_block: str = ""
    prior_year_block: str = ""
    driver_block: str = ""
    sector: str = "unknown"
    prepared: bool = False

    # The revenue decomposition, read from the filing's XBRL instance. This is
    # what the Drivers lens builds units x ASP on, and until it existed that
    # lens was asked to derive a decomposition from a corpus containing none —
    # unless the company happened to be one of twelve somebody had prepared.
    segment_lines: list = field(default_factory=list)
    segment_notes: list[str] = field(default_factory=list)
    # The last eight earnings calls. The one source whose value is the SEQUENCE
    # rather than the document: what stopped being said is a fact, and it is
    # invisible to anyone reading a single call.
    transcripts: list = field(default_factory=list)
    # Bottom-up market size and this company's share, from peers' filed revenue.
    industry: object | None = None
    industry_block: str = ""
    # Which economies its revenue is exposed to and which input costs its
    # industry buys — each naming the model driver it moves.
    exposure: object | None = None
    exposure_block: str = ""
    value_chain_block: str = ""
    # (region, share of revenue). The geographic split IS the FX translation
    # exposure, which is the input the Mechanical lens could not previously get.
    geo_mix: list = field(default_factory=list)

    # The two series the MODEL needs, as distinct from the evidence store. A
    # lens cites claims; the three-statement model rolls a balance sheet forward
    # and needs the quarterly history, and its EPS denominator needs a share
    # price. Carrying them here is what lets stage 2 be a complete handover
    # rather than a partial one that stage 3 has to top up from the network.
    history: object | None = None
    prices: list | None = None

    def by_id(self) -> dict[str, Claim]:
        return {c.id: c for c in self.claims}


def acquire(
    ticker: str,
    period: str,
    as_of: date,
    loader: Loader,
    events: EventLog,
    macro_source=None,
) -> Acquired:
    """B1-B5. Sequential for determinism; independent in principle.

    Note every call carries `as_of` — sources refuse anything filed later, so a
    leak raises rather than quietly flattering the backtest.
    """
    out = Acquired()
    company = profile(ticker)
    out.sector = company.sector
    out.prepared = company.prepared
    out.driver_block = company.drivers

    # ---- B1: numbers --------------------------------------------------- #
    with events.node("B1_numbers"):
        budget = Budget()
        actuals = loader.actuals(ticker, period, as_of)
        if actuals:
            out.claims.extend(actuals)
            budget.spend(docs=len(actuals))
        out.consensus = loader.consensus(ticker, as_of)

        prior = _prior_year_period(period)
        prior_claims = loader.actuals(ticker, prior, as_of) if prior else None
        if prior_claims:
            out.claims.extend(prior_claims)
            out.prior_year_block = _render_claims(
                f"{ticker} {prior} actuals", prior_claims
            )
            budget.spend(docs=len(prior_claims))
        else:
            # The Drivers lens has no year-on-year base without this, and an
            # empty block reads to the lens as "nothing to compare" rather than
            # as a label that failed to match. `period` must be the FISCAL
            # label, so list what the filer actually has and let the mismatch be
            # obvious instead of silent.
            history = loader.history(ticker, as_of)
            log.warning(
                "prior_year_missing",
                ticker=ticker,
                period=period,
                prior=prior,
                available=history.periods()[-8:] if history else [],
                hint="periods are fiscal labels derived from period end dates",
            )

        out.budgets["B1"] = budget.report()
        events.emit(EventType.CLAIM_ADDED, "B1_numbers", n=len(out.claims))

    # ---- A1b: the series the model rolls forward from ------------------- #
    #
    # Fetched here rather than inside the model so acquisition is a complete
    # handover: everything the analysis needs, gathered once, budgeted, and
    # written to the dossier. The alternative — the model reaching back to the
    # network mid-run — means a stage that was supposed to be replayable is not.
    with events.node("B1b_series"):
        out.history = loader.history(ticker, as_of)
        # Two years of daily bars. The whole series would be 4,000 sessions to
        # answer a question about one quarter's buyback.
        out.prices = loader.prices(ticker, as_of - timedelta(days=730), as_of)
        events.emit(
            EventType.NODE_DONE,
            "B1b_series",
            quarters=out.history.n_quarters() if out.history else 0,
            price_bars=len(out.prices or []),
        )

    # ---- B6: the revenue decomposition --------------------------------- #
    #
    # Deterministic and free: it reads the XBRL instance the filing already
    # published, where each revenue fact carries the axis it is split on. No
    # model call, no name matching, and general to any filer rather than to a
    # list somebody prepared.
    #
    # The prepared paragraph in `universe.py` still wins where one exists —
    # a human's decomposition can name a driver the segment note does not, like
    # units against ASP — but it is now the exception rather than the only path.
    with events.node("B6_segments"):
        found = loader.segments(ticker, as_of)
        out.segment_lines, out.segment_notes = found or ([], [])
        out.geo_mix = segments.geo_mix(out.segment_lines)
        # Deliberately NOT copied into `driver_block`. The table goes into the
        # shared corpus, where all six lenses read it from the cached prefix —
        # Margins needs it for the mix case as much as Drivers needs it to build
        # up. Putting it here as well would pay for the same rows a second time.
        events.emit(
            EventType.NODE_DONE,
            "B6_segments",
            members=len(out.segment_lines),
            regions=len(out.geo_mix),
            rejected=len(out.segment_notes),
        )

    # ---- B7: the earnings calls ---------------------------------------- #
    #
    # Eight quarters, not one. An analyst listens to every call and forms an
    # impression of tone and deflection — real, and the least reproducible thing
    # they do, because it lives in one person's memory of forty hours of audio.
    #
    # An agent cannot be in the room. It can read forty quarters in ninety
    # seconds and apply the identical test to every one, which no analyst can.
    # That is a different instrument rather than a substitute, and it is the one
    # place here where the machine is structurally better rather than faster.
    #
    # The bodies go into `documents` so a lens quoting a call has its quote
    # verified against the transcript, exactly like a filing.
    with events.node("B7_calls"):
        calls = loader.transcripts(ticker, as_of, company=company.name) or []
        out.transcripts = calls
        for call in calls:
            out.claims.append(transcripts.to_claim(call))
            out.documents[call.url] = call.text
        events.emit(
            EventType.NODE_DONE,
            "B7_calls",
            calls=len(calls),
            quarters=[c.period for c in calls],
            with_qa=sum(1 for c in calls if c.has_qa()),
        )

    # ---- B2: filings and their text ------------------------------------ #
    with events.node("B2_filings"):
        budget = Budget()
        # Counted BEFORE the loop, because transcripts have already put bodies
        # in `documents` and the fallback below must trigger on "no REGISTRY
        # filing", not on "no document of any kind". Gating on the latter meant
        # the company-site route never fired for the exact companies it exists
        # for — a Swiss filer with eight transcripts looked well supplied.
        before_filings = len(out.documents)
        for form, items, why in FILINGS_PRIORITY:
            if budget.exhausted():
                budget.skip(f"{form}: {why}")
                continue
            found = loader.filings(ticker, as_of, [form], limit=3, items=items)
            if not found:
                continue
            out.claims.extend(found)
            budget.spend(docs=len(found))

            # THE LINE THAT MAKES CITATION VERIFICATION POSSIBLE. Without the
            # body text, every prose quote from this filing fails verification
            # and every lens that cites it is dropped.
            for claim in found:
                if budget.exhausted():
                    budget.skip(f"body text for {claim.source.uri}")
                    continue
                body = _fetch_document(loader, claim.source.uri)
                if body:
                    out.documents[claim.source.uri] = body
                    budget.spend(tokens=len(body) // 4)

        # THE FALLBACK THAT MAKES THIS WORK OUTSIDE THE US.
        #
        # If no registry answered, go to the company's own site. Every listed
        # company on earth publishes a results release, a half-year report and a
        # presentation on its own domain, in the same three formats, whether or
        # not its country has anything resembling EDGAR.
        #
        # Conditional on the registry having produced NOTHING, not merged with
        # it: where a filing exists it is strictly better evidence, being signed
        # and dated and impossible to edit after the fact.
        if len(out.documents) == before_filings:
            exa = next(
                (s for s in loader.sources if getattr(s, "name", "") == "exa"), None
            )
            site = loader.website(ticker, as_of)
            ir_claims, ir_documents, ir_notes = ir_site.fetch(
                exa, ticker, company.name or ticker, site, as_of
            )
            out.claims.extend(ir_claims)
            out.documents.update(ir_documents)
            budget.spend(
                docs=len(ir_documents),
                tokens=sum(len(b) for b in ir_documents.values()) // 4,
            )
            for note in ir_notes:
                budget.skip(note)
            log.info(
                "ir_fallback",
                ticker=ticker,
                why="no registry filings — using the company's own site",
                site=site,
                documents=len(ir_documents),
            )

        transcript = loader.transcript(ticker, as_of)
        if transcript:
            uri = f"transcript:{ticker}:{period}"
            out.documents[uri] = transcript

        out.budgets["B2"] = budget.report()
        if budget.skipped:
            # Never silent. A dropped source must be visible in the manifest.
            log.info("acquisition_truncated", stage="B2", skipped=budget.skipped)
        events.emit(
            EventType.NODE_DONE, "B2_filings",
            filings=len(out.claims), documents=len(out.documents),
        )

    # ---- B3: industry --------------------------------------------------- #
    with events.node("B3_industry"):
        budget = Budget()
        peer_claims, peer_lines = [], []

        # A curated peer list beats a derived one — it can encode a supplier or
        # a customer that shares no industry code. But it only exists for a
        # company somebody prepared for, and on the day the ticker arrives at
        # 10am. Falling back to SIC means an unprepared company still gets an
        # industry read instead of an empty one.
        peer_tickers = list(company.peers)
        if not peer_tickers:
            peer_tickers = loader.peers(ticker, as_of) or []
            log.info(
                "peers_derived",
                ticker=ticker, n=len(peer_tickers), why="no prepared peer list",
            )

        for peer in peer_tickers:
            if budget.exhausted():
                budget.skip(f"peer {peer}")
                continue
            reported = _peer_recent_actuals(loader, peer, as_of)
            if not reported:
                continue
            peer_claims.extend(reported)
            peer_lines.append(_render_claims(f"{peer} (already reported)", reported))
            # One peer is one unit of work, not one per line item it reported.
            # Counting claims made a twelve-peer industry cost 36 "documents"
            # and spend the whole stage budget before the narrative searches
            # below ever ran.
            budget.spend(docs=1)

        # ---- industry and company narrative ---------------------------- #
        #
        # Peer filings above give the industry's NUMBERS. This gives the reason
        # behind them — a supply constraint, a pricing move, a customer's capex
        # plan — which is the half no balance sheet contains.
        #
        # Both searches are bounded by `as_of` inside the source. An unbounded
        # news search returns today's internet for a historical date, which does
        # not merely add noise: it hands the model the answer.
        sic = loader.sic(ticker, as_of)
        # `industry_name`, not `industry`: the latter is the imported MODULE,
        # and shadowing it here made every non-replay run die at B8 with
        # "'str' object has no attribute 'PeerRevenue'". It survived because
        # every recent run started from a dossier, which skips acquisition
        # entirely — the one code path that a replay can never exercise.
        industry_name = sic[1] if sic else company.sector
        # And it is the SECTOR too, not just a search term. This was fetched,
        # used to build a query, and thrown away — so every company outside the
        # prepared list reached the Macro lens with `sector="unknown"` while its
        # actual industry sat in a local variable one line above. SEC states the
        # industry on the filing; there is no reason to be guessing at it.
        if sic and out.sector == "unknown":
            out.sector = sic[1]
        searches = [
            (f"{industry_name} industry demand pricing outlook", "industry"),
            (f"{ticker} {industry_name} earnings outlook guidance", "company"),
        ]
        # Its own budget, deliberately. Peers are ranked above narrative and
        # should be — a peer's actual print beats any article about the
        # industry — but sharing one budget meant a crowded industry starved
        # the narrative entirely rather than merely outranking it.
        news_budget = Budget()
        for query, what in searches:
            if news_budget.exhausted():
                news_budget.skip(f"{what} news: {query}")
                continue
            found = loader.news(ticker, as_of, query) or []
            for claim in found:
                if news_budget.exhausted():
                    news_budget.skip(f"body text for {claim.source.uri}")
                    continue
                # Same rule as filings: without the body, every quote from this
                # article fails verification and the lens citing it is dropped.
                body = _fetch_document(loader, claim.source.uri)
                if not body:
                    continue
                out.documents[claim.source.uri] = body
                out.claims.append(claim)
                news_budget.spend(docs=1, tokens=len(body) // 4)
            log.info("news_acquired", ticker=ticker, what=what, n=len(found))

        for target in INDUSTRY_PRIORITY[2:]:
            budget.skip(f"not implemented: {target}")
        out.budgets["B3_news"] = news_budget.report()

        out.claims.extend(peer_claims)
        out.peer_block = "\n\n".join(peer_lines)
        if not out.peer_block and peer_tickers:
            out.peer_block = (
                f"(none of {', '.join(peer_tickers)} has reported within "
                f"{PEER_LOOKBACK_DAYS} days of {as_of}. Early in a reporting "
                "cycle this is the correct and common situation.)"
            )
        out.budgets["B3"] = budget.report()
        events.emit(
            EventType.NODE_DONE, "B3_industry",
            peers_checked=len(peer_tickers), peers_with_prints=len(peer_lines),
        )

    # ---- B4: macro ------------------------------------------------------ #
    with events.node("B4_macro"):
        budget = Budget()
        if macro_source is None:
            budget.skip("no macro source configured (FRED_API_KEY unset)")
        else:
            from forecaster.data.fred_source import macro_block as render_macro

            series = macro_source.get_macro(list(company.macro_series), as_of)
            out.macro_block = render_macro(series)
            if series:
                budget.spend(docs=len(series))
                out.claims.extend(_macro_claims(series, as_of))
        out.budgets["B4"] = budget.report()
        events.emit(
            EventType.NODE_DONE, "B4_macro",
            series=len(company.macro_series) if macro_source else 0,
        )

    log.info(
        "acquisition_complete",
        ticker=ticker,
        prepared=company.prepared,
        claims=len(out.claims),
        documents=len(out.documents),
        has_peers=bool(out.peer_block),
        has_macro=bool(out.macro_block),
    )
    # ---- B8: industry size and share ------------------------------------ #
    #
    # The split consensus forecasts around rather than through: is revenue
    # growing because the market is, or because this company is taking share?
    # Built bottom-up from the filed revenue of every SIC peer rather than from
    # a purchased market-size number, which is a consultancy's estimate of a
    # boundary they drew, published on a lag and unauditable.
    with events.node("B8_industry"):
        peer_revenues = []
        for peer in peer_tickers[:14]:
            peer_history = loader.history(peer, as_of)
            if peer_history is None:
                continue
            latest = peer_history.latest_period()
            if latest is None:
                continue
            now = peer_history.get("revenue", latest)
            periods = peer_history.periods()
            index = periods.index(latest)
            ago = (
                peer_history.get("revenue", periods[index - 4])
                if index >= 4
                else None
            )
            if now is not None:
                peer_revenues.append(
                    industry.PeerRevenue(
                        ticker=peer,
                        revenue=now.value,
                        prior_revenue=ago.value if ago else None,
                    )
                )

        own = None
        if out.history is not None:
            latest = out.history.latest_period()
            periods = out.history.periods()
            if latest is not None:
                now = out.history.get("revenue", latest)
                index = periods.index(latest)
                ago = (
                    out.history.get("revenue", periods[index - 4])
                    if index >= 4
                    else None
                )
                if now is not None:
                    own = industry.PeerRevenue(
                        ticker=ticker,
                        revenue=now.value,
                        prior_revenue=ago.value if ago else None,
                    )

        out.industry = industry.build(
            ticker,
            sic[0] if sic else None,
            sic[1] if sic else "",
            own,
            peer_revenues,
        )
        out.industry_block = industry.to_block(out.industry)
        events.emit(
            EventType.NODE_DONE,
            "B8_industry",
            peers_priced=len(peer_revenues),
            share=out.industry.share,
            market_growth=out.industry.market_growth,
        )

    # ---- B9: external exposure ------------------------------------------ #
    #
    # Every series has to name the line it moves. "Copper is up 14%" is a fact
    # about copper; "copper is up 14% and this company buys copper" is a
    # forecast, and the gap between them is where macro commentary lives without
    # ever reaching a number.
    #
    # Geographic exposure is only computable because the segment extractor gives
    # the revenue split. Input costs come from the company's own SIC code, so
    # this works on a ticker nobody prepared for.
    with events.node("B9_exposure"):
        out.exposure = exposure.build(
            ticker, out.geo_mix, sic[0] if sic else None
        )
        wanted = exposure.series_ids(out.exposure)
        changes: dict[str, float] = {}
        if macro_source is not None and wanted:
            series = macro_source.get_macro(wanted, as_of) or {}
            for series_id, points in series.items():
                usable = [p for p in points if p.value is not None]
                if len(usable) >= 2 and usable[0].value:
                    changes[series_id] = usable[-1].value / usable[0].value - 1
            out.exposure = exposure.build(
                ticker, out.geo_mix, sic[0] if sic else None, changes
            )
        out.exposure_block = exposure.to_block(out.exposure)
        events.emit(
            EventType.NODE_DONE,
            "B9_exposure",
            regions=len(out.exposure.geography),
            inputs=len(out.exposure.inputs),
            covered=round(out.exposure.covered, 3),
            unmapped=out.exposure.unmapped_regions,
        )


    return out


# --------------------------------------------------------------------------- #


def _fetch_document(loader: Loader, uri: str) -> str | None:
    """Pull a filing's body text via whichever source can serve it.

    Failure here is not fatal: the claim survives without its body, and its
    quote then correctly counts as unverified rather than passed.
    """
    for source in loader.sources:
        fetch = getattr(source, "get_document", None)
        if fetch is None:
            continue
        try:
            body = fetch(uri)
            if body:
                return body
        except Exception as exc:  # noqa: BLE001
            log.warning("document_fetch_failed", uri=uri, error=str(exc))
    return None


def _peer_recent_actuals(loader: Loader, peer: str, as_of: date) -> list[Claim]:
    """A peer's most recent print, if it landed inside the lookback window.

    Peers are looked up by ticker only — anything in the universe listed as a
    name rather than a ticker (a private or foreign supplier) is skipped rather
    than guessed at.

    The period is READ FROM THE PEER'S OWN HISTORY rather than constructed.
    This function used to generate `f"{as_of.year}Q{q}"` labels and try six of
    them, which cannot match a filer whose fiscal year does not end in December:
    NVDA's quarter ending April 2026 is fiscal 2027Q1, and 2027 was never tried.
    The empty result was then rendered as "none of these peers has reported
    within 100 days, which early in a reporting cycle is correct and common" —
    a bug wearing the costume of a normal answer.
    """
    if not peer.isupper() or " " in peer:
        return []

    history = loader.history(peer, as_of)
    if history is None:
        return []

    period = history.latest_period()
    if period is None:
        return []

    filed = history.filed_for(period)
    if filed is None or filed < as_of - timedelta(days=PEER_LOOKBACK_DAYS):
        # Older than the window: already fully absorbed into consensus, and it
        # tells us nothing the Street has not had months to price.
        return []

    return loader.actuals(peer, period, as_of) or []


def _prior_year_period(period: str) -> str | None:
    """`2026Q3` -> `2025Q3`. The year-on-year base for the Drivers lens."""
    if len(period) >= 6 and period[:4].isdigit() and "Q" in period:
        return f"{int(period[:4]) - 1}{period[4:]}"
    return None


def _render_claims(header: str, claims: list[Claim]) -> str:
    lines = [f"{header}:"]
    for claim in claims:
        value = claim.value if claim.value is not None else "(qualitative)"
        unit = f" {claim.unit}" if claim.unit else ""
        lines.append(f"  - {claim.label}: {value}{unit} (filed {claim.source.as_of})")
    return "\n".join(lines)


def _macro_claims(series: dict, as_of: date) -> list[Claim]:
    """Macro observations as citable claims, so the Macro lens can point at a
    series id rather than asserting a move from memory."""
    claims = []
    for series_id, points in series.items():
        if not points:
            continue
        latest = max(points, key=lambda p: p.date)
        claims.append(
            Claim(
                id=f"fred:{series_id}",
                label=f"FRED {series_id}",
                value=float(latest.value),
                unit="index",
                period=str(latest.date),
                source=Source(
                    kind=SourceKind.MACRO,
                    uri=f"https://fred.stlouisfed.org/series/{series_id}",
                    as_of=as_of,
                ),
                verbatim_quote=(
                    f"{series_id} = {latest.value} on {latest.date} "
                    f"(as published on {as_of})"
                ),
            )
        )
    return claims
