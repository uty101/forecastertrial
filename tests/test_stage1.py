"""Stage 1 — data layer, shrinkage, baseline, backtest harness.

Every test here encodes a real failure mode. The ones that matter most are the
loader fallback (a half-working sponsor adapter must still be useful) and the
backtest's honesty about statistical power.
"""

from __future__ import annotations

import statistics
from datetime import date

import pytest

from forecaster.data.cache import Cache, CacheMiss
from forecaster.data.loader import Loader
from forecaster.data.protocol import PointInTimeViolation
from forecaster.eval import baseline as bl
from forecaster.eval.backtest import Case, ablate, run
from forecaster.eval.shrinkage import guide_landing_positions, mad, shrink, winsorize
from forecaster.schemas import Basis, Consensus

AS_OF = date(2026, 8, 16)

# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #


def test_cache_key_includes_as_of(tmp_path):
    """The cache must never be able to serve data across a point-in-time
    boundary. Different as_of, different key — no exceptions."""
    cache = Cache(tmp_path)
    a = cache.key("consensus", date(2026, 8, 16), ticker="NVDA")
    b = cache.key("consensus", date(2026, 8, 17), ticker="NVDA")
    assert a != b


def test_cache_roundtrip_and_stats(tmp_path):
    cache = Cache(tmp_path)
    key = cache.key("x", AS_OF, ticker="NVDA")
    assert cache.fetch(key, lambda: {"eps": 1.0}) == {"eps": 1.0}
    assert cache.fetch(key, lambda: {"eps": 999.0}) == {"eps": 1.0}  # served cached
    assert cache.stats["hits"] == 1


def test_read_only_cache_refuses_to_fetch(tmp_path):
    """`make verify` runs read-only. A silent network fallback would make the
    golden-file test meaningless, so a miss must be fatal."""
    cache = Cache(tmp_path, read_only=True)
    with pytest.raises(CacheMiss):
        cache.fetch(cache.key("x", AS_OF), lambda: {"eps": 1.0})


# --------------------------------------------------------------------------- #
# loader
# --------------------------------------------------------------------------- #


class FakeSource:
    def __init__(self, name, priority, consensus=None, raises=False):
        self.name, self.priority = name, priority
        self._consensus, self._raises = consensus, raises
        self.calls = 0

    def get_consensus(self, ticker, as_of):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._consensus

    def get_actuals(self, *a):
        return None

    def get_guidance(self, *a):
        return None

    def get_filings(self, *a, **k):
        return None

    def get_transcript(self, *a):
        return None

    def get_fx_rates(self, *a):
        return None

    def get_macro(self, *a):
        return None


def _cons(eps, n=20):
    return Consensus(eps=eps, n_analysts=n, basis=Basis.NON_GAAP, as_of=AS_OF)


def test_partial_adapter_still_useful():
    """The design rule that makes the day-of adapter cheap: a sponsor source
    that only answers `get_consensus` and returns None for everything else
    falls through to yfinance/SEC for the rest."""
    sponsor = FakeSource("sponsor", 1, consensus=_cons(1.10))
    fallback = FakeSource("yfinance", 10, consensus=_cons(1.05))
    loader = Loader([fallback, sponsor])

    assert loader.consensus("NVDA", AS_OF).eps == 1.10
    assert loader.provenance["consensus:NVDA"] == "sponsor"


def test_falls_through_when_higher_priority_returns_none():
    loader = Loader([FakeSource("sponsor", 1), FakeSource("yfinance", 10, _cons(1.05))])
    assert loader.consensus("NVDA", AS_OF).eps == 1.05
    assert loader.provenance["consensus:NVDA"] == "yfinance"


def test_disagreement_between_sources_is_recorded_not_swallowed():
    """Two sources disagreeing on consensus usually means a GAAP/non-GAAP
    basis mismatch. That is a finding, not an error."""
    loader = Loader([FakeSource("sponsor", 1, _cons(1.10)), FakeSource("yf", 10, _cons(1.05))])
    loader.consensus("NVDA", AS_OF)
    assert len(loader.disagreements) == 1


def test_circuit_breaker_trips_after_three_failures():
    flaky = FakeSource("flaky", 1, raises=True)
    good = FakeSource("good", 10, consensus=_cons(1.0))
    loader = Loader([flaky, good])

    for _ in range(4):
        assert loader.consensus("NVDA", AS_OF).eps == 1.0

    assert flaky.calls == 3, "should stop calling a source that keeps failing"
    assert "flaky" in loader.report()["tripped"]


def test_point_in_time_violation_is_never_routed_around():
    """A leak is a bug to fix, not a transient failure to fall back from."""

    class Leaky(FakeSource):
        def get_consensus(self, ticker, as_of):
            raise PointInTimeViolation("leaked")

    loader = Loader([Leaky("leaky", 1), FakeSource("good", 10, _cons(1.0))])
    with pytest.raises(PointInTimeViolation):
        loader.consensus("NVDA", AS_OF)


# --------------------------------------------------------------------------- #
# shrinkage
# --------------------------------------------------------------------------- #


def test_noisy_company_is_pulled_toward_peers():
    """Three erratic quarters should not be trusted over the sector."""
    noisy = shrink("NOISY", [0.40, -0.30, 0.35], {f"P{i}": [0.02, 0.03, 0.02] for i in range(8)})
    assert noisy.weight < 0.5
    assert abs(noisy.shrunk) < abs(noisy.raw)


def test_consistent_company_keeps_more_of_its_own_number():
    steady = shrink("STEADY", [0.05] * 8, {f"P{i}": [0.01 * i, 0.02 * i] for i in range(1, 9)})
    noisy = shrink("NOISY", [0.40, -0.30, 0.35], {f"P{i}": [0.01 * i, 0.02 * i] for i in range(1, 9)})
    assert steady.weight > noisy.weight


def test_no_history_falls_back_to_group():
    est = shrink("NEW", [], {"A": [0.05, 0.06], "B": [0.03, 0.04]})
    assert est.n == 0 and est.shrunk == est.group


def test_winsorize_clips_the_alphabet_case():
    """One +216% surprise must not set the calibration for everyone else."""
    values = [0.02, 0.03, 0.01, 0.04, 0.02, 0.03, 2.16]
    assert max(winsorize(values)) < 2.16
    assert statistics.fmean(winsorize(values)) < statistics.fmean(values)


def test_mad_is_robust_to_a_single_outlier():
    clean = [0.02, 0.03, 0.02, 0.03, 0.02]
    assert mad(clean + [5.0]) == pytest.approx(mad(clean), abs=0.02)


def test_guide_landing_positions():
    """Where a company lands inside its own guided range: 0=low, 1=high, >1=beat."""
    pos = guide_landing_positions([(1.0, 2.0), (2.0, 3.0), (0.0, 1.0)], [1.5, 3.0, 1.2])
    assert pos == [0.5, 1.0, pytest.approx(1.2)]


# --------------------------------------------------------------------------- #
# baseline
# --------------------------------------------------------------------------- #


def test_baseline_uses_index_tilt_without_history():
    b = bl.build(consensus_eps=1.00, ticker="NEW")
    assert b.eps == pytest.approx(1.070)
    assert "aggregate tilt" in b.rationale


def test_baseline_uses_shrunk_company_tilt_with_history():
    b = bl.build(
        consensus_eps=1.00,
        ticker="ADBE",
        own_surprises=[0.04, 0.05, 0.04, 0.05, 0.04, 0.05, 0.04, 0.05],
        peer_surprises={f"P{i}": [0.02, 0.03] for i in range(6)},
    )
    assert 1.02 < b.eps < 1.06
    assert "shrunk" in b.rationale


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #


def _cases(n=12):
    return [
        Case(
            ticker=f"T{i}",
            period="2026Q1",
            as_of=date(2026, 5, 1),
            consensus_eps=1.00,
            actual_eps=1.00 * (1 + (0.07 if i % 4 else -0.05)),
        )
        for i in range(n)
    ]


def test_baseline_beats_naive_consensus():
    """The whole reason the baseline is hard to beat: companies beat the bar
    ~78% of the time, so a flat tilt is genuinely good."""
    result = run(_cases(), forecaster=lambda c: c.consensus_eps)
    assert result.mae_baseline < result.mae_consensus


def test_a_forecaster_that_matches_consensus_has_zero_skill():
    result = run(_cases(), forecaster=lambda c: c.consensus_eps)
    assert result.skill_vs_consensus == pytest.approx(0.0)
    assert result.win_rate == 0.0


def test_an_oracle_scores_perfectly():
    result = run(_cases(), forecaster=lambda c: c.actual_eps)
    assert result.mae == 0.0
    assert result.skill_vs_consensus == pytest.approx(1.0)
    assert result.win_rate == 1.0


def test_small_n_is_flagged_as_underpowered():
    """The sentence to say on stage before someone else does."""
    result = run(_cases(20), forecaster=lambda c: c.actual_eps)
    assert result.underpowered
    lo, hi = result.win_rate_ci
    assert hi - lo > 0.0
    assert "variance-dominated" in result.summary()["power_note"]


def test_run_spread_is_captured_for_stochastic_forecasters():
    """'A single run of a model is a coin flip wearing a suit.'"""
    seq = iter([0.9, 1.0, 1.1] * 100)

    result = run(_cases(3), forecaster=lambda c: next(seq), runs_per_case=3)
    assert result.runs_per_case == 3
    assert result.mean_run_spread > 0


def test_ablation_identifies_a_lens_that_does_nothing():
    """The check that decides whether seven lenses is really seven lenses."""

    def build(active: list[str]):
        # 'good' moves the forecast toward truth; 'useless' does nothing.
        return lambda c: c.actual_eps if "good" in active else c.consensus_eps

    scores = ablate(_cases(), build, ["good", "useless"])
    assert scores["good"] > 0, "removing a useful lens should raise MAE"
    assert scores["useless"] == 0.0, "removing a useless lens should change nothing"


def test_degenerate_peer_set_does_not_discard_a_long_own_record():
    """Regression. Found by a smoke test, not by the unit tests above.

    If every peer happens to share a median, MAD of the peer medians is 0 and
    the naive James-Stein weight collapses to 0 — throwing away a company with
    eight consistent quarters because five synthetic peers looked identical.

    Zero between-company spread is an ABSENCE of evidence, not evidence that
    all companies are the same. Fall back to sample-size shrinkage.
    """
    identical_peers = {f"P{i}": [0.02, 0.03, 0.02, 0.04] for i in range(10)}
    long_record = shrink("ADBE", [0.045, 0.05, 0.042, 0.048, 0.046, 0.05, 0.044, 0.049],
                         identical_peers)
    short_record = shrink("NEWCO", [0.045, 0.05, 0.042], identical_peers)

    assert long_record.weight == pytest.approx(0.5), "8 quarters should earn half"
    assert short_record.weight < long_record.weight, "3 quarters should earn less"
    assert long_record.shrunk > long_record.group, "own history must still count"


def test_too_few_peers_falls_back_rather_than_trusting_noise():
    est = shrink("X", [0.05] * 8, {"A": [0.01, 0.02], "B": [0.09, 0.10]})
    assert est.weight > 0, "two peers is not a usable between-company estimate"
