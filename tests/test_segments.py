"""Revenue disaggregation from the XBRL instance, for any ticker.

This replaced a hardcoded list of twelve companies whose driver decomposition had
been typed out by hand, and then replaced a first attempt that read SEC's rendered
HTML tables. Both earlier routes are worth remembering: the hand-written one
covered twelve names, and the HTML one reached 7 of 12 while costing a
filer-specific fix for each — a page-layout quirk per company, with an unbounded
supply of companies.

Reading the instance means the dimension is data. Every test here encodes a way a
parsed split is wrong while looking structured, which is the dangerous kind: a
lens builds a bottom-up forecast on it and never knows.
"""

from __future__ import annotations

import pytest

from forecaster.data import segments


def _context(cid: str, dims: str, start: str, end: str) -> str:
    return f"""
<context id="{cid}">
  <entity><identifier scheme="http://www.sec.gov/CIK">0001045810</identifier>
    <segment>{dims}</segment>
  </entity>
  <period><startDate>{start}</startDate><endDate>{end}</endDate></period>
</context>"""


def _member(axis: str, member: str) -> str:
    return (
        f'<xbrldi:explicitMember dimension="us-gaap:{axis}">{member}'
        "</xbrldi:explicitMember>"
    )


GEO = "StatementGeographicalAxis"
PRODUCT = "ProductOrServiceAxis"
CONSOL = "ConsolidationItemsAxis"
TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"

Q_NOW, Q_NOW_END = "2026-01-26", "2026-04-26"
Q_AGO, Q_AGO_END = "2025-01-27", "2025-04-27"


def _fact(cid: str, value: float, tag: str = TAG, attrs: str = "") -> str:
    return (
        f'<us-gaap:{tag}{attrs} contextRef="{cid}" unitRef="usd">'
        f'{value}</us-gaap:{tag}>'
    )


INSTANCE = "".join(
    [
        "<xbrl>",
        # Undimensioned consolidated revenue, both periods.
        _context("c-1", "", Q_NOW, Q_NOW_END),
        _context("c-2", "", Q_AGO, Q_AGO_END),
        # Geography, current and prior.
        _context("c-10", _member(GEO, "country:US"), Q_NOW, Q_NOW_END),
        _context("c-11", _member(GEO, "nvda:TaiwanMember"), Q_NOW, Q_NOW_END),
        _context("c-12", _member(GEO, "country:US"), Q_AGO, Q_AGO_END),
        # A parent and its two children, all on the same axis.
        _context("c-20", _member(PRODUCT, "nvda:DataCenterMember"), Q_NOW, Q_NOW_END),
        _context("c-21", _member(PRODUCT, "nvda:HyperscaleMember"), Q_NOW, Q_NOW_END),
        _context("c-24", _member(PRODUCT, "nvda:AICloudsMember"), Q_NOW, Q_NOW_END),
        _context("c-22", _member(PRODUCT, "nvda:EdgeMember"), Q_NOW, Q_NOW_END),
        # The same product member again, qualified by an axis that does not split
        # anything. Keyed on the context this would double-count.
        _context(
            "c-23",
            _member(PRODUCT, "nvda:EdgeMember")
            + _member(CONSOL, "us-gaap:OperatingSegmentsMember"),
            Q_NOW,
            Q_NOW_END,
        ),
        _fact("c-1", 100.0),
        _fact("c-2", 60.0),
        _fact("c-10", 80.0),
        _fact("c-11", 20.0),
        _fact("c-12", 50.0),
        _fact("c-20", 90.0),
        _fact("c-21", 60.0),
        _fact("c-24", 30.0),
        _fact("c-22", 10.0),
        _fact("c-23", 10.0),
        "</xbrl>",
    ]
)


def _lines():
    return segments.from_instance(INSTANCE, "https://example.test/x_htm.xml")


# --------------------------------------------------------------------------- #
# the axis is the classification
# --------------------------------------------------------------------------- #


def test_the_dimension_axis_says_what_kind_of_split_it_is():
    """No report titles, no table layouts, no filer-specific naming. This is the
    taxonomy's own classification and it is identical for every filer, which is
    the entire reason for reading the instance instead of the rendering."""
    kinds = {line.kind for line in _lines()}

    assert kinds == {"geography", "product"}


def test_member_names_are_made_readable_without_being_invented():
    lines = {line.label for line in _lines()}

    assert "Data Center" in lines
    assert "Taiwan" in lines
    # A two-letter country code is left alone: expanding it needs a lookup table
    # and a wrong expansion is worse than the code.
    assert "US" in lines


def test_the_prior_year_comes_from_the_same_document():
    """What makes segment growth defensible rather than reconstructed — the
    instance carries every period it reports, so no join across filings."""
    us = next(line for line in _lines() if line.label == "US")

    assert us.prior_value == 50.0
    assert us.growth == pytest.approx(80 / 50 - 1)


def test_a_member_with_no_comparative_has_no_growth_rather_than_a_wrong_one():
    """A segment that did not exist a year ago must not be paired with an
    unrelated member's figure."""
    taiwan = next(line for line in _lines() if line.label == "Taiwan")

    assert taiwan.prior_value is None
    assert taiwan.growth is None


# --------------------------------------------------------------------------- #
# the two bugs that cost most of the coverage
# --------------------------------------------------------------------------- #


def test_an_ignorable_second_axis_does_not_disqualify_a_fact():
    """Exxon, P&G and Coca-Cola tag segment revenue against BOTH the segment axis
    and `ConsolidationItemsAxis`. Requiring exactly one dimension threw every one
    of those facts away and three filers returned nothing at all."""
    contexts = segments.parse_contexts(INSTANCE)

    assert contexts["c-23"].axis == PRODUCT
    assert contexts["c-23"].member == "nvda:EdgeMember"


def test_the_same_member_reaching_us_twice_is_counted_once():
    """P&G reports each segment plainly and again qualified by the consolidation
    axis. Keyed on the context those are two facts, the members double, no subset
    reconciles, and the whole split is discarded — the company looks like it
    discloses nothing."""
    edge = [line for line in _lines() if line.label == "Edge"]

    assert len(edge) == 1


def test_contextref_is_found_wherever_it_sits_in_the_tag():
    """Microsoft emits `id=` before `contextRef=`. A pattern assuming contextRef
    came first matched none of its revenue facts, and the filer with the cleanest
    segment tagging in the sample looked like it had no revenue at all."""
    reordered = INSTANCE.replace(
        f'<us-gaap:{TAG} contextRef="c-10"',
        f'<us-gaap:{TAG} id="f-99" contextRef="c-10"',
    )

    lines = segments.from_instance(reordered, "u")

    assert any(line.label == "US" for line in lines)


# --------------------------------------------------------------------------- #
# reconciling, which is what makes it usable
# --------------------------------------------------------------------------- #


def test_a_parent_listed_beside_its_children_is_collapsed():
    """An axis is a hierarchy flattened into members. NVDA tags Data Center at
    75,246 and Hyperscale and AI Clouds beneath it, siblings as far as the axis
    is concerned — summing every member double-counts. Nothing in the taxonomy
    says which is which; arithmetic does."""
    kept, notes = segments.reconcile(_lines(), 100.0)
    products = {line.label for line in kept if line.kind == "product"}

    # Data Center (90) = Hyperscale (60) + AI Clouds (30). Both {Data Center,
    # Edge} and {Hyperscale, AI Clouds, Edge} reconcile to 100; the finer split
    # is the better driver tree, so ties break toward more members.
    assert products == {"Hyperscale", "AI Clouds", "Edge"}
    assert any("double-count" in note for note in notes)


def test_the_consolidated_revenue_comes_from_the_same_document_and_period():
    """Reconciling against the latest quarter from `History` instead compares an
    ANNUAL segment split to a QUARTERLY total whenever the most recent filing is
    a 10-K. Exxon, P&G and Coca-Cola all extracted their members correctly and
    had every one discarded on that mismatch."""
    assert segments.consolidated_revenue(INSTANCE, Q_NOW) == 100.0


def test_the_largest_undimensioned_figure_wins():
    """UnitedHealth tags a total and several components of it against the same
    context. Taking the first found returned a component, against which no split
    could possibly reconcile."""
    with_component = INSTANCE.replace(
        _fact("c-1", 100.0), _fact("c-1", 30.0) + _fact("c-1", 100.0)
    )

    assert segments.consolidated_revenue(with_component, Q_NOW) == 100.0


def test_a_single_member_is_not_a_decomposition():
    """The consolidation axis tags the CONSOLIDATED total as
    `OperatingSegmentsMember`, which reconciles perfectly while saying nothing."""
    one = [
        segments.SegmentLine(
            kind="segment", label="All of it", value=100.0, prior_value=None,
            unit="USD", period_label=Q_NOW, prior_period_label="", report="",
            source_uri="u",
        )
    ]

    kept, notes = segments.reconcile(one, 100.0)

    assert kept == []
    assert any("single member" in note for note in notes)


def test_a_split_that_cannot_reconcile_is_dropped_with_its_reason():
    """A driver tree missing a third of the revenue is worse than no driver tree,
    because a lens will build on it. Exxon and UnitedHealth end here, and that is
    the designed outcome rather than a failure."""
    partial = [
        segments.SegmentLine(
            kind="product", label=f"Part {i}", value=10.0, prior_value=None,
            unit="USD", period_label=Q_NOW, prior_period_label="", report="",
            source_uri="u",
        )
        for i in range(3)
    ]

    kept, notes = segments.reconcile(partial, 100.0)

    assert kept == []
    assert any("no subset" in note for note in notes)


def test_customer_concentration_is_not_required_to_sum_to_revenue():
    """A concentration disclosure names the customers above a threshold. It is
    not meant to be exhaustive, and rejecting it for that would discard the one
    disclosure saying who actually buys."""
    named = [
        segments.SegmentLine(
            kind="concentration", label="Customer A", value=15.0, prior_value=None,
            unit="USD", period_label=Q_NOW, prior_period_label="", report="",
            source_uri="u",
        )
    ]

    kept, _ = segments.reconcile(named, 100.0)

    assert len(kept) == 1


# --------------------------------------------------------------------------- #
# what it hands downstream
# --------------------------------------------------------------------------- #


def test_the_geographic_split_is_the_fx_exposure():
    """The leg of the Mechanical lens written off as unavailable. A filer
    reporting 20% of revenue from Taiwan carries that much translation exposure,
    and it is in the same document as everything else."""
    kept, _ = segments.reconcile(_lines(), 100.0)

    mix = dict(segments.geo_mix(kept))

    assert mix["US"] == pytest.approx(0.8)
    assert sum(mix.values()) == pytest.approx(1.0)


def test_the_block_states_growth_beside_every_part():
    kept, _ = segments.reconcile(_lines(), 100.0)

    block = segments.to_block(kept)

    assert "US" in block and "YoY" in block


def test_an_empty_parse_renders_as_nothing_rather_than_a_heading():
    assert segments.to_block([]) == ""


def test_a_document_with_no_dimensioned_revenue_yields_nothing():
    assert segments.from_instance("<xbrl></xbrl>", "u") == []
