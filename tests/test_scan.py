"""The two prose scans, and specifically the ways they are allowed to fail.

Both of these produce structure from text a model wrote, which makes them the
easiest place in the system for an invented sentence to acquire the authority of
a quotation. So most of what is tested here is REJECTION: the unverifiable quote,
the URL that was never supplied, the undated article, the three-quarter sequence
that is too short for a change to be a change. The happy paths are one test each.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from forecaster.llm.client import LLMError
from forecaster.pipeline.e_expect import scan
from forecaster.pipeline.e_expect.perception import MIN_ITEMS

BODY = (
    "Nvidia's datacentre backlog now stretches into next year and the company "
    "has said it expects supply to remain tight. Analysts see no relief before "
    "the second half."
)
QUOTE = "Analysts see no relief before the second half."


class FakeClient:
    """Returns whatever it is handed, or raises. No network, no schema games."""

    def __init__(self, response=None, error: str | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def call(self, prompt, schema=None, variables=None, run_index=0):
        self.calls.append((prompt, variables or {}))
        if self.error:
            raise LLMError(self.error)
        return self.response, {}


def article(url="https://x.com/a", text=BODY, published="2026-07-01"):
    return {"url": url, "title": "Nvidia backlog", "text": text,
            "publishedDate": published}


def scored(url="https://x.com/a", quote=QUOTE, stance="bullish", subject="company"):
    return scan.ScoredArticle(
        subject=subject, stance=stance, conviction=0.8,
        claim="Supply stays tight", quote=quote, url=url,
    )


# ---- perception ---------------------------------------------------------- #


def test_a_scored_article_with_a_real_quote_is_kept():
    client = FakeClient(scan.PerceptionResponse(articles=[scored()]))
    result = scan.score_articles(client, "NVDA", [article()], {"a": BODY})

    assert len(result.reads) == 1
    assert result.reads[0].published == date(2026, 7, 1)
    assert result.reads[0].signed == pytest.approx(0.8)
    assert not result.skipped


def test_an_invented_quote_drops_the_whole_item():
    """The failure this file exists for.

    A paraphrase reads exactly like a quotation, and `v1_reconcile` string-matches
    downstream — so an unverifiable sentence must not survive to be cited.
    """
    invented = "Nvidia told investors the shortage would end by December."
    client = FakeClient(scan.PerceptionResponse(articles=[scored(quote=invented)]))
    result = scan.score_articles(client, "NVDA", [article()], {"a": BODY})

    assert result.reads == []
    assert "not in the article" in result.skipped[0]


def test_a_url_that_was_never_supplied_is_dropped():
    client = FakeClient(
        scan.PerceptionResponse(articles=[scored(url="https://invented.example")])
    )
    result = scan.score_articles(client, "NVDA", [article()], {"a": BODY})

    assert result.reads == []
    assert "not supplied" in result.skipped[0]


def test_an_undated_article_is_dropped():
    """Staleness is half the reading; an item with no date cannot contribute."""
    client = FakeClient(scan.PerceptionResponse(articles=[scored()]))
    result = scan.score_articles(
        client, "NVDA", [article(published="")], {"a": BODY}
    )

    assert result.reads == []
    assert "undated" in result.skipped[0]


def test_a_failed_call_returns_an_empty_reading_rather_than_raising():
    client = FakeClient(error="429 from the cheap tier")
    result = scan.score_articles(client, "NVDA", [article()], {"a": BODY})

    assert result.reads == []
    assert "perception scan failed" in result.skipped[0]
    # And an empty reading must adjust nothing.
    assert result.risk_premium_adjustment()[0] == 0.0
    assert result.stress_multiplier()[0] == 1.0


def test_no_bodies_means_no_call_is_made_at_all():
    client = FakeClient(scan.PerceptionResponse(articles=[]))
    result = scan.score_articles(client, "NVDA", [{"url": "u", "text": ""}], {})

    assert client.calls == []
    assert "no article bodies" in result.skipped[0]


def test_a_one_sided_reading_widens_the_discount_rate_not_the_estimate():
    """The whole point of the perception leg, end to end.

    Unanimity is treated as fragility: the premium goes UP because the market has
    stopped pricing the other outcome. Nothing here touches a driver.
    """
    articles = [article(url=f"https://x.com/{i}") for i in range(MIN_ITEMS + 1)]
    client = FakeClient(
        scan.PerceptionResponse(
            articles=[scored(url=f"https://x.com/{i}") for i in range(MIN_ITEMS + 1)]
        )
    )
    result = scan.score_articles(client, "NVDA", articles, {"a": BODY})

    assert result.crowded("company")
    premium, why = result.risk_premium_adjustment()
    assert premium == pytest.approx(0.005)
    assert "narrow" in why.lower()
    assert result.stress_multiplier()[0] == pytest.approx(1.5)


# ---- the calls ----------------------------------------------------------- #


@dataclass
class FakeTranscript:
    period: str
    published: date
    url: str
    text: str


CALL_TEXT = (
    "Prepared remarks about strategy and long-term positioning. " * 40
    + "Question-and-Answer Session. "
    + "Operator: our first question comes from the line of an analyst. "
    + "We are not breaking out datacentre units this quarter. "
    + "Thank you for the question."
)
CALL_QUOTE = "We are not breaking out datacentre units this quarter."


def transcripts(n=4):
    return [
        FakeTranscript(f"2026Q{i + 1}", date(2026, 1, 1), f"https://c/{i}", CALL_TEXT)
        for i in range(n)
    ]


def change(quote=CALL_QUOTE, kind="withdrawn"):
    return scan.DisclosureChange(
        kind=kind, subject="datacentre units", last_seen="2026Q2",
        what_changed="Stopped giving unit counts after 2026Q2",
        quote=quote, matters_because="The unit series drove the revenue bridge",
    )


def test_fewer_than_three_quarters_is_not_a_sequence():
    """Two points make a difference, not a change. No call is made."""
    client = FakeClient(scan.CallsResponse(changes=[]))
    response, notes = scan.read_calls(client, "NVDA", transcripts(2))

    assert response is None
    assert client.calls == []
    assert "at least three" in notes[0]


def test_a_withdrawal_with_a_real_quote_survives():
    client = FakeClient(scan.CallsResponse(changes=[change()], tone_shift="none"))
    response, notes = scan.read_calls(client, "NVDA", transcripts())

    assert response is not None
    assert len(response.changes) == 1
    assert notes == []


def test_an_invented_call_quote_is_dropped():
    client = FakeClient(
        scan.CallsResponse(changes=[change(quote="Management said demand had halved.")])
    )
    response, notes = scan.read_calls(client, "NVDA", transcripts())

    assert response is not None
    assert response.changes == []
    assert "not in any transcript" in notes[0]


def test_the_quarters_are_sent_oldest_first():
    """A withdrawal is only visible reading forward — you notice the absence
    after seeing the presence."""
    client = FakeClient(scan.CallsResponse(changes=[]))
    scan.read_calls(client, "NVDA", list(reversed(transcripts())))

    quarters = client.calls[0][1]["quarters"]
    assert quarters == "2026Q1, 2026Q2, 2026Q3, 2026Q4"


def test_only_the_qa_half_is_sent():
    """Prepared remarks are written by IR. The Q&A is where a metric gets
    quietly dropped."""
    client = FakeClient(scan.CallsResponse(changes=[]))
    scan.read_calls(client, "NVDA", transcripts(3))

    sent = client.calls[0][1]["transcripts"]
    assert "Prepared remarks about strategy" not in sent
    assert CALL_QUOTE in sent


def test_a_failed_call_scan_degrades_to_a_note():
    client = FakeClient(error="timeout")
    response, notes = scan.read_calls(client, "NVDA", transcripts())

    assert response is None
    assert "call scan failed" in notes[0]


# ---- the block ----------------------------------------------------------- #


def test_withdrawals_lead_the_block():
    response = scan.CallsResponse(
        changes=[change(kind="introduced"), change(kind="withdrawn")]
    )
    block = scan.to_block(response, [])

    assert block.index("[WITHDRAWN]") < block.index("[INTRODUCED]")


def test_nothing_changing_is_stated_as_a_finding_not_as_a_gap():
    block = scan.to_block(scan.CallsResponse(changes=[], tone_shift=""), [])

    assert "nothing changed" in block
    assert "correct answer more often than not" in block


def test_a_missing_reading_says_why():
    block = scan.to_block(None, ["only 2 identifiable quarters"])

    assert "no cross-quarter call reading" in block
    assert "2 identifiable quarters" in block
