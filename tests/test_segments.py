"""Revenue disaggregation from the filing, for any ticker.

This replaced a hardcoded list of twelve companies whose driver decomposition
had been written out by hand. Every test here encodes a way a parsed segment
table is wrong while looking structured — which is the dangerous kind, because a
lens will build a bottom-up forecast on it and never know.
"""

from __future__ import annotations

from forecaster.data import segments

# The shape SEC's renderer emits. Trimmed, but the structure is verbatim: a
# caption carrying the units, a header row of periods, an abstract row heading
# each block, then a member row with no figures and its values beneath.
GEO_HTML = """
<table>
<tr><th class="tl" colspan="3">Revenue by Geographic Regions (Details) - USD ($)
    $ in Millions</th></tr>
<tr><th>&nbsp;</th><th>Apr. 26, 2026</th><th>Apr. 27, 2025</th></tr>
<tr><td>Revenues</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenue</td><td>$ 81,615</td><td>$ 44,062</td></tr>
<tr><td>United States</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenues</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenue</td><td>63,769</td><td>25,685</td></tr>
<tr><td>Taiwan</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenues</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenue</td><td>12,006</td><td>7,648</td></tr>
<tr><td>China (including Hong Kong)</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenues</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenue</td><td>4,550</td><td>9,659</td></tr>
<tr><td>Other</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenues</td><td>&#160;</td><td>&#160;</td></tr>
<tr><td>Revenue</td><td>1,290</td><td>1,070</td></tr>
</table>
"""

SUMMARY_XML = """
<FilingSummary>
 <MyReports>
  <Report><ShortName>Segment Information</ShortName>
          <HtmlFileName>R20.htm</HtmlFileName></Report>
  <Report><ShortName>Segment Information - Schedule of Revenue by Geographic
          Regions (Details)</ShortName>
          <HtmlFileName>R64.htm</HtmlFileName></Report>
  <Report><ShortName>Segment Information - Narrative (Details)</ShortName>
          <HtmlFileName>R61.htm</HtmlFileName></Report>
  <Report><ShortName>Loans - By Portfolio Segment (Details)</ShortName>
          <HtmlFileName>R31.htm</HtmlFileName></Report>
  <Report><ShortName>Segment Information - Schedule of Revenue by Market
          Platform (Details)</ShortName>
          <HtmlFileName>R66.htm</HtmlFileName></Report>
 </MyReports>
</FilingSummary>
"""


def _line(kind, label, value, prior=None) -> segments.SegmentLine:
    return segments.SegmentLine(
        kind=kind, label=label, value=value, prior_value=prior, unit="USD",
        period_label="Apr. 26, 2026", prior_period_label="Apr. 27, 2025",
        report="test", source_uri="https://example.test/R1.htm",
    )


# --------------------------------------------------------------------------- #
# finding the right table
# --------------------------------------------------------------------------- #


def test_it_finds_the_tagged_detail_pages_and_skips_the_prose():
    """SEC renders each note three times — narrative, tables, tagged detail.
    Only the last carries machine-readable numbers; matching without the
    `(Details)` suffix returns a page of prose."""
    found = segments.find_reports(SUMMARY_XML)
    paths = {path for _, _, path in found}

    assert "R64.htm" in paths
    assert "R66.htm" in paths
    assert "R20.htm" not in paths, "the un-suffixed note is prose"


def test_a_narrative_details_page_is_excluded():
    """It carries facts like "number of reportable segments: 2", which parse as
    a revenue line of $2 sitting beside figures in millions."""
    found = segments.find_reports(SUMMARY_XML)

    assert "R61.htm" not in {path for _, _, path in found}


def test_a_loan_portfolio_is_not_a_business_segment():
    """Banks overload the word. A loan book parsed as a revenue split produces a
    decomposition that does not sum to revenue and is wrong in a way that looks
    structured."""
    found = segments.find_reports(SUMMARY_XML)

    assert "R31.htm" not in {path for _, _, path in found}


def test_specific_patterns_beat_the_generic_one():
    """The ordering bug that cost the FX exposure.

    NVDA titles every note "Segment Information — …", so a generic
    `segment information` pattern checked first claims the GEOGRAPHIC table too
    and it disappears into the segment bucket. Matching stops at the first hit,
    so narrow patterns have to be tested before the catch-all.
    """
    found = dict((path, kind) for kind, _, path in segments.find_reports(SUMMARY_XML))

    assert found["R64.htm"] == "geography"
    assert found["R66.htm"] == "product"


# --------------------------------------------------------------------------- #
# reading the table
# --------------------------------------------------------------------------- #


def test_a_member_row_names_the_figures_beneath_it():
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")
    labels = [line.label for line in lines]

    assert labels == ["United States", "Taiwan", "China (including Hong Kong)", "Other"]


def test_a_bare_section_header_does_not_overwrite_the_member():
    """The bug that made the whole geographic table parse to nothing.

    The market-platform note heads each block with "Revenue from External
    Customer [Line Items]", which the bracket test catches. The geographic note
    heads it with a bare "Revenues", which it does not — and that one word
    overwrote the member on every row, so every region came back labelled
    "Revenues" and the table yielded no usable lines at all.
    """
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")

    assert lines, "the table parsed to nothing"
    assert not any(line.label.lower() in {"revenue", "revenues"} for line in lines)


def test_the_scale_in_the_caption_is_applied():
    """A table quoted in millions and read at face value is wrong by six orders
    of magnitude and internally consistent — the parts still sum to the total,
    so nothing downstream catches it."""
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")

    assert lines[0].value == 63_769_000_000.0


def test_the_prior_year_comparative_comes_from_the_same_table():
    """What makes segment growth defensible rather than reconstructed: the
    comparative is printed beside the figure in the filing, not derived by
    joining two documents."""
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")
    us = lines[0]

    assert us.prior_value == 25_685_000_000.0
    assert us.growth == 63_769 / 25_685 - 1


def test_a_declining_region_reports_a_negative_growth_rate():
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")
    china = next(line for line in lines if line.label.startswith("China"))

    assert china.growth < 0


# --------------------------------------------------------------------------- #
# reconciling, which is what makes it usable
# --------------------------------------------------------------------------- #


def test_a_parent_listed_beside_its_children_is_collapsed():
    """A rendered segment table is a hierarchy flattened into rows. NVDA lists
    Data Center at 75,246 and then Hyperscale and AI Clouds underneath it — all
    as siblings. Summing every row gives 156,861 against 81,615 of revenue.

    Nothing in the text says which is which. Arithmetic does: the finest subset
    that reconciles to reported revenue is the real decomposition.
    """
    group = [
        _line("product", "Data Center", 75_246),
        _line("product", "Hyperscale", 37_869),
        _line("product", "AI Clouds", 37_377),
        _line("product", "Edge Computing", 6_369),
    ]

    kept, notes = segments.reconcile(group, 81_615)
    labels = {line.label for line in kept}

    assert labels == {"Hyperscale", "AI Clouds", "Edge Computing"}
    assert any("double-count" in note for note in notes)


def test_a_split_that_reconciles_at_the_coarse_level_is_kept_whole():
    group = [
        _line("segment", "Products", 60_000),
        _line("segment", "Services", 21_615),
    ]

    kept, notes = segments.reconcile(group, 81_615)

    assert len(kept) == 2
    assert not notes


def test_a_split_that_cannot_reconcile_is_dropped_with_its_reason():
    """A driver tree missing a third of the revenue is worse than no driver
    tree, because a lens will build on it."""
    group = [
        _line("segment", "Depreciation", 997),
        _line("segment", "Operating income", 53_536),
        _line("segment", "Other segment items", 25_339),
    ]

    kept, notes = segments.reconcile(group, 81_615)

    assert kept == []
    assert any("no subset" in note for note in notes)


def test_customer_concentration_is_not_required_to_sum_to_revenue():
    """A concentration note lists the customers above a threshold. It is not
    meant to be exhaustive and rejecting it for that would throw away the one
    disclosure naming who actually buys the product."""
    group = [_line("concentration", "Customer A", 15_000)]

    kept, _ = segments.reconcile(group, 81_615)

    assert len(kept) == 1


def test_no_reported_revenue_means_nothing_is_trusted():
    """Without a target there is no way to tell a complete split from a partial
    one, and a partial one is the failure this whole check exists to catch."""
    kept, notes = segments.reconcile([_line("product", "A", 100)], None)

    assert kept == []
    assert notes


def test_a_table_too_wide_to_search_is_declined_rather_than_guessed():
    """A filer with more than eighteen rows in one disaggregation table is
    disclosing something other than a segment split."""
    group = [_line("segment", f"Row {i}", 1_000) for i in range(20)]

    kept, notes = segments.reconcile(group, 20_000)

    assert kept == []
    assert any("no subset" in note for note in notes)


# --------------------------------------------------------------------------- #
# what it hands downstream
# --------------------------------------------------------------------------- #


def test_the_geographic_split_is_the_fx_exposure():
    """The leg of the Mechanical lens written off as unavailable. A filer
    reporting 15% of revenue from Taiwan has that much translation exposure,
    and it is in the same document as everything else."""
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")

    mix = dict(segments.geo_mix(lines))

    import pytest

    assert mix["United States"] > 0.75
    assert sum(mix.values()) == pytest.approx(1.0)


def test_the_block_states_growth_beside_every_part():
    """Growth is the number the lens is being asked to forecast, and it came out
    of the filing rather than out of anyone's model."""
    lines = segments.parse_report(GEO_HTML, "geography", "geo", "u")

    block = segments.to_block(lines)

    assert "United States" in block
    assert "YoY" in block
    assert "% of total" in block


def test_an_empty_parse_renders_as_nothing_rather_than_a_heading():
    assert segments.to_block([]) == ""
