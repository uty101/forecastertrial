"""The adapter written on the day.

This is the only file that gets edited under time pressure, in a room, by
someone who has been awake since six — and it sits at priority 1, ahead of
yfinance and SEC, so whatever it returns wins. That combination is why it is
worth testing the template *before* the day rather than the filled-in version
after: the tests here are the guardrails that stay true no matter which fields
get mapped at 10:30.

Every failure mode below shares a shape: the adapter returns something usable
and wrong, and nothing downstream can tell.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.cache import Cache
from forecaster.data.protocol import PointInTimeViolation
from forecaster.data.sponsor_source import SponsorSource, _maybe_float, _maybe_int
from forecaster.schemas import Basis, SourceKind

AS_OF = date(2026, 8, 16)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def get(self, path, params=None):
        self.calls.append((path, params or {}))
        return _FakeResponse(self.payload, self.status)


def _source(tmp_path, payload, status=200):
    source = SponsorSource("https://feed.test", "key", Cache(tmp_path))
    client = _FakeClient(payload, status)
    source._client = client
    return source, client


# --------------------------------------------------------------------------- #
# point-in-time
# --------------------------------------------------------------------------- #


def test_a_consensus_revision_dated_after_as_of_raises(tmp_path):
    """The single highest-risk thing a sponsor feed can do.

    Their API almost certainly serves *current* estimates and has no reason to
    respect a historical `as_of` — that is our problem, not theirs. A revision
    published after the date we are forecasting from is look-ahead bias that
    improves the score and invalidates it, and priority 1 means it beats the two
    sources that do respect the boundary. It has to raise, not be dropped.
    """
    source, _ = _source(
        tmp_path,
        {"eps_mean": 2.11, "as_of_date": "2026-08-17"},  # one day too late
    )

    with pytest.raises(PointInTimeViolation):
        source.get_consensus("NVDA", AS_OF)


def test_a_consensus_dated_on_as_of_is_accepted(tmp_path):
    """The boundary is inclusive. An estimate published on the morning we
    forecast from is information we genuinely have."""
    source, _ = _source(tmp_path, {"eps_mean": 2.11, "as_of_date": "2026-08-16"})

    assert source.get_consensus("NVDA", AS_OF).eps == 2.11


def test_the_cache_key_carries_as_of(tmp_path):
    """Cached on `as_of` so a payload fetched for one date can never be served
    for another. Without this the first call of the day poisons every backtest
    quarter that follows it."""
    source, client = _source(tmp_path, {"eps_mean": 2.11})

    source.get_consensus("NVDA", AS_OF)
    source.get_consensus("NVDA", date(2026, 5, 16))

    assert len(client.calls) == 2, "a different as_of reused a cached payload"


# --------------------------------------------------------------------------- #
# falling through rather than failing
# --------------------------------------------------------------------------- #


def test_a_404_returns_none_so_the_loader_falls_through(tmp_path):
    """What makes a half-written adapter safe to ship at 10:50.

    A sponsor feed that does not cover a ticker must hand back None, not raise:
    the loader then falls through to yfinance and SEC and the run continues. An
    exception here takes down a source the circuit breaker counts.
    """
    source, _ = _source(tmp_path, None, status=404)

    assert source.get_consensus("NVDA", AS_OF) is None
    assert source.get_actuals("NVDA", "2027Q2", AS_OF) is None


def test_a_payload_without_an_eps_field_returns_none(tmp_path):
    """Their field names are unknown until 10:30, so the mapping WILL be wrong
    at least once. Wrong must mean "no consensus" — a Consensus built with a
    missing eps would be compared against ours and reported as a finding."""
    source, _ = _source(tmp_path, {"mean_estimate": 2.11})  # unmapped name

    assert source.get_consensus("NVDA", AS_OF) is None


def test_the_alternate_eps_field_name_is_accepted(tmp_path):
    source, _ = _source(tmp_path, {"consensus_eps": 2.04})

    assert source.get_consensus("NVDA", AS_OF).eps == 2.04


def test_consensus_declares_its_basis(tmp_path):
    """Consensus is non-GAAP and SEC XBRL is GAAP; the median DJIA gap was 31%
    in one recent quarter. An undeclared basis is a systematic one-directional
    error that looks like bad modelling. The template asserts non-GAAP and the
    docstring says to confirm it on the day — this test is what makes the
    assumption visible rather than buried."""
    source, _ = _source(tmp_path, {"eps_mean": 2.11})

    assert source.get_consensus("NVDA", AS_OF).basis is Basis.NON_GAAP


# --------------------------------------------------------------------------- #
# actuals and provenance
# --------------------------------------------------------------------------- #


def test_a_partial_payload_yields_fewer_claims_not_empty_ones(tmp_path):
    """A missing field must produce no claim, never a claim carrying None.

    A valueless claim satisfies the schema and then reaches the model as a fact
    with a blank in it, which is exactly the shape the provenance invariant
    exists to prevent.
    """
    source, _ = _source(tmp_path, {"revenue": 46_743_000_000, "eps_diluted": None})

    claims = source.get_actuals("NVDA", "2027Q2", AS_OF)

    assert [c.label for c in claims] == ["Revenue"]
    assert all(c.value is not None for c in claims)


def test_every_actual_carries_a_quote_naming_its_field_and_value(tmp_path):
    """A structured feed has no prose to quote, so the "quote" is the field
    itself — which keeps the invariant machine-verifiable against the same
    endpoint instead of exempting this source from it."""
    source, _ = _source(tmp_path, {"revenue": 46_743_000_000})

    claim = source.get_actuals("NVDA", "2027Q2", AS_OF)[0]

    assert claim.verbatim_quote == "revenue=46743000000 for NVDA 2027Q2"
    assert claim.source.kind is SourceKind.SPONSOR
    assert "ticker=NVDA" in claim.source.uri


def test_an_empty_actuals_payload_returns_none_not_an_empty_list(tmp_path):
    """`None` means "this source cannot answer" and the loader moves on; `[]`
    means "answered, nothing there" and it does not."""
    source, _ = _source(tmp_path, {"unrelated": 1})

    assert source.get_actuals("NVDA", "2027Q2", AS_OF) is None


# --------------------------------------------------------------------------- #
# coercion
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("junk", ["n/a", "", None, "—", {}])
def test_garbage_numeric_fields_become_none_rather_than_raising(junk):
    """Feeds put "n/a" in numeric columns. That must cost us one optional field,
    not the whole run."""
    assert _maybe_float(junk) is None
    assert _maybe_int(junk) is None


def test_numeric_strings_are_still_read():
    """The other half of the same rule: tolerant of junk must not mean deaf to
    a number that arrived as a string."""
    assert _maybe_float("2.11") == 2.11
    assert _maybe_int("61") == 61


def test_methods_the_adapter_does_not_implement_return_none(tmp_path):
    """Returning None is what lets us ship three methods instead of eight. If
    an unimplemented method raised, a partial adapter would be worse than none.
    """
    source, _ = _source(tmp_path, {})

    assert source.get_guidance("NVDA", AS_OF) is None
    assert source.get_filings("NVDA", AS_OF, ["8-K"]) is None
    assert source.get_transcript("NVDA", AS_OF) is None
    assert source.get_macro(["DFF"], AS_OF) is None
    assert source.get_fx_rates(["EUR"], date(2026, 1, 1), AS_OF) is None


def test_it_outranks_the_sources_it_is_meant_to_beat(tmp_path):
    """Priority 1 is load-bearing: their data is the scored data, so it has to
    win the resolve. If this drifts above yfinance's the sponsor feed becomes a
    fallback nobody notices we stopped using."""
    from forecaster.data.yfinance_source import YFinanceSource

    assert SponsorSource.priority < YFinanceSource.priority
