"""The non-GAAP bridge extractor — the trap CLAUDE.md calls the silent killer.

Consensus is non-GAAP, XBRL is GAAP, the median DJIA gap was 31%, and forecasting
on the wrong basis produces a miss in the SAME DIRECTION every quarter. That does
not look like a bug; it looks like a model that is simply bad, which is why the
tests here are mostly about refusing to produce a bridge rather than producing
one:

- a quote that is not in the release drops its item
- a bridge that does not tie to the company's own reported figure comes back
  with the failure attached, never silently used
- a reconciliation printed only in absolute dollars is refused outright rather
  than divided by an inferred share count

The one that has to be right in the other direction is sign convention. An
excluded COST raises non-GAAP EPS; an excluded GAIN lowers it. Getting that
backwards on a single line still ties if two errors cancel, so it is tested on a
release that has both.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.llm.client import LLMError
from forecaster.model.bridge import RECURRENCE_THRESHOLD, Bridge, BridgeItem
from forecaster.pipeline import extract

RELEASE = """
NVIDIA CORPORATION
RECONCILIATION OF GAAP TO NON-GAAP FINANCIAL MEASURES
(In millions, except per share data)

Diluted earnings per share (GAAP) $ 0.81
Stock-based compensation expense 0.49
Amortization of acquisition-related intangible assets 0.03
Gain on sale of investment (0.11)
Income tax effect of non-GAAP adjustments (0.09)
Diluted earnings per share (non-GAAP) $ 1.13
"""


class FakeClient:
    def __init__(self, response=None, error: str | None = None):
        self.response = response
        self.error = error
        self.calls: list = []

    def call(self, prompt, schema=None, variables=None, **kwargs):
        self.calls.append((prompt, variables or {}))
        if self.error:
            raise LLMError(self.error)
        return self.response, {}


def item(label, per_share, quote):
    return extract.ExtractedItem(label=label, per_share=per_share, quote=quote)


def full_response(**overrides):
    base = {
        "found": True,
        "period": "Q2 FY2026",
        "eps_gaap": 0.81,
        "eps_non_gaap": 1.13,
        "items": [
            item("Stock-based compensation expense", 0.49,
                 "Stock-based compensation expense 0.49"),
            item("Amortization of acquisition-related intangible assets", 0.03,
                 "Amortization of acquisition-related intangible assets 0.03"),
            item("Gain on sale of investment", -0.11,
                 "Gain on sale of investment (0.11)"),
            item("Income tax effect of non-GAAP adjustments", -0.09,
                 "Income tax effect of non-GAAP adjustments (0.09)"),
        ],
    }
    base.update(overrides)
    return extract.ExtractedBridge(**base)


def run(response=None, error=None, document=RELEASE):
    client = FakeClient(response, error)
    return client, extract.extract_bridge(
        client, "NVDA", document, "https://sec.gov/ex99.htm", date(2026, 8, 27)
    )


# ---- the happy path, and the sign convention inside it ------------------- #


def test_a_release_that_ties_produces_a_usable_bridge():
    _, (built, claims, rejections) = run(full_response())

    assert rejections == []
    assert len(claims) == 4
    assert built.eps_gaap == pytest.approx(0.81)
    assert built.eps_non_gaap == pytest.approx(1.13)
    # The premium is the adjustment over GAAP — 32c on 81c, not 32%.
    assert built.gap_pct == pytest.approx(0.32 / 0.81, abs=0.01)


def test_an_excluded_gain_lowers_non_gaap_and_an_excluded_cost_raises_it():
    """The sign convention, on a release that carries both directions.

    Two sign errors cancel and still tie, so this checks the individual lines
    rather than only the total.
    """
    _, (built, _, _) = run(full_response())

    by_label = {i.label: i.per_share for i in built.items}
    assert by_label["Stock-based compensation expense"] > 0
    assert by_label["Gain on sale of investment"] < 0
    # And the tax effect of add-backs is itself a reconciling item — leave it
    # out and the bridge misses by nine cents in one direction, every quarter.
    assert by_label["Income tax effect of non-GAAP adjustments"] < 0


# ---- the refusals -------------------------------------------------------- #


def test_an_invented_quote_drops_its_item_and_breaks_the_tie_visibly():
    response = full_response(
        items=[
            item("Stock-based compensation expense", 0.49,
                 "Stock-based compensation expense 0.49"),
            item("Restructuring", 0.20,
                 "Restructuring charges of $0.20 per share were incurred."),
        ]
    )
    _, (built, claims, rejections) = run(response)

    assert len(claims) == 1
    assert any("quote not found" in r for r in rejections)
    # The dropped line makes the bridge fail to tie, and that failure is
    # reported rather than absorbed — a bridge missing an item is a
    # one-directional error, the worst kind.
    assert any("DOES NOT TIE" in r for r in rejections)


def test_a_bridge_that_does_not_tie_is_returned_with_the_failure_attached():
    """Returned, not discarded: the gap itself is information, and a bridge
    that was made to tie would be undetectable."""
    _, (built, _, rejections) = run(full_response(eps_non_gaap=1.40))

    assert built is not None
    assert any("DOES NOT TIE" in r for r in rejections)


def test_absolute_dollar_reconciliations_are_refused_not_converted():
    response = full_response(units_note="per-share column not presented")
    _, (built, claims, rejections) = run(response)

    assert built is None
    assert claims == []
    assert "absolute dollars" in rejections[0]


def test_a_gaap_only_release_is_a_legitimate_answer_not_an_error():
    _, (built, claims, rejections) = run(
        extract.ExtractedBridge(found=False)
    )

    assert built is None
    assert rejections == []


def test_a_failed_call_degrades_rather_than_raising():
    _, (built, _, rejections) = run(error="503")

    assert built is None
    assert "bridge extraction failed" in rejections[0]


def test_an_empty_document_never_reaches_the_model():
    client, (built, _, rejections) = run(full_response(), document="   ")

    assert client.calls == []
    assert built is None
    assert rejections == ["empty document"]


# ---- recurrence ---------------------------------------------------------- #


def make(label, per_share=0.4):
    return BridgeItem(label=label, per_share=per_share, note="test fixture")


def test_an_item_excluded_every_quarter_stops_being_unusual():
    """Four quarters of the same one-off is a permanent cost moved below the
    line — which is the finding, not the bookkeeping."""
    bridges = [
        Bridge(eps_gaap=1.0, items=[make("Stock-based compensation")])
        for _ in range(RECURRENCE_THRESHOLD)
    ]
    extract.count_recurrence(bridges)

    assert all(b.items[0].is_recurring for b in bridges)
    assert bridges[0].recurring_adjustment == pytest.approx(0.4)


def test_a_genuine_one_off_stays_a_one_off():
    bridges = [
        Bridge(eps_gaap=1.0, items=[make("Stock-based compensation")])
        for _ in range(RECURRENCE_THRESHOLD)
    ]
    bridges[0].items = [*bridges[0].items, make("Litigation settlement", 0.15)]
    extract.count_recurrence(bridges)

    labels = {i.label: i.is_recurring for i in bridges[0].items}
    assert labels["Stock-based compensation"] is True
    assert labels["Litigation settlement"] is False
    assert bridges[0].recurring_adjustment == pytest.approx(0.4)


def test_wording_drift_across_quarters_still_counts_as_one_line():
    """'Stock-based compensation expense' and 'Stock-Based Compensation' are the
    same line. Matching on the raw string would reset the count every time IR
    retyped the table."""
    bridges = [
        Bridge(eps_gaap=1.0, items=[make("Stock-based compensation expense")]),
        Bridge(eps_gaap=1.0, items=[make("Stock-Based Compensation")]),
        Bridge(eps_gaap=1.0, items=[make("Stock based compensation costs")]),
        Bridge(eps_gaap=1.0, items=[make("Stock-based compensation")]),
    ]
    extract.count_recurrence(bridges)

    assert all(b.items[0].quarters_recurring == RECURRENCE_THRESHOLD for b in bridges)


def test_recurrence_preserves_the_claim_that_makes_the_item_citable():
    """The rebuild in count_recurrence must not drop provenance — an item
    without its claim is exactly the unsourced adjustment BridgeItem refuses
    to be constructed with."""
    bridges = [Bridge(eps_gaap=1.0, items=[make("Stock-based compensation")])]
    extract.count_recurrence(bridges)

    assert bridges[0].items[0].note == "test fixture"
