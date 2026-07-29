"""The reconciler is the highest-value component in the repo, so it gets the
most tests. Each one encodes a real failure mode, not a hypothetical."""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.pipeline.v1_reconcile import (
    check_arithmetic,
    drop_failed,
    reconcile_lens,
    verify_citation,
    verify_citations,
)
from forecaster.schemas import Basis, Claim, LensName, LensOutput, Source, SourceKind

# --------------------------------------------------------------------------- #
# arithmetic
# --------------------------------------------------------------------------- #

CLEAN = dict(
    revenue=10_000.0,
    gross_margin=0.60,
    opex=3_000.0,
    tax_rate=0.20,
    shares=1_000.0,
    other_income=0.0,
)


def test_consistent_eps_passes():
    # (10000*0.6 - 3000) * 0.8 / 1000 = 2.40
    result = check_arithmetic(**CLEAN, claimed_eps=2.40)
    assert result.ok, result.errors


def test_inconsistent_eps_is_caught():
    result = check_arithmetic(**CLEAN, claimed_eps=3.10)
    assert not result.ok
    assert "does not reconcile" in result.errors[0]


def test_rounding_within_tolerance_survives():
    result = check_arithmetic(**CLEAN, claimed_eps=2.42)
    assert result.ok


def test_units_error_is_caught_as_growth_anomaly():
    """The one that will actually bite you: thousands reported as millions.

    The arithmetic is internally consistent, so only the YoY sanity band catches
    it. This is why that check exists.
    """
    result = check_arithmetic(
        revenue=10_000_000.0,
        gross_margin=0.60,
        opex=3_000_000.0,
        tax_rate=0.20,
        shares=1_000.0,
        claimed_eps=2400.0,
        revenue_prior_year=9_500.0,
    )
    assert not result.ok
    assert any("units error" in e for e in result.errors)


def test_percent_supplied_instead_of_fraction():
    result = check_arithmetic(**{**CLEAN, "gross_margin": 60.0}, claimed_eps=2.40)
    assert not result.ok
    assert any("outside [0,1]" in e for e in result.errors)


def test_segments_must_sum_to_total():
    result = check_arithmetic(
        **CLEAN, claimed_eps=2.40, segment_revenues=[4_000.0, 3_000.0]
    )
    assert not result.ok
    assert any("segments sum to" in e for e in result.errors)


def test_zero_shares_fails_fast():
    result = check_arithmetic(**{**CLEAN, "shares": 0.0}, claimed_eps=2.40)
    assert not result.ok


# --------------------------------------------------------------------------- #
# citations
# --------------------------------------------------------------------------- #

SOURCE = Source(
    kind=SourceKind.FILING_8K,
    uri="https://sec.gov/x/8k.htm",
    as_of=date(2026, 5, 28),
)


def _claim(quote: str, cid: str = "c1") -> Claim:
    return Claim(
        id=cid,
        label="Q3 revenue guidance",
        value=44_000.0,
        unit="USD_millions",
        source=SOURCE,
        verbatim_quote=quote,
    )


DOC = (
    "For the third quarter, we expect revenue to be $44.0 billion, "
    "plus or minus 2 percent. GAAP and non‑GAAP gross margins are "
    "expected to be 71.8 percent and 72.0 percent respectively."
)


def test_exact_quote_verifies():
    assert verify_citation(_claim("we expect revenue to be $44.0 billion"), DOC)


def test_curly_quotes_and_nbsp_do_not_break_matching():
    """Filings are full of typographic junk. Naive matching fails on all of it
    and you lose an hour thinking the model hallucinated a correct quote."""
    doc = "For the third quarter, we expect revenue to be $44.0 billion — plus or minus 2%."
    assert verify_citation(_claim("we expect revenue to be $44.0 billion - plus"), doc)


def test_fabricated_quote_fails():
    assert not verify_citation(_claim("we expect revenue to be $52.0 billion"), DOC)


def test_missing_source_document_counts_as_failed():
    """Absence of evidence is not evidence."""
    verified, failed = verify_citations([_claim("anything")], documents={})
    assert verified == [] and failed == ["c1"]


def test_verify_citations_splits_correctly():
    good = _claim("plus or minus 2 percent", "good")
    bad = _claim("we are raising full-year guidance", "bad")
    verified, failed = verify_citations([good, bad], {SOURCE.uri: DOC})
    assert verified == ["good"] and failed == ["bad"]


# --------------------------------------------------------------------------- #
# dropping
# --------------------------------------------------------------------------- #


def _lens(name: LensName, eps: float | None = 2.4, claims: list[str] | None = None):
    return LensOutput(
        lens=name,
        eps=eps,
        basis=Basis.NON_GAAP,
        reasoning="x",
        claim_ids=claims if claims is not None else ["c1"],
        confidence=0.7,
    )


def test_failed_lens_is_dropped_with_a_reason():
    bad = reconcile_lens(
        _lens(LensName.MARGINS),
        check_arithmetic(**CLEAN, claimed_eps=9.99),
        failed_claim_ids=[],
    )
    good = reconcile_lens(_lens(LensName.GUIDANCE), None, failed_claim_ids=[])

    kept, dropped = drop_failed([bad, good])

    assert [k.lens for k in kept] == [LensName.GUIDANCE]
    assert "margins" in dropped
    assert "does not reconcile" in dropped["margins"]


def test_lens_citing_nothing_cannot_be_constructed():
    """A lens with no evidence is the failure mode the provenance design exists
    to prevent — and it is caught at construction, not at reconciliation.

    The reconciler keeps its own check as defence in depth, but this is the
    guarantee that actually holds: an uncited estimate is unrepresentable.
    """
    with pytest.raises(Exception) as err:
        LensOutput(
            lens=LensName.FORENSICS,
            eps=2.4,
            basis=Basis.NON_GAAP,
            reasoning="x",
            claim_ids=[],
            confidence=0.7,
        )
    assert "at least 1 item" in str(err.value)


def test_lens_with_no_estimate_is_dropped():
    lens = reconcile_lens(_lens(LensName.MACRO, eps=None), None, [])
    _, dropped = drop_failed([lens])
    assert "macro" in dropped


def test_claim_cannot_be_built_without_a_quote():
    with pytest.raises(Exception):
        Claim(id="x", label="l", value=1.0, unit="USD", source=SOURCE, verbatim_quote="")


def test_numeric_claim_requires_a_unit():
    with pytest.raises(Exception):
        Claim(id="x", label="l", value=1.0, source=SOURCE, verbatim_quote="q")
