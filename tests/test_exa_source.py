"""News and industry publications.

This is the weakest point-in-time story in the system and the strongest
fabrication risk, so both are tested here rather than assumed.

The date is an ESTIMATE — Exa infers `publishedDate` by parsing HTML, unlike a
filing's `filed` date or a call's date. And the content is prose from an
arbitrary publisher, which is the likeliest place for a model to produce a
quote that reads perfectly and was never written.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.cache import Cache
from forecaster.data.exa_source import ExaSource, _opening
from forecaster.data.protocol import PointInTimeViolation
from forecaster.pipeline.v1_reconcile import verify_citation
from forecaster.schemas import SourceKind

AS_OF = date(2026, 8, 3)

BODY = (
    "Omdia raises its semiconductor forecast for 2026. AI demand drove a 94.1% "
    "surge in the data centre segment, the firm said, with foundry capacity "
    "remaining the binding constraint through the second half."
)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code
        self.text = '{"error":"quota exhausted"}'

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def post(self, url, json=None):
        self.calls.append(json or {})
        return _FakeResponse(self.payload, self.status)


def _source(tmp_path, results, status=200):
    source = ExaSource("test-key", Cache(tmp_path))
    client = _FakeClient({"results": results}, status)
    source._client = client
    return source, client


def _result(url, published, text=BODY, title="Omdia raises forecast"):
    return {"url": url, "publishedDate": published, "text": text, "title": title}


def test_an_undated_result_is_dropped_not_assumed_old(tmp_path):
    """Exa infers the date from HTML and sometimes cannot.

    Everything else in the corpus carries a date somebody asserted — SEC stamps
    `filed`, a call happens on a day. Here it is a parse. An undated article is
    a leak we could never detect, and one article about the quarter being
    forecast outweighs the rest of the corpus put together.
    """
    source, _ = _source(tmp_path, [_result("https://a.example/1", None)])

    assert source.search("q", AS_OF) == []
    assert source.get_news("NVDA", AS_OF, "q") is None


def test_a_result_published_after_as_of_raises(tmp_path):
    """The date bound is sent to the API; this catches it not being honoured."""
    late = _result("https://a.example/2", "2026-09-01T00:00:00.000Z")
    source, _ = _source(tmp_path, [late])

    with pytest.raises(PointInTimeViolation):
        source.search("q", AS_OF)


def test_the_request_carries_the_date_bound(tmp_path):
    """Without it a historical as_of returns today's internet, and the lens
    cannot be backtested at all — which means lambda cannot be fitted with it."""
    ok = _result("https://a.example/3", "2026-07-01T00:00:00.000Z")
    source, client = _source(tmp_path, [ok])
    source.search("semiconductor demand", AS_OF, lookback_days=120)

    sent = client.calls[0]
    assert sent["endPublishedDate"].startswith("2026-08-03")
    assert sent["startPublishedDate"].startswith("2026-04-05")
    assert sent["contents"] == {"text": True}


def test_the_quote_is_an_exact_substring_of_the_stored_body(tmp_path):
    """News claims are PROSE, so the reconciler string-matches them.

    A descriptive quote — "article published 2026-07-01" — appears nowhere in
    the article and would fail every news claim, dropping any lens that cited
    one. Lifting the opening sentence out of the body makes it verify by
    construction.
    """
    url = "https://a.example/4"
    source, _ = _source(tmp_path, [_result(url, "2026-07-01T00:00:00.000Z")])

    (claim,) = source.get_news("NVDA", AS_OF, "semis")

    assert claim.source.kind is SourceKind.NEWS
    assert verify_citation(claim, source.get_document(url))


def test_a_spent_quota_degrades_rather_than_raising(tmp_path):
    """A raising source spends the Loader's failure budget and trips the
    breaker, turning "no news" into "this source is dead for the run"."""
    source, client = _source(tmp_path, None, status=402)

    assert source.search("q", AS_OF) == []
    assert len(client.calls) == 1


def test_opening_stops_at_a_sentence_boundary():
    assert _opening(BODY).endswith("2026.")
    # ...and never runs past the cap even with no punctuation.
    assert len(_opening("word " * 200)) <= 280
