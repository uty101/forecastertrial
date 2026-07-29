"""Verification layer 2 — is this quarter even comparable to its own history?

Everything upstream leans on historical patterns: where this company lands
inside its guided range, its median surprise, its margin trend. All of that
assumes the quarters resemble each other. Sometimes they do not, and when they
do not the historical prior is worse than useless — it is confidently wrong in a
specific direction.

**When this fires, lambda collapses.** That is the whole purpose: without it the
system is *most* confident exactly where it is *least* entitled to be, because a
mid-quarter acquisition makes every historical comparison look unusually clean
right up until the print.

One cheap model call. The cost of a false positive is a lost edge on one name;
the cost of a false negative is a confident forecast built on a prior that does
not hold. The prompt is told to be conservative in both directions rather than
to hunt for something to flag.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from forecaster.events import EventLog
from forecaster.llm.client import LLMClient, LLMError
from forecaster.schemas import EventType

log = structlog.get_logger()


class ComparabilityResponse(BaseModel):
    comparable: bool = Field(
        description="True when this quarter can be compared to the company's own "
        "history. A clean quarter is the common case."
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Short labels for what fired, e.g. 'M&A closed mid-quarter', "
        "'53rd week', 'non-GAAP definition changed'.",
    )
    rationale: str = Field(description="One line on what was found, or not found.")


def check(
    client: LLMClient,
    ticker: str,
    period: str,
    as_of,
    events_block: str,
    events: EventLog | None = None,
) -> tuple[str | None, str]:
    """Returns (comparability_flag, rationale).

    The flag is what `f_lambda` reads; None means the quarter is comparable.

    A failed call returns None — treating a broken check as "not comparable"
    would collapse lambda on every run whenever the API hiccuped, which is a
    silent, one-directional accuracy loss that would be very hard to notice.
    The failure is logged and surfaced instead.
    """
    if events:
        events.emit(EventType.NODE_START, "V2_comparability")

    try:
        response, _ = client.call(
            "comparability",
            schema=ComparabilityResponse,
            variables={
                "ticker": ticker,
                "period": period,
                "as_of": as_of.isoformat(),
                "events_block": events_block or "(no filings or events acquired)",
            },
        )
    except LLMError as exc:
        log.warning("comparability_check_failed", error=str(exc))
        if events:
            events.emit(EventType.NODE_FAILED, "V2_comparability", error=str(exc))
        return None, f"comparability check did not run ({exc}) — treated as comparable"

    flag = "; ".join(response.flags) if not response.comparable else None
    if events:
        events.emit(
            EventType.NODE_DONE,
            "V2_comparability",
            comparable=response.comparable,
            flags=response.flags,
        )
    log.info(
        "comparability_checked",
        comparable=response.comparable,
        flags=response.flags,
    )
    return flag, response.rationale
