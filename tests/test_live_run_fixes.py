"""Four bugs that only a live run could show, each pinned so it cannot return.

None of these were visible from the test suite, and none of them raised. They
are here because the failure mode they share is the expensive one: the system
kept working, produced a number, and was quietly worse.

    the cache        eight lenses each WROTE the shared corpus and none read one
    the citations    the one lens that cannot hallucinate was dropped for a
                     fabricated citation
    the judge        the single most expensive call thrown away over a dict key
    the truncation   a lens's work finished, paid for, and discarded

The first is a cost bug, the rest are correctness bugs. All four were found by
spending $0.88 and reading the log.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from forecaster.pipeline.e_lenses.base import LENS_MAX_TOKENS
from forecaster.pipeline.g_judge import REQUIRED_QUANTILES, JudgeResponse
from forecaster.pipeline.v1_reconcile import (
    PROSE_SOURCES,
    STRUCTURED_SOURCES,
    verify_citations,
)
from forecaster.schemas import Claim, Source, SourceKind

# ---- the cache ----------------------------------------------------------- #


def test_the_corpus_is_the_cache_prefix_not_the_suffix():
    """The whole economics of the fan-out depends on this ordering.

    Caching is a PREFIX match. With the per-lens instructions in front of the
    breakpoint, every lens presents a different prefix, so each one writes the
    corpus at the 1.25x write rate and none of them ever reads one. It still
    works; it just costs several times what it should and looks identical in the
    output.
    """
    import inspect

    from forecaster.llm import client as client_mod

    source = inspect.getsource(client_mod.LLMClient._live_call)
    corpus_at = source.index('"text": corpus')
    system_at = source.index('"text": system_text')
    assert corpus_at < system_at, (
        "the corpus must be appended to `system` BEFORE the per-prompt "
        "instructions. Caching is a prefix match, so a per-lens block in front "
        "of the breakpoint means the cache can never hit across the fan-out."
    )
    # And the breakpoint has to be on the corpus block itself.
    assert 'cache_control' in source[corpus_at : corpus_at + 240]


# ---- the citations ------------------------------------------------------- #


def index_claim() -> Claim:
    """What the SEC submissions feed gives you: a pointer, not a sentence."""
    return Claim(
        id="sec:NVDA:0001045810-26-000051",
        label="8-K filed 2026-05-20",
        value=None,
        source=Source(
            kind=SourceKind.FILING_INDEX,
            uri="https://sec.gov/Archives/.../nvda-8k.htm",
            as_of=date(2026, 5, 20),
            accession="0001045810-26-000051",
        ),
        verbatim_quote="8-K filed 2026-05-20, accession 0001045810-26-000051",
    )


def test_a_pointer_to_a_filing_is_not_a_quote_from_it():
    """The bug that dropped the Mechanical lens — the one with no model in it.

    The claim says the document EXISTS. String-matching that descriptor against
    the document it points at fails by construction, because the sentence was
    never written anywhere in the exhibit. The check was not catching a
    fabrication; it was comparing the wrong two things.
    """
    body = "NVIDIA Corporation furnishes Exhibit 99.1 herewith. Revenue was..."
    verified, failed = verify_citations(
        [index_claim()], {"https://sec.gov/Archives/.../nvda-8k.htm": body}
    )

    assert failed == []
    assert len(verified) == 1


def test_a_quote_from_inside_a_filing_is_still_string_matched():
    """The rule that must NOT have been weakened by the fix above."""
    body = "We expect third quarter revenue of $44.0 billion, plus or minus 2%."
    invented = Claim(
        id="guide:NVDA:Q3:eps:0",
        label="revenue guidance",
        value=44e9,
        unit="USD",
        source=Source(
            kind=SourceKind.FILING_8K,
            uri="https://sec.gov/ex99.htm",
            as_of=date(2026, 5, 20),
        ),
        verbatim_quote="We expect third quarter revenue of $48.0 billion.",
    )
    verified, failed = verify_citations([invented], {"https://sec.gov/ex99.htm": body})

    assert verified == []
    assert failed == ["guide:NVDA:Q3:eps:0"]


def test_the_two_classifications_stay_disjoint():
    """A kind in both sets would be checked one way and excused the other,
    and which one won would depend on dict ordering."""
    assert not (PROSE_SOURCES & STRUCTURED_SOURCES)
    assert SourceKind.FILING_INDEX in STRUCTURED_SOURCES
    assert SourceKind.FILING_8K in PROSE_SOURCES


# ---- the judge ----------------------------------------------------------- #


def test_the_five_levels_are_named_fields_not_a_free_form_mapping():
    """Two consecutive live runs discarded the most expensive call in the
    system because `quantiles` came back as an empty dict, with the numbers
    written out in the rationale prose instead.

    A mapping asks the model to invent a key format and then populate it. Five
    required floats ask it for five numbers. The `quantiles` property still
    presents them the way everything downstream reads them.
    """
    response = JudgeResponse(
        median_eps=2.0, mean_eps=2.0,
        p10=1.8, p25=1.9, p50=2.0, p75=2.1, p90=2.2,
        rationale="the guidance case carried it",
    )

    assert sorted(response.quantiles) == sorted(REQUIRED_QUANTILES)
    assert response.quantiles["0.1"] == 1.8
    assert response.quantiles["0.9"] == 2.2


def test_a_missing_level_cannot_be_omitted_at_all():
    """Not a validator any more — the field is required, so the model is asked
    again rather than the run falling back."""
    with pytest.raises(ValidationError):
        JudgeResponse(
            median_eps=2.0, mean_eps=2.0, p10=1.8, p50=2.0, rationale="x"
        )


def test_a_non_monotonic_cdf_is_still_a_hard_failure():
    """Naming the fields must not have relaxed anything about the VALUES.
    A CDF that goes backwards is not a distribution, and it would flow into
    calibration and produce intervals no chart would reveal as nonsense."""
    with pytest.raises(ValueError, match="monotonically increasing"):
        JudgeResponse(
            median_eps=2.0, mean_eps=2.0,
            p10=1.8, p25=2.4, p50=2.0, p75=2.1, p90=2.2,
            rationale="x",
        )


# ---- the truncation ------------------------------------------------------ #


def test_lenses_get_more_room_than_the_client_default():
    """Peer read finished its reasoning and lost it to stop_reason=max_tokens.
    Output tokens are billed on use, so headroom is free until it is needed."""
    import inspect

    from forecaster.llm import client as client_mod

    default = inspect.signature(client_mod.LLMClient.call).parameters["max_tokens"]
    assert default.default < LENS_MAX_TOKENS
