"""Layer A — acquisition, with hard budgets.

Unbounded research is the main way this design loses the day. "Find everything
available online" has no termination condition, and most of what it would find
is noise for a one-quarter forecast: prior-quarter guidance and peer prints that
have already landed are worth an order of magnitude more than news sentiment.

So every acquirer gets a RANKED target list and a budget. When the budget is
spent it returns what it has and LOGS WHAT IT SKIPPED. Silent truncation reads
as "we covered everything" when you didn't.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import structlog

from forecaster.config import settings
from forecaster.data.loader import Loader
from forecaster.events import EventLog
from forecaster.schemas import Claim, EventType

log = structlog.get_logger()

# Ranked, highest value first. Everything below the line is optional and is the
# first thing dropped when the budget runs out.
FILINGS_PRIORITY = [
    ("8-K", "last quarter's EX-99.1 — the guidance paragraph"),
    ("10-Q", "segment table, non-GAAP reconciliation, share count"),
    ("8-K", "anything filed since the last earnings call"),
    ("10-K", "geographic mix, revenue drivers, buyback authorisation"),
    # --- below here is optional ---
    ("DEF 14A", "comp structure — rarely moves a quarterly forecast"),
]

INDUSTRY_PRIORITY = [
    "peers with the same quarter-end that ALREADY REPORTED this cycle",
    "industry volume and price data",
    "customer or supplier disclosures naming the company",
    "trade press",
]


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

    def by_id(self) -> dict[str, Claim]:
        return {c.id: c for c in self.claims}


def acquire(
    ticker: str, period: str, as_of: date, loader: Loader, events: EventLog
) -> Acquired:
    """A1-A4 in parallel in production; sequential here for determinism.

    Note every call carries `as_of` — sources refuse anything filed later, so a
    leak raises rather than quietly flattering the backtest.
    """
    out = Acquired()

    with events.node("A1_numbers"):
        budget = Budget()
        actuals = loader.actuals(ticker, period, as_of)
        if actuals:
            out.claims.extend(actuals)
            budget.spend(docs=len(actuals))
        out.consensus = loader.consensus(ticker, as_of)
        out.budgets["A1"] = budget.report()
        events.emit(EventType.CLAIM_ADDED, "A1_numbers", n=len(out.claims))

    with events.node("A2_filings"):
        budget = Budget()
        for form, why in FILINGS_PRIORITY:
            if budget.exhausted():
                budget.skip(f"{form}: {why}")
                continue
            found = loader.filings(ticker, as_of, [form], limit=3)
            if found:
                out.claims.extend(found)
                budget.spend(docs=len(found))
        transcript = loader.transcript(ticker, as_of)
        if transcript:
            out.documents[f"transcript:{ticker}:{period}"] = transcript
        out.budgets["A2"] = budget.report()
        if budget.skipped:
            # Never silent. A dropped source must be visible in the manifest.
            log.info("acquisition_truncated", stage="A2", skipped=budget.skipped)

    with events.node("A3_industry"):
        budget = Budget()
        for target in INDUSTRY_PRIORITY:
            if budget.exhausted():
                budget.skip(target)
        out.budgets["A3"] = budget.report()

    with events.node("A4_macro"):
        out.budgets["A4"] = Budget().report()

    return out
