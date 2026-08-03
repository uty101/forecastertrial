"""The plumbing around the SEC source, where the silent failures lived.

`test_history.py` covers the reshaping. These cover the three ways a correct
history still reached the pipeline as nothing at all: a period label that could
not match, a payload cached before the quarter existed, and a rate limit that
tripped the circuit breaker on the only source of actuals.

All three shared the property that makes them expensive — they produced a
plausible, reassuring answer rather than an error.
"""

from __future__ import annotations

import time
from datetime import date

import tenacity

from forecaster.data.cache import Cache
from forecaster.data.history import History, build_series
from forecaster.data.lineitems import BY_KEY
from forecaster.data.sec_source import _RETRY_STATUSES, SECSource, _TransientSEC
from forecaster.pipeline.a_acquire import PEER_LOOKBACK_DAYS, _peer_recent_actuals

NVDA_FYE = 1
AS_OF = date(2026, 8, 16)


def _fact(start, end, val, filed):
    return {
        "start": start, "end": end, "val": val, "filed": filed,
        "form": "10-Q", "fy": 2027, "fp": "FY", "accn": "0001045810-26-000052",
    }


def _history(filed: str) -> History:
    """A January year-end filer whose latest quarter ended in April 2026."""
    series = build_series(
        BY_KEY["revenue"],
        [_fact("2026-01-26", "2026-04-26", 44_062e6, filed)],
        NVDA_FYE,
    )
    return History("NVDA", AS_OF, {"revenue": series})


class _FakeLoader:
    def __init__(self, history: History | None) -> None:
        self._history = history
        self.asked_for: list[str] = []

    def history(self, ticker, as_of, keys=None):
        return self._history

    def actuals(self, ticker, period, as_of):
        self.asked_for.append(period)
        return ["claim"]


# --------------------------------------------------------------------------- #
# period labels
# --------------------------------------------------------------------------- #


def test_peer_print_is_found_for_a_non_december_year_end():
    """The headline bug, and the reason it survived.

    `_recent_periods` generated `f"{as_of.year}Q{q}"` and tried 2026 and 2025.
    NVDA's April 2026 quarter is fiscal 2027Q1, so nothing ever matched, the
    peer read came back empty, and the empty result was rendered as "none of
    these peers has reported within 100 days, which early in a reporting cycle
    is correct and common". A silent failure that reassures you is worse than
    one that raises.
    """
    loader = _FakeLoader(_history(filed="2026-05-27"))

    claims = _peer_recent_actuals(loader, "NVDA", AS_OF)

    assert claims == ["claim"]
    assert loader.asked_for == ["2027Q1"]


def test_a_print_older_than_the_window_is_still_rejected():
    """The lookback is the point of the check; fixing labels must not lose it.

    A print the Street has had months to absorb tells us nothing, so it should
    be skipped — but for the honest reason, not because its label failed.
    """
    stale = (AS_OF.toordinal() - PEER_LOOKBACK_DAYS - 5)
    loader = _FakeLoader(_history(filed=date.fromordinal(stale).isoformat()))

    assert _peer_recent_actuals(loader, "NVDA", AS_OF) == []
    assert loader.asked_for == []


def test_non_ticker_peers_are_skipped_rather_than_guessed_at():
    """A private or foreign supplier listed by name has no XBRL to look up."""
    loader = _FakeLoader(_history(filed="2026-05-27"))
    assert _peer_recent_actuals(loader, "Taiwan Semiconductor", AS_OF) == []
    assert _peer_recent_actuals(loader, "tsm", AS_OF) == []


def test_a_peer_with_no_history_is_not_an_error():
    assert _peer_recent_actuals(_FakeLoader(None), "NVDA", AS_OF) == []


# --------------------------------------------------------------------------- #
# cache freshness
# --------------------------------------------------------------------------- #


def _stale_envelope(cache: Cache, key: str, fetched_at: str) -> list[int]:
    cache.put(key, {"fetched_at": fetched_at, "value": {"facts": "old"}})
    return []


def test_companyfacts_cached_before_as_of_is_refetched(tmp_path):
    """The staleness bug: a payload fetched last week cannot contain this week.

    `_visible` filters facts filed after `as_of`, but it cannot restore facts
    that were never in the response. A payload cached before the quarter was
    filed makes the current quarter look like it does not exist — the same
    symptom as a company that has genuinely not reported.
    """
    cache = Cache(tmp_path)
    key = cache.key("sec_facts", date(2000, 1, 1), cik="0001045810")
    _stale_envelope(cache, key, "2026-08-03")

    calls: list[int] = []

    def producer():
        calls.append(1)
        return {"facts": "fresh"}

    got = cache.fetch_dated(key, producer, not_before=AS_OF)

    assert got == {"facts": "fresh"}
    assert len(calls) == 1


def test_companyfacts_fetched_after_as_of_is_reused(tmp_path):
    """Freshness is the weaker condition on purpose.

    Keying on `as_of` would be correct and ruinous — a 200-quarter backtest
    would refetch the same multi-megabyte payload 200 times per ticker. A
    payload fetched today serves every historical `as_of`.
    """
    cache = Cache(tmp_path)
    key = cache.key("sec_facts", date(2000, 1, 1), cik="0001045810")
    cache.put(key, {"fetched_at": "2026-08-16", "value": {"facts": "kept"}})

    def producer():
        raise AssertionError("should not have reached the network")

    assert cache.fetch_dated(key, producer, not_before=date(2024, 3, 31)) == {
        "facts": "kept"
    }


def test_read_only_replay_ignores_freshness(tmp_path):
    """`make verify` replays a recorded cache and must never hit the network.

    Enforcing freshness here would make the golden-file test either flaky or
    dependent on when the fixture was recorded.
    """
    writable = Cache(tmp_path)
    key = writable.key("sec_facts", date(2000, 1, 1), cik="0001045810")
    _stale_envelope(writable, key, "2020-01-01")

    replay = Cache(tmp_path, read_only=True)

    def producer():
        raise AssertionError("read-only replay must not fetch")

    assert replay.fetch_dated(key, producer, not_before=AS_OF) == {"facts": "old"}


def test_an_entry_written_without_the_envelope_is_refreshed(tmp_path):
    """Caches written by an earlier build are raw payloads, not envelopes."""
    cache = Cache(tmp_path)
    key = cache.key("sec_facts", date(2000, 1, 1), cik="0001045810")
    cache.put(key, {"facts": "legacy"})

    assert cache.fetch_dated(key, lambda: {"facts": "fresh"}, not_before=AS_OF) == {
        "facts": "fresh"
    }
    # ...and replay still trusts whatever was recorded.
    legacy = Cache(tmp_path, read_only=True)
    cache.put(key, {"facts": "legacy"})
    assert legacy.fetch_dated(key, lambda: None, not_before=AS_OF) == {"facts": "legacy"}


# --------------------------------------------------------------------------- #
# peers by industry code
# --------------------------------------------------------------------------- #


def test_ticker_index_ranks_by_size_and_picks_the_common_stock(tmp_path):
    """`company_tickers.json` is size-ordered, and its keys are STRINGS.

    So iteration runs "0", "10337", "15" — not ascending rank. Keeping the
    first occurrence per company therefore handed Bank of America the ticker
    BAC-PL at rank 10337 instead of BAC at 15, because a multi-class issuer
    appears once per listed class.

    The damage was downstream and silent: peers are ranked by this position, so
    BAC, WFC, C and USB fell to the bottom of JPMorgan's industry and the peer
    set came back as Amerant, BOK Financial and Camden National. A plausible
    list of real banks, none of them comparable.
    """
    cache = Cache(tmp_path)
    # Insertion order here mirrors the file's string-sorted keys.
    cache.put(
        cache.key("sec_tickers", date(2000, 1, 1)),
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
            "10337": {"cik_str": 70858, "ticker": "BAC-PL", "title": "Bank of America"},
            "15": {"cik_str": 70858, "ticker": "BAC", "title": "Bank of America"},
        },
    )
    index = SECSource("Test User test@example.com", cache)._ticker_index()

    assert index[70858] == (15, "BAC")
    assert index[320193] == (0, "AAPL")


# --------------------------------------------------------------------------- #
# throttling
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "{}") -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"ok": True}

    def raise_for_status(self):
        # httpx is a no-op on 2xx; anything else here is a status the source
        # decided was neither retryable nor an ordinary 404.
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        status = self._statuses.pop(0) if self._statuses else 200
        return _FakeResponse(status)


def _source(tmp_path, statuses: list[int]) -> tuple[SECSource, _FakeClient]:
    source = SECSource("Test User test@example.com", Cache(tmp_path))
    client = _FakeClient(statuses)
    source._client = client
    return source, client


def test_a_403_is_retried_rather_than_counted_as_a_source_failure(tmp_path, monkeypatch):
    """SEC answers a breached rate limit with 403, the same status as a missing
    User-Agent. Letting it through spends `Loader.FAILURES_BEFORE_TRIP` in under
    a second and trips the breaker on the only source of actuals, filings and
    document bodies — which ends the run at "every lens was dropped" rather than
    degrading it.
    """
    monkeypatch.setattr(SECSource._http_get.retry, "wait", tenacity.wait_none())
    source, client = _source(tmp_path, [403, 403, 200])

    response = source._http_get("https://data.sec.gov/anything")

    assert response.status_code == 200
    assert len(client.calls) == 3
    assert 403 in _RETRY_STATUSES and 429 in _RETRY_STATUSES


def test_persistent_throttling_eventually_surfaces(tmp_path, monkeypatch):
    """Retrying forever would hang the run; four attempts then tell the truth."""
    monkeypatch.setattr(SECSource._http_get.retry, "wait", tenacity.wait_none())
    source, client = _source(tmp_path, [429] * 10)

    try:
        source._http_get("https://data.sec.gov/anything")
    except _TransientSEC:
        pass
    else:
        raise AssertionError("expected _TransientSEC after the retry budget")

    assert len(client.calls) == 4


def test_a_404_is_not_retried(tmp_path):
    """A company that never filed a given form is an ordinary outcome."""
    source, client = _source(tmp_path, [404])
    assert source._http_get("https://data.sec.gov/missing") is None
    assert len(client.calls) == 1


def test_requests_are_paced_under_the_published_limit(tmp_path):
    """10 req/sec is SEC's ceiling and the limiter runs on their clock."""
    source, _ = _source(tmp_path, [200, 200])

    started = time.monotonic()
    source._http_get("https://data.sec.gov/one")
    source._http_get("https://data.sec.gov/two")

    assert time.monotonic() - started >= 0.1
