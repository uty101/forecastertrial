"""Layer A — acquisition, with hard budgets.

Unbounded research is the main way this design loses the day. "Find everything
available online" has no termination condition, and most of what it would find
is noise for a one-quarter forecast: prior-quarter guidance and peer prints that
have already landed are worth an order of magnitude more than news sentiment.

So every acquirer gets a RANKED target list and a budget. When the budget is
spent it returns what it has and LOGS WHAT IT SKIPPED. Silent truncation reads
as "we covered everything" when you didn't.

Four acquirers, run in order here for determinism:

    A1 Numbers    XBRL actuals + consensus
    A2 Filings    8-K EX-99.1, 10-Q, transcript — AND THE DOCUMENT TEXT
    A3 Industry   peers and the value chain who ALREADY reported this cycle
    A4 Macro      sector-relevant FRED series, point-in-time

A2 fetching the actual document text is not an optimisation. Citation
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
    """A1-A4. Sequential for determinism; independent in principle.

    Note every call carries `as_of` — sources refuse anything filed later, so a
    leak raises rather than quietly flattering the backtest.
    """
    out = Acquired()
    company = profile(ticker)
    out.sector = company.sector
    out.prepared = company.prepared
    out.driver_block = company.drivers

    # ---- A1: numbers --------------------------------------------------- #
    with events.node("A1_numbers"):
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

        out.budgets["A1"] = budget.report()
        events.emit(EventType.CLAIM_ADDED, "A1_numbers", n=len(out.claims))

    # ---- A2: filings and their text ------------------------------------ #
    with events.node("A2_filings"):
        budget = Budget()
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

        transcript = loader.transcript(ticker, as_of)
        if transcript:
            uri = f"transcript:{ticker}:{period}"
            out.documents[uri] = transcript

        out.budgets["A2"] = budget.report()
        if budget.skipped:
            # Never silent. A dropped source must be visible in the manifest.
            log.info("acquisition_truncated", stage="A2", skipped=budget.skipped)
        events.emit(
            EventType.NODE_DONE, "A2_filings",
            filings=len(out.claims), documents=len(out.documents),
        )

    # ---- A3: industry --------------------------------------------------- #
    with events.node("A3_industry"):
        budget = Budget()
        peer_claims, peer_lines = [], []

        for peer in company.peers:
            if budget.exhausted():
                budget.skip(f"peer {peer}")
                continue
            reported = _peer_recent_actuals(loader, peer, as_of)
            if not reported:
                continue
            peer_claims.extend(reported)
            peer_lines.append(_render_claims(f"{peer} (already reported)", reported))
            budget.spend(docs=len(reported))

        for target in INDUSTRY_PRIORITY[1:]:
            budget.skip(f"not implemented: {target}")

        out.claims.extend(peer_claims)
        out.peer_block = "\n\n".join(peer_lines)
        if not out.peer_block and company.peers:
            out.peer_block = (
                f"(none of {', '.join(company.peers)} has reported within "
                f"{PEER_LOOKBACK_DAYS} days of {as_of}. Early in a reporting "
                "cycle this is the correct and common situation.)"
            )
        out.budgets["A3"] = budget.report()
        events.emit(
            EventType.NODE_DONE, "A3_industry",
            peers_checked=len(company.peers), peers_with_prints=len(peer_lines),
        )

    # ---- A4: macro ------------------------------------------------------ #
    with events.node("A4_macro"):
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
        out.budgets["A4"] = budget.report()
        events.emit(
            EventType.NODE_DONE, "A4_macro",
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
