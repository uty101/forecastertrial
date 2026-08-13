"""Earnings call transcripts — the source I said did not exist.

All six adapters return None from `get_transcript`, so the conclusion was that
transcripts are out of reach. They are not: every company holds a public call and
four publishers carry the full text within a day. The tests here are about the
two things that make a SEQUENCE of them usable rather than a pile.
"""

from __future__ import annotations

from datetime import date

from forecaster.data import transcripts as T

AS_OF = date(2026, 8, 4)
LONG = "Operator: Good afternoon. " + ("Thank you for the question. " * 900)


def _result(url: str, title: str, text: str, published: str) -> dict:
    # The ticker is in the URL because it is in real transcript URLs —
    # `fool.com/.../nvidia-nvda-q1-2027-earnings-call-transcript` — and because
    # `from_results` now checks that a transcript is actually THIS company's.
    # A search for NESN.SW was returning NESR's and ZOZO's calls, and every
    # quote from them verified, because the words really were in the document.
    return {
        "url": f"{url}-nvda", "title": title, "text": text,
        "publishedDate": published,
    }


def test_the_quarter_is_read_from_the_title_not_the_publication_date():
    """A piece published in May about Q1 is legitimate; one published in May
    about Q2 is a leak. They are indistinguishable by date alone."""
    assert T.quarter_of("NVIDIA (NVDA) Q1 2027 Earnings Call Transcript") == "2027Q1"
    assert T.quarter_of("fool.com/.../nvidia-nvda-q4-2026-earnings") == "2026Q4"
    assert T.quarter_of("Acme third quarter 2025 results call") == "2025Q3"
    assert T.quarter_of("Acme announces a new chief financial officer") is None


def test_a_news_write_up_about_the_call_is_not_the_call():
    """Length is the discriminator that works. A write-up quoting the CEO runs a
    few thousand characters; the call runs forty thousand, and no keyword test
    separates them as reliably."""
    assert T.looks_like_transcript("x/transcript", "Q1 call transcript", LONG)
    assert not T.looks_like_transcript("x/news", "Nvidia beats", "short story")


def test_a_transcript_published_after_the_lock_date_is_refused():
    """Exa is asked for a bounded window and the bound is on an INFERRED date.
    Checking again costs nothing, and a transcript from after the lock date is
    the answer to the question being asked."""
    found = T.from_results(
        "NVDA",
        [_result("u/q1-2027", "Q1 2027 transcript", LONG, "2026-09-01")],
        AS_OF,
    )

    assert found == []


def test_one_transcript_per_quarter():
    """Four publishers carry the same call. Reading all four costs four times
    the tokens for the same words."""
    found = T.from_results(
        "NVDA",
        [
            _result("fool/q1-2027", "Q1 2027 transcript", LONG, "2026-05-20"),
            _result("investing/q1-2027", "Q1 2027 transcript", LONG, "2026-05-21"),
        ],
        AS_OF,
    )

    assert len(found) == 1


def test_something_with_no_identifiable_quarter_is_dropped():
    """The whole value is the sequence — a number given for six quarters and
    withheld in the seventh. A conference-call ANNOUNCEMENT is long enough to
    pass the length test and is not a transcript of anything."""
    found = T.from_results(
        "NVDA",
        [_result("u/announce", "NVIDIA sets conference call date", LONG, "2026-07-29")],
        AS_OF,
    )

    assert found == []


def test_the_qa_section_is_detected_because_it_is_the_half_that_matters():
    """Prepared remarks are written by IR and say what the company chose to say.
    The Q&A is where someone has to answer a question they did not choose."""
    with_qa = T.Transcript("T", "2027Q1", AS_OF, "u", "t",
                           "...we'll now begin the question and answer session...")
    without = T.Transcript("T", "2027Q1", AS_OF, "u", "t", "prepared remarks only")

    assert with_qa.has_qa()
    assert not without.has_qa()


def test_the_claim_quotes_the_call_itself_so_it_verifies():
    """`v1_reconcile` string-matches every prose quote against its source, so a
    descriptive quote appears nowhere in the document and drops the lens."""
    transcript = T.Transcript("T", "2027Q1", AS_OF, "u", "t", LONG)

    claim = T.to_claim(transcript)

    assert claim.verbatim_quote in " ".join(LONG.split())
    assert claim.period == "2027Q1"


def test_transcripts_come_back_newest_first():
    found = T.from_results(
        "NVDA",
        [
            _result("u/q3-2026", "Q3 2026 transcript", LONG, "2025-11-23"),
            _result("u/q1-2027", "Q1 2027 transcript", LONG, "2026-05-20"),
        ],
        AS_OF,
    )

    assert [t.period for t in found] == ["2027Q1", "2026Q3"]


def test_another_companys_call_is_not_this_companys_call():
    """The bug this check exists for, and it is the worst kind of silent one.

    A search for `NESN.SW` returned earnings calls for NESR (National Energy
    Services Reunited), NTWK and ZOZO. Seven other companies' transcripts went
    into the corpus as Nestlé's, and every quote lifted from them would pass
    citation verification — because the words really are in the document. The
    provenance chain was intact and pointed at the wrong company.
    """
    other = _result(
        "insidermonkey.com/national-energy-services-reunited-nesr/q1-2026",
        "National Energy Services Reunited Corp (NESR) Q1 2026 Earnings Call",
        LONG,
        "2026-05-20",
    )
    assert T.from_results("NESN.SW", [other], AS_OF, company="Nestle S.A.") == []


def test_the_company_name_alone_is_enough_when_the_ticker_is_absent():
    """Most publishers title a piece "Nestle S.A. Half Year Earnings Call" with
    no ticker anywhere in it. Requiring both would reject almost everything."""
    theirs = {
        "url": "fool.com/nestle-half-year-2026-earnings-call-transcript",
        "title": "Nestle S.A. Q2 2026 Earnings Call Transcript",
        "text": LONG,
        "publishedDate": "2026-07-24",
    }
    found = T.from_results("NESN.SW", [theirs], AS_OF, company="Nestle S.A.")

    assert [t.period for t in found] == ["2026Q2"]


def test_a_legal_suffix_is_not_evidence_of_identity():
    """"Group", "Holdings" and "plc" match half the market. Matching on them
    would readmit exactly the confusion this check removes."""
    assert not T.is_this_company(
        "NESN.SW", "Nestle Group Holdings plc",
        "insidermonkey.com/acme-group-holdings/q1", "Acme Group Holdings plc Q1",
    )
