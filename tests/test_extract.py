"""Guidance extraction — the one step that needs a model.

Guidance is the strongest single predictor of the coming print and it lives in
prose rather than XBRL, so a model reads it. Everything here guards the gap
between "the model returned a number" and "the company said that number".
"""

from __future__ import annotations

from forecaster.pipeline.extract import ExtractedGuide, _rescale
from forecaster.pipeline.run import _unique_guides
from forecaster.schemas import Basis, Guidance

QUOTE = "Revenue is expected to be $91.0 billion, plus or minus 2%."


def guide(**kw) -> ExtractedGuide:
    base = dict(metric="revenue", period="Q2 FY2027", quote=QUOTE)
    return ExtractedGuide(**{**base, **kw})


def test_revenue_is_rescaled_using_the_sentences_own_units():
    """"Millions vs thousands is the error that will actually bite."

    The release says "$91.0 billion" and the extractor faithfully returns 89.18
    to 92.82, because that is what the sentence says. Stored against a claim
    whose unit is USD, ninety-one billion dollars becomes ninety-one dollars —
    wrong by nine orders of magnitude, with every number downstream still
    internally consistent.
    """
    g = guide(low=89.18, high=92.82)
    _rescale(g)

    assert g.low == 89.18e9
    assert g.high == 92.82e9


def test_figures_already_in_absolute_dollars_are_not_scaled_twice():
    """A release that reports 91000000000 alongside the word "billion" must not
    be multiplied again — the second application is the silent one."""
    g = guide(low=89_180_000_000.0, high=92_820_000_000.0)
    _rescale(g)

    assert g.low == 89_180_000_000.0


def test_eps_is_never_rescaled():
    """EPS is dollars per share and never billions. A sentence mentioning both
    revenue in billions and EPS in dollars would otherwise multiply the EPS."""
    g = guide(metric="eps", point=2.05, quote="Revenue of $91.0 billion; EPS $2.05.")
    _rescale(g)

    assert g.point == 2.05


def test_a_quote_with_no_scale_word_is_left_alone():
    g = guide(low=1.2, high=1.4, quote="Revenue is expected to grow 12%.")
    _rescale(g)

    assert g.low == 1.2


def test_identical_figures_collapse_to_one_guide():
    """The guidance sentence appears in BOTH the press release and the CFO
    commentary, and the extractor labels it under each basis — so one revenue
    range arrived four times. Identical figures for the same metric and period
    are one fact, whatever basis it was tagged with; revenue has no GAAP versus
    non-GAAP distinction in the first place.
    """
    rows = [
        Guidance(metric="revenue", period="Q2 FY2027", low=89.18e9, high=92.82e9,
                 basis=Basis.NON_GAAP, claim_id="a"),
        Guidance(metric="revenue", period="Q2 FY2027", low=89.18e9, high=92.82e9,
                 basis=Basis.GAAP, claim_id="b"),
    ]
    assert len(_unique_guides(rows)) == 1


def test_genuinely_different_bases_both_survive():
    """Where the numbers actually differ the distinction is real — a company
    guiding GAAP and non-GAAP margins apart is telling you the bridge."""
    rows = [
        Guidance(metric="eps", period="Q2 FY2027", point=2.39,
                 basis=Basis.GAAP, claim_id="a"),
        Guidance(metric="eps", period="Q2 FY2027", point=1.87,
                 basis=Basis.NON_GAAP, claim_id="b"),
    ]
    assert len(_unique_guides(rows)) == 2
