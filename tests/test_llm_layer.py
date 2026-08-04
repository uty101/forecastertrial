"""Prompts, evidence store, judge and calibration.

Every test here encodes a failure mode that costs something real: a prompt that
only breaks when its lens runs, a corpus that silently stops hitting the cache,
a judge that emits a non-monotonic CDF, a percentile index that quietly does
nothing.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from forecaster.llm.client import PRICING, Usage, price
from forecaster.llm.prompt import PromptError, load, load_all
from forecaster.pipeline import c_structure
from forecaster.pipeline.g_judge import JudgeResponse
from forecaster.pipeline.v3_calibrate import (
    MIN_BUCKET,
    Regime,
    ResidualBook,
    _empirical_quantile,
    calibrate,
    coverage,
)
from forecaster.schemas import (
    Claim,
    Consensus,
    Distribution,
    Source,
    SourceKind,
)

AS_OF = date(2026, 8, 16)
SOURCE = Source(kind=SourceKind.FILING_8K, uri="https://sec.gov/x/8k.htm", as_of=AS_OF)


def _claim(cid: str, label: str, value: float, quote: str = "q") -> Claim:
    return Claim(
        id=cid, label=label, value=value, unit="USD", source=SOURCE, verbatim_quote=quote
    )


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #


def test_every_prompt_parses():
    """A prompt that only fails when its lens runs is a prompt that fails at
    14:00 on the day, three stages deep, with a stack trace about a dict key."""
    prompts = load_all()
    assert len(prompts) >= 10
    for name, prompt in prompts.items():
        assert prompt.id == name
        assert prompt.version >= 1
        assert prompt.system.strip() and prompt.user.strip()


def test_agent_count_matches_every_surface_that_states_it():
    """"How many agents are there" is answered on four surfaces, and they drifted.

    An agent is defined in exactly one way in this repo — a component with a
    versioned prompt in llm/prompts/ — because that is checkable rather than
    asserted. The README, the /agents sheet and the /system drawings all print a
    number, and at one point three of them said eleven by counting the Mechanical
    lens, which has no prompt and no model in it.

    Counting Mechanical as an agent destroys the only distinction on those pages
    worth making: every stage that can hallucinate is checked by one that cannot.
    So the count is pinned here, and the UI derives its own from the same rule.
    """
    prompts = load_all()
    assert len(prompts) == 10, (
        f"the agent roster changed: {sorted(prompts)}. Update the count on the "
        f"/agents sheet, the /system legend and the README in the same commit, "
        f"or they will disagree on a projector."
    )
    assert "mechanical" not in prompts, (
        "the Mechanical lens must not acquire a prompt file — it is arithmetic, "
        "and that is the point of it"
    )
    from forecaster.cli import AGENT_LAYERS

    assert set(AGENT_LAYERS) == set(prompts), (
        f"cli.AGENT_LAYERS is out of step with the prompt files: "
        f"only in AGENT_LAYERS {set(AGENT_LAYERS) - set(prompts)}, "
        f"only in prompts {set(prompts) - set(AGENT_LAYERS)}"
    )


def test_unknown_prompt_lists_what_is_available():
    with pytest.raises(PromptError) as err:
        load("lens_vibes")
    assert "lens_guidance" in str(err.value)


def test_missing_variable_refuses_to_render():
    """Rendering `{ticker}` into the prompt produces a confident, well-argued
    forecast for a company that does not exist."""
    prompt = load("lens_guidance")
    with pytest.raises(PromptError) as err:
        prompt.render({"ticker": "NVDA"})
    assert "missing variables" in str(err.value)


def test_editing_a_prompt_changes_its_fingerprint():
    """The cache key includes this. Without it you edit a prompt, re-run the
    backtest, and score the OLD prompt's cached answers — which looks like the
    edit did nothing and sends you tuning in the wrong direction."""
    prompt = load("judge")
    edited = prompt.__class__(**{**prompt.__dict__, "system": prompt.system + " "})
    assert edited.fingerprint != prompt.fingerprint


def test_judge_runs_on_the_expensive_tier_and_extraction_on_the_cheap_one():
    """Model tiering is the cost story on the slide; a prompt drifting to the
    wrong tier makes that story false."""
    assert load("judge").model_tier == "deep"
    assert load("extract_guidance").model_tier == "cheap"
    assert load("comparability").model_tier == "cheap"
    assert all(
        load(f"lens_{n}").model_tier == "mid"
        for n in ("guidance", "drivers", "margins", "forensics", "peer_read", "macro")
    )


# --------------------------------------------------------------------------- #
# evidence store
# --------------------------------------------------------------------------- #


def test_corpus_is_byte_identical_across_calls():
    """The corpus is the cached prefix for a six-lens fan-out. Any instability —
    an unsorted dict, a timestamp — silently drops the hit rate to zero and you
    pay full price six times with no error to tell you."""
    claims = [_claim(f"raw{i}", f"Metric {i}", float(i)) for i in range(12)]
    store = c_structure.build(claims)
    assert store.corpus() == store.corpus()
    assert c_structure.build(claims).corpus() == store.corpus()


def test_claims_are_renumbered_to_short_citable_ids():
    """A model asked to cite `sec:NVDA:2026Q1:Diluted EPS (GAAP)` truncates it,
    changes the case, or drops the colon — and the reconciler then correctly but
    uselessly drops the lens for a fabricated citation."""
    store = c_structure.build([_claim("sec:NVDA:2026Q1:Diluted EPS (GAAP)", "EPS", 2.4)])
    assert list(store.claims) == ["c1"]
    assert store.claims["c1"].id == "c1"


def test_corpus_sorts_c2_before_c10():
    store = c_structure.build([_claim(f"r{i}", f"M{i}", float(i)) for i in range(12)])
    body = store.corpus()
    assert body.index("\nc2.") < body.index("\nc10.")


def test_duplicate_claims_are_deduped_and_logged():
    """Acquisition hits the same fact from several sources. Seven copies of the
    share count is seven times the corpus cost for no extra information."""
    same = [
        _claim("a", "Diluted shares", 2_500.0),
        _claim("b", "Diluted shares", 2_500.0),
    ]
    store = c_structure.build(same)
    assert len(store.claims) == 1
    assert len(store.dropped) == 1


def test_fabricated_citation_is_reported_not_skipped():
    """A lens citing evidence that does not exist must reach the reconciler as a
    failure. Quietly dropping the unknown id would let an unfalsifiable number
    through with a citation list that looks fine."""
    store = c_structure.build([_claim("a", "Revenue", 44_000.0)])
    found, unknown = store.resolve(["c1", "c99"])
    assert [c.id for c in found] == ["c1"]
    assert unknown == ["c99"]
    assert "fabricated" in store.cited_block(["c99"])


def test_empty_blocks_say_so_rather_than_rendering_blank():
    """A blank block invites the model to fill the gap from memory. An explicit
    'not available' invites it to abstain, which is the correct answer."""
    assert "no guidance" in c_structure.guidance_block([])
    assert "no guided-range history" in c_structure.landing_block(None)
    assert "no consensus" in c_structure.consensus_block(None)
    assert "every lens reached you" in c_structure.dropped_block({})


# --------------------------------------------------------------------------- #
# judge
# --------------------------------------------------------------------------- #


def test_judge_rejects_a_non_monotonic_cdf():
    """A non-monotonic CDF is not a distribution. Left alone it flows into
    calibration and produces intervals that are nonsense in a way no chart
    reveals."""
    with pytest.raises(ValidationError) as err:
        JudgeResponse(
            median_eps=2.4,
            mean_eps=2.4,
            quantiles={"0.1": 2.6, "0.25": 2.5, "0.5": 2.4, "0.75": 2.3, "0.9": 2.2},
            rationale="x",
        )
    assert "monotonically increasing" in str(err.value)


def test_judge_rejects_missing_quantiles():
    with pytest.raises(ValidationError):
        JudgeResponse(
            median_eps=2.4, mean_eps=2.4, quantiles={"0.5": 2.4}, rationale="x"
        )


def test_judge_accepts_a_well_formed_distribution():
    response = JudgeResponse(
        median_eps=2.40,
        mean_eps=2.42,
        quantiles={"0.1": 2.1, "0.25": 2.3, "0.5": 2.4, "0.75": 2.5, "0.9": 2.8},
        rationale="guidance carried it",
    )
    assert response.quantiles["0.9"] > response.quantiles["0.1"]


# --------------------------------------------------------------------------- #
# calibration
# --------------------------------------------------------------------------- #


def test_empirical_quantile_uses_the_correct_percentile_index():
    """`int(p * n)` is not a percentile index. For n=20, p=0.95 it returns 19 —
    which IS the maximum — so the 95th percentile equals the max and nothing is
    ever excluded. This is the same bug that made winsorize a silent no-op."""
    values = [float(i) for i in range(20)]
    assert _empirical_quantile(values, 0.95) == 18.0
    assert _empirical_quantile(values, 0.95) != max(values)


def test_thin_regime_falls_back_to_the_pooled_book():
    """Eight residuals cannot tell you where the 10th percentile is. Using them
    anyway produces a confident interval built on sampling noise."""
    book = ResidualBook()
    thin = Regime("thin", "wide")
    for i in range(5):
        book.add(thin, 0.01 * i)
    for i in range(60):
        book.add(Regime("heavy", "tight"), 0.001 * i)

    sample, source = book.for_regime(thin)
    assert len(sample) == 65
    assert "pooled" in source


def test_calibration_is_skipped_and_says_so_when_there_is_no_backtest():
    """The honest failure. Silently returning the judge's own interval labelled
    as calibrated would make the reliability diagram a lie."""
    distribution = Distribution(
        median=2.4, mean=2.4,
        quantiles={"0.1": 2.2, "0.25": 2.3, "0.5": 2.4, "0.75": 2.5, "0.9": 2.6},
    )
    out, note = calibrate(distribution, ResidualBook(), None)
    assert out.calibrated is False
    assert "NOT CALIBRATED" in note


def test_calibration_preserves_the_centre_and_replaces_the_width():
    """This layer has no view on the level, only on the width. Moving the point
    estimate here would overwrite the judge's work with a statistical artefact."""
    book = ResidualBook()
    regime = Regime("normal", "tight")
    for i in range(MIN_BUCKET * 2):
        book.add(regime, (i % 11 - 5) * 0.01)

    narrow = Distribution(
        median=2.4, mean=2.4,
        quantiles={"0.1": 2.39, "0.25": 2.4, "0.5": 2.4, "0.75": 2.4, "0.9": 2.41},
    )
    out, note = calibrate(narrow, book, Consensus(eps=2.4, as_of=AS_OF))

    assert out.calibrated is True
    assert out.median == pytest.approx(2.4)
    assert out.quantiles["0.5"] == pytest.approx(2.4)
    band = out.quantiles["0.9"] - out.quantiles["0.1"]
    assert band > (narrow.quantiles["0.9"] - narrow.quantiles["0.1"])
    assert "backtest residuals" in note


def test_coverage_is_the_number_that_makes_calibration_falsifiable():
    """An 80% interval that covers 55% is a finding to report, not a chart to
    leave off the slide."""
    intervals = [(1.0, 3.0), (1.0, 3.0), (1.0, 3.0), (1.0, 3.0)]
    assert coverage(intervals, [2.0, 2.0, 2.0, 9.0]) == 0.75
    assert coverage([], []) == 0.0


def test_regime_buckets_on_coverage_and_dispersion():
    thin = Consensus(eps=1.0, n_analysts=4, as_of=AS_OF)
    heavy = Consensus(eps=1.0, n_analysts=61, eps_high=1.02, eps_low=0.98, as_of=AS_OF)
    assert Regime.of(thin).coverage == "thin"
    assert Regime.of(heavy).coverage == "heavy"
    assert Regime.of(heavy).dispersion == "tight"
    assert Regime.of(None).key() == "normal/tight"


# --------------------------------------------------------------------------- #
# cost accounting
# --------------------------------------------------------------------------- #


def test_cached_reads_cost_a_tenth_of_fresh_input():
    """The whole reason the corpus goes behind a cache breakpoint. If this
    multiplier is wrong the cost line on the slide is wrong."""
    fresh = Usage(input_tokens=1_000_000)
    cached = Usage(cache_read_input_tokens=1_000_000)
    assert price("claude-opus-5", fresh) == pytest.approx(5.00)
    assert price("claude-opus-5", cached) == pytest.approx(0.50)


def test_unknown_model_prices_at_the_most_expensive_tier():
    """An over-estimate is a safe failure; an under-estimate silently walks
    through the kill switch."""
    usage = Usage(input_tokens=1_000_000)
    assert price("claude-something-new", usage) >= max(p[0] for p in PRICING.values())


def test_usage_adds_across_calls():
    total = Usage(input_tokens=10, output_tokens=5, cost_usd=0.1) + Usage(
        input_tokens=3, output_tokens=2, cost_usd=0.2
    )
    assert (total.input_tokens, total.output_tokens) == (13, 7)
    assert total.cost_usd == pytest.approx(0.3)


# --------------------------------------------------------------------------- #
# the invariant
# --------------------------------------------------------------------------- #


def test_lenses_cannot_see_each_other():
    """Structural, not behavioural. `run_lens` has no parameter through which
    one lens's output could reach another, and `LensContext` carries inputs
    only. If they could see each other they would converge, and converging is
    how you accidentally rebuild consensus — which scores zero.
    """
    import inspect

    from forecaster.pipeline.e_lenses.base import LensContext, run_lens

    params = set(inspect.signature(run_lens).parameters)
    assert not {"lenses", "other_lenses", "peers_output", "prior_estimates"} & params

    fields = set(LensContext.__dataclass_fields__)
    assert "lens_outputs" not in fields
    # The working revenue handed to Margins must be an input block, never a
    # reference to the Drivers lens — otherwise the two agree by construction
    # and the judge reads that agreement as corroboration.
    assert LensContext.__dataclass_fields__["working_revenue"].type == "str"
