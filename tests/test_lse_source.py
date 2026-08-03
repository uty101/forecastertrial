"""The options chain, and the one number the rest of the system cannot produce.

Every other measure of dispersion here is our own opinion measured twice — our
backtest residuals, and analyst disagreement. A straddle is somebody putting
money on the size of the move.

The first test is the one that matters. The endpoint accepts date parameters and
ignores them, so nothing but an explicit refusal stops a backtest being handed
today's option prices for a quarter that has already happened.
"""

from __future__ import annotations

from datetime import date, timedelta

from forecaster.data.cache import Cache
from forecaster.data.lse_source import LSESource

TODAY = date.today()


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code
        self.text = '{"detail":"quota"}'

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def get(self, url, params=None):
        self.calls.append(params or {})
        return _FakeResponse(self.payload, self.status)


def contract(strike, kind, price, expiry, iv=0.45, spot=200.0):
    return {
        "ticker": f"X{expiry}{kind[0].upper()}{strike}", "underlying": "NVDA",
        "strike": strike, "expiry": expiry, "contract_type": kind,
        "last_price": price, "underlying_price": spot, "iv": iv, "dte": 25,
    }


CHAIN = [
    # An earlier expiry that does NOT bracket the print.
    contract(200, "call", 4.0, "2026-08-14"),
    contract(200, "put", 4.0, "2026-08-14"),
    # The expiry after the earnings date, carrying the event premium.
    contract(190, "call", 16.0, "2026-08-28"),
    contract(200, "call", 11.0, "2026-08-28"),
    contract(200, "put", 11.0, "2026-08-28"),
]


def _source(tmp_path, payload, status=200):
    source = LSESource("k", "https://api.example/vault", Cache(tmp_path))
    client = _FakeClient(payload, status)
    source._client = client
    return source, client


def test_a_historical_as_of_is_refused_rather_than_served_todays_chain(tmp_path):
    """The endpoint accepts as_of, date and start/end and IGNORES all three.

    Verified against the live API: every variant returns the identical 3,945
    rows. So a backtest of a past quarter would be handed a chain priced with
    full knowledge of what happened — the most direct leak available, since the
    market already knows the answer.

    Returning None costs a lens. Returning the chain invents a forecaster that
    already knew.
    """
    source, client = _source(tmp_path, CHAIN)
    stale = TODAY - timedelta(days=60)

    assert source.get_options_chain("NVDA", stale) is None
    assert source.implied_move("NVDA", stale, TODAY) is None
    assert client.calls == []  # refused before reaching the network


def test_a_current_as_of_is_served(tmp_path):
    source, _ = _source(tmp_path, CHAIN)
    assert source.get_options_chain("NVDA", TODAY) is not None


def test_the_expiry_bracketing_the_print_is_chosen(tmp_path):
    """An expiry before the print prices an ordinary week; the one after it
    carries the event premium, which is the whole quantity of interest."""
    source, _ = _source(tmp_path, CHAIN)

    move = source.implied_move("NVDA", TODAY, date(2026, 8, 26))

    assert move["expiry"] == "2026-08-28"
    assert move["strike"] == 200
    # 11.0 call + 11.0 put over a 200 spot.
    assert move["straddle"] == 22.0
    assert move["implied_move_pct"] == 0.11


def test_a_strike_with_only_one_leg_is_not_a_straddle(tmp_path):
    """190 is nearer nothing useful: a lone call prices a direction, not a move.

    Picking it would report an implied move of half the truth, with no error.
    """
    source, _ = _source(tmp_path, [c for c in CHAIN if not (
        c["expiry"] == "2026-08-28" and c["strike"] == 200 and c["contract_type"] == "put"
    )])

    assert source.implied_move("NVDA", TODAY, date(2026, 8, 26)) is None


def test_no_expiry_after_the_print_is_absence_not_an_error(tmp_path):
    source, _ = _source(tmp_path, CHAIN)
    assert source.implied_move("NVDA", TODAY, date(2027, 12, 1)) is None


def test_a_spent_quota_degrades_rather_than_raising(tmp_path):
    source, _ = _source(tmp_path, None, status=402)
    assert source.get_options_chain("NVDA", TODAY) is None
