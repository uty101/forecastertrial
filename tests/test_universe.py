"""The prep-time universe, and the ways a lookup table quietly lies.

Nothing here is about whether the data is *good* — the peer lists are judgement
calls and a test cannot second-guess them. It is about the failure modes of
hand-maintained data feeding an automated pipeline, all of which share a shape:
the wrong answer looks exactly like the right one at the call site.
"""

from __future__ import annotations

import pytest

from forecaster.data.universe import (
    DEFAULT_MACRO,
    UNIVERSE,
    Company,
    profile,
)


def test_an_unprepared_company_cold_starts_instead_of_raising():
    """The whole point: the pipeline runs on a ticker nobody prepared for.

    On the day we are handed a company at 10am, and the odds it is one of the
    twelve in here are low. A KeyError at `profile()` would take the run down
    before acquisition starts.
    """
    cold = profile("ZZZZ")

    assert cold.prepared is False
    assert cold.sector == "unknown"
    assert cold.peers == ()
    # Not empty: the Macro lens needs something to fetch, and a coarse rate and
    # inflation set is better than an abstention caused by an absent config.
    assert cold.macro_series == DEFAULT_MACRO


def test_prepared_is_reported_and_not_inferred_from_a_populated_field():
    """`prepared` is surfaced in the run manifest so a thin peer read on an
    unprepared name is explainable rather than mysterious. A caller that
    inferred it from `peers` being non-empty would be wrong in both directions:
    a prepared company can have no listed peers, and an unprepared one gets its
    peers from SIC later."""
    assert profile("NVDA").prepared is True
    assert profile("ZZZZ").prepared is False


def test_lookup_is_case_insensitive():
    """A lowercase ticker that silently cold-starts is the worst kind of bug —
    everything still works, just worse, and nothing in the output says so."""
    assert profile("nvda").sector == profile("NVDA").sector == "semiconductors"
    assert profile("nvda").prepared is True


def test_every_entry_is_filed_under_its_own_ticker():
    """A typo in a dict key hands back another company's value chain, and the
    peer read then reasons confidently about the wrong industry."""
    for key, company in UNIVERSE.items():
        assert key == company.ticker, f"{key} holds a Company for {company.ticker}"


def test_no_company_lists_itself_as_its_own_peer():
    """A self-peer is counted twice in a peer median and pulls the read-across
    towards the company we are trying to forecast — which is circular, and looks
    like corroboration."""
    for company in UNIVERSE.values():
        assert company.ticker not in company.value_chain()


def test_the_value_chain_dedupes_without_reordering():
    """A name appearing as both a peer and a customer must be fetched once.

    Twice means two filing pulls off the same budget and, worse, two votes in
    any median taken over the chain. No entry currently overlaps, which is
    exactly why this is a constructed case: the invariant has to hold for the
    entry somebody adds next, not just the ones already there.
    """
    overlapping = Company(
        ticker="X", name="X", sector="s", fiscal_quarter_end="calendar",
        peers=("A", "B"), suppliers=("B",), customers=("C", "A"),
    )

    assert overlapping.value_chain() == ("A", "B", "C")


def test_a_prepared_company_with_no_macro_series_still_gets_the_default():
    """An empty tuple would reach the Macro lens as "nothing to fetch", and the
    lens would abstain — reported as no macro signal rather than as missing
    configuration. Those are different findings."""
    silent = Company(
        ticker="Y", name="Y", sector="s", fiscal_quarter_end="calendar",
        macro_series=(),
    )
    UNIVERSE["Y"] = silent
    try:
        assert profile("Y").macro_series == DEFAULT_MACRO
    finally:
        del UNIVERSE["Y"]


@pytest.mark.parametrize("ticker", sorted(UNIVERSE))
def test_every_prepared_company_carries_a_driver_decomposition(ticker: str):
    """The warm start is worth having only if it says something. An entry with
    an empty `drivers` string is a company we did no preparation for, listed as
    though we had."""
    assert profile(ticker).drivers.strip(), f"{ticker} has no driver decomposition"
