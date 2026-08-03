"""Earnings call transcripts.

The transcript is the one source where a point-in-time leak is not subtle: a
call published after `as_of` literally contains the result being forecast. So
the date check is the test that matters here, and it is checked against the
date the API reports rather than against any date we compute.

No network. A fake client stands in for httpx, in the shape the API's own
documentation specifies.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.cache import Cache
from forecaster.data.protocol import PointInTimeViolation
from forecaster.data.transcript_source import TranscriptSource

AS_OF = date(2026, 8, 3)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, routes: dict[str, object], status: int = 200) -> None:
        self.routes = routes
        self.status = status
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None):
        path = url.rsplit("/", 1)[-1]
        self.calls.append((path, params or {}))
        return _FakeResponse(self.routes.get(path), self.status)


def _source(tmp_path, routes, status=200) -> tuple[TranscriptSource, _FakeClient]:
    source = TranscriptSource("test-key", Cache(tmp_path))
    client = _FakeClient(routes, status)
    source._client = client
    return source, client


LISTING = [
    {"ticker": "NVDA", "year": "2027", "quarter": "1", "date": "2026-05-20"},
    {"ticker": "NVDA", "year": "2026", "quarter": "4", "date": "2026-02-25"},
    {"ticker": "NVDA", "year": "2026", "quarter": "3", "date": "2025-11-19"},
]


def _transcript(published: str, text: str = "Operator: Good afternoon."):
    return {
        "date": published, "ticker": "NVDA", "year": "2027", "quarter": "1",
        "transcript": text,
    }


def test_a_transcript_published_after_as_of_raises(tmp_path):
    """The most direct leak available — the call contains the answer.

    Every other source can leak subtly, through a restatement or a revised
    estimate. A transcript published after `as_of` states the quarter's results
    out loud, so this fails loudly rather than filtering quietly.
    """
    source, _ = _source(tmp_path, {"earningstranscript": _transcript("2026-08-27")})

    with pytest.raises(PointInTimeViolation):
        source.get_quarter("NVDA", 2027, 2, AS_OF)


def test_a_transcript_published_before_as_of_is_returned(tmp_path):
    source, _ = _source(tmp_path, {"earningstranscript": _transcript("2026-05-20")})
    assert source.get_quarter("NVDA", 2027, 1, AS_OF).startswith("Operator")


def test_the_listing_bounds_the_search_at_as_of(tmp_path):
    """Ask the API which calls exist rather than deriving the fiscal label.

    A vendor's quarter labelling need not match the one we derive from period
    end dates, and a mismatch returns nothing — the same silent-empty failure
    as the calendar-vs-fiscal bug in the peer read.
    """
    source, client = _source(tmp_path, {"earningstranscriptsearch": LISTING})

    rows = source.available("NVDA", AS_OF)

    assert [r["date"] for r in rows] == ["2026-05-20", "2026-02-25", "2025-11-19"]
    _, params = client.calls[0]
    assert params["end_date"] == AS_OF.isoformat()


def test_an_empty_body_is_none_not_an_empty_string(tmp_path):
    """Outside the tier's history window the row comes back with no text.

    Returning "" would read downstream as a call that happened and contained
    nothing, which is a different and much more misleading claim than absence.
    """
    source, _ = _source(tmp_path, {"earningstranscript": _transcript("2020-05-20", "")})
    assert source.get_quarter("NVDA", 2021, 1, AS_OF) is None


def test_a_rejected_key_does_not_retry(tmp_path):
    """A bad key is configuration, not weather. Retrying it burns the clock on
    a day where the clock is the binding constraint."""
    source, client = _source(tmp_path, {"earningstranscript": None}, status=401)

    assert source.get_quarter("NVDA", 2027, 1, AS_OF) is None
    assert len(client.calls) == 1


def test_no_key_refuses_to_construct(tmp_path):
    with pytest.raises(ValueError, match="API key"):
        TranscriptSource("", Cache(tmp_path))


def test_get_transcript_picks_the_most_recent_knowable_call(tmp_path):
    source, _ = _source(tmp_path, {
        "earningstranscriptsearch": LISTING,
        "earningstranscript": _transcript("2026-05-20"),
    })
    assert source.get_transcript("NVDA", AS_OF) is not None


def test_no_listing_is_absence_not_an_error(tmp_path):
    """A company with no covered calls degrades the lens, never the run."""
    source, _ = _source(tmp_path, {"earningstranscriptsearch": []})
    assert source.get_transcript("NEWCO", AS_OF) is None
