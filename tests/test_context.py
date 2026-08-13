"""Industry sizing, external exposure, and perception.

Three inputs that all bring a view on value into the model — and one of them
must never reach it. The tests are as much about that boundary as about the
arithmetic.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data import exposure, industry
from forecaster.pipeline.e_expect import perception as P


def _peer(ticker, revenue, prior=None):
    return industry.PeerRevenue(
        ticker=ticker, revenue=revenue, prior_revenue=prior
    )


def _industry(peers=None, company=None):
    return industry.build(
        "T",
        "3674",
        "Semiconductors",
        company or _peer("T", 100.0, 60.0),
        peers
        if peers is not None
        else [_peer("A", 100.0, 80.0), _peer("B", 50.0, 45.0), _peer("C", 50.0, 45.0)],
    )


# --------------------------------------------------------------------------- #
# industry — market growth against share change
# --------------------------------------------------------------------------- #


def test_growth_splits_into_market_and_share():
    """The split consensus forecasts around rather than through. Growing 60% in
    a market growing 55% is riding a wave that can stop; growing 60% in a market
    growing 8% is taking share from someone who will respond."""
    result = _industry()

    market, share = result.decompose()
    assert result.company.growth == pytest.approx(100 / 60 - 1)
    assert market == pytest.approx(300 / 230 - 1)
    assert share > 0, "revenue grew faster than the market, so share was gained"


def test_share_is_computed_against_the_filed_peer_set():
    result = _industry()

    assert result.size == 300.0
    assert result.share == pytest.approx(1 / 3)


def test_a_conglomerate_misfiled_under_a_narrow_code_is_excluded():
    """It would otherwise BE the market, and this company's share would collapse
    for a reason with nothing to do with competition."""
    result = _industry(
        peers=[
            _peer("A", 100.0),
            _peer("B", 50.0),
            _peer("C", 50.0),
            _peer("HUGE", 50_000.0),
        ]
    )

    assert all(p.ticker != "HUGE" for p in result.peers)
    assert any("misclassification" in note for note in result.excluded)


def test_too_few_peers_claims_nothing():
    """Share of a three-company set is noise, so nothing is offered rather than
    a thin number being presented as a measurement."""
    block = industry.to_block(_industry(peers=[_peer("A", 100.0)]))

    assert "fewer than three peers" in block


def test_the_block_says_the_level_is_less_reliable_than_the_trend():
    """SIC includes firms this company does not compete with and misses
    competitors filed elsewhere. A reader taking the share LEVEL as market share
    has been misled."""
    block = industry.to_block(_industry())

    assert "TREND" in block
    assert "coarse boundary" in block


def test_share_falling_while_revenue_grows_is_visible():
    """The most important thing this can report, and it is invisible in the
    headline number."""
    result = _industry(
        company=_peer("T", 110.0, 100.0),
        peers=[
            _peer("A", 200.0, 100.0),
            _peer("B", 100.0, 50.0),
            _peer("C", 100.0, 50.0),
        ],
    )

    assert result.share_change < 0
    assert result.peer_growth_median > result.company.growth


# --------------------------------------------------------------------------- #
# exposure — every series names the line it moves
# --------------------------------------------------------------------------- #


GEO = [("United States", 0.78), ("Taiwan", 0.15), ("Atlantis", 0.07)]


def test_geographic_revenue_becomes_demand_weighted_growth():
    """Specific to the company rather than to its sector, and it changes when
    the mix changes — which is exactly when a top-down view stops working."""
    result = exposure.build(
        "T",
        [("United States", 0.8), ("Japan", 0.2)],
        "3674",
        {"GDPC1": 0.02, "JPNRGDPEXP": 0.10},
    )

    assert result.weighted_growth() == pytest.approx(0.8 * 0.02 + 0.2 * 0.10)


def test_an_unmappable_region_is_excluded_and_named():
    """Not assumed to grow at the world average. A weighted rate covering 60% of
    revenue is a different claim from one covering 98%, and the number alone
    cannot say which it is."""
    result = exposure.build(
        "T", GEO, "3674", {"GDPC1": 0.02, "TWNPROINDMISMEI": 0.05}
    )

    assert result.unmapped_regions == ["Atlantis"]
    assert result.covered == pytest.approx(0.93)
    assert "UNMAPPED" in exposure.to_block(result)


def test_regions_are_matched_loosely_because_filers_name_them_anyhow():
    for label in ("US", "United States", "Americas", "North America"):
        assert exposure.series_for_region(label)[0] == "GDPC1", label


def test_input_costs_come_from_the_filed_industry_code():
    """Coarse and derived beats precise and prepared: it works on a ticker
    nobody thought about."""
    chemicals = {s for s, _ in exposure.inputs_for_sic("2834")}
    airlines = {s for s, _ in exposure.inputs_for_sic("4512")}

    assert "WPU06" in chemicals
    assert "DCOILWTICO" in airlines
    assert chemicals != airlines


def test_an_unknown_industry_still_gets_a_commodity_read():
    assert exposure.inputs_for_sic("9999") == exposure.UNIVERSAL_INPUTS


def test_every_exposure_names_the_driver_it_moves():
    """The discipline the module exists for. A series with no line attached is
    commentary."""
    result = exposure.build("T", GEO, "3674", {})

    assert all(e.drives == "revenue_growth" for e in result.geography)
    assert all(e.drives == "gross_margin" for e in result.inputs)


def test_an_input_cost_carries_no_weight_because_none_is_disclosed():
    """Filers do not break out what fraction of COGS a commodity is, and
    inventing that fraction is the whole error this module exists to avoid."""
    result = exposure.build("T", GEO, "3674", {"PCOPPUSDM": 0.14})

    copper = next(e for e in result.inputs if e.series_id == "PCOPPUSDM")
    assert copper.weight is None
    assert copper.contribution is None
    assert "ize it from the evidence" in exposure.to_block(result)


# --------------------------------------------------------------------------- #
# perception — the one input that must not reach the model
# --------------------------------------------------------------------------- #


def _read(stance, conviction=0.8, subject="company"):
    return P.Read(
        subject=subject,
        stance=stance,
        conviction=conviction,
        claim="c",
        quote="q",
        url="u",
        published=date(2026, 8, 1),
    )


def test_a_one_sided_narrative_shrinks_conviction_and_nothing_else():
    """It does not say the estimate is wrong. It says being right earns less and
    being wrong costs more, which is a position-sizing fact — so it moves lambda
    and never the number."""
    crowded = P.Perception("T", reads=[_read("bullish") for _ in range(6)])

    multiplier, why = crowded.lambda_multiplier()
    assert multiplier < 1.0
    assert "priced" in why


def test_contested_coverage_raises_conviction():
    """A surprise has somewhere to go, so a differentiated estimate is worth
    more."""
    split = P.Perception(
        "T",
        reads=[_read("bullish", 1.0) for _ in range(3)]
        + [_read("bearish", 1.0) for _ in range(3)],
    )

    assert split.lambda_multiplier()[0] > 1.0


def test_dispersion_is_reported_separately_from_direction():
    """Article counts and word polarity produce a number that measures
    publication volume — coverage spikes before every print regardless of
    direction."""
    split = P.Perception(
        "T",
        reads=[_read("bullish", 1.0) for _ in range(3)]
        + [_read("bearish", 1.0) for _ in range(3)],
    )

    assert split.tilt() == pytest.approx(0.0)
    assert split.dispersion() > 0.9


def test_too_few_items_claims_nothing():
    thin = P.Perception("T", reads=[_read("bullish")])

    assert thin.tilt() is None
    assert "not a signal" in P.to_block(thin)


def test_the_block_frames_agreement_as_weak_evidence():
    """A lens told "sentiment is bullish" drifts bullish. A judge told "the
    narrative is unanimous, so agreement with it is weak evidence" does
    something useful with the same fact."""
    crowded = P.Perception("T", reads=[_read("bullish") for _ in range(6)])

    block = P.to_block(crowded)

    assert "ALREADY BELIEVED" in block
    assert "WEAKER evidence" in block
    assert "never the estimate" in block
