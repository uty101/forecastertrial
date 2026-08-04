"""The three statements laid out the way a model lays them out.

Almost everything here is about the annual column, because that is where a
statement grid goes wrong in a way that survives every other check: the number
looks plausible, ties to nothing, and nobody notices.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.history import History, Observation
from forecaster.model import grid

AS_OF = date(2026, 8, 4)

# Two clean fiscal years plus one quarter of a third, so the partial-year rules
# have something to be wrong about.
PERIODS = [
    ("2025Q1", 3), ("2025Q2", 6), ("2025Q3", 9), ("2025Q4", 12),
    ("2026Q1", 3), ("2026Q2", 6), ("2026Q3", 9), ("2026Q4", 12),
    ("2027Q1", 3),
]


def _history(values: dict[str, dict[str, float]]) -> History:
    """`values[key][period] = value`. Anything absent is simply not reported."""
    series: dict[str, list[Observation]] = {}
    for key, by_period in values.items():
        for period, value in by_period.items():
            fy, fp = int(period[:4]), period[4:]
            month = dict(PERIODS)[period]
            series.setdefault(key, []).append(
                Observation(
                    key=key, fy=fy, fp=fp, value=value, unit="USD",
                    period_end=date(fy, month, 28), filed=date(fy, month, 28),
                    form="10-Q", accession=f"000-{period}",
                )
            )
    return History("TEST", AS_OF, series, cik="0000000001")


def _cell(grids, statement: str, row_id: str, period: str):
    """The cell, or None — a row with nothing in it is dropped from the grid, so
    "absent row" and "empty cell" are the same answer to the caller."""
    row = next((r for r in grids[statement].rows if r.id == row_id), None)
    return row.cells.get(period) if row else None


# --------------------------------------------------------------------------- #
# the annual column is not one rule
# --------------------------------------------------------------------------- #


def test_flows_are_summed_across_the_four_quarters():
    history = _history({"revenue": {
        "2025Q1": 100.0, "2025Q2": 200.0, "2025Q3": 300.0, "2025Q4": 400.0,
    }})

    grids = grid.build(history, "annual")

    assert _cell(grids, "income", "revenue", "FY2025").value == 1000.0


def test_balances_take_the_closing_quarter_and_are_never_summed():
    """The error that stays internally consistent.

    Four quarters of a cash BALANCE summed gives a number that looks like a year
    of cash generation, sits happily on a balance sheet, and is meaningless. A
    balance is an instant; the year takes the last one.
    """
    history = _history({"cash": {
        "2025Q1": 100.0, "2025Q2": 120.0, "2025Q3": 140.0, "2025Q4": 160.0,
    }})

    grids = grid.build(history, "annual")

    assert _cell(grids, "balance", "cash", "FY2025").value == 160.0


def test_a_weighted_average_share_count_is_averaged_not_summed():
    """Neither rule applies: a weighted average does not add up, and taking Q4
    alone reports the year's exit count as its average. Averaging the four is the
    standard reconstruction, and it is derived rather than reported."""
    history = _history({
        "net_income": {p: 100.0 for p, _ in PERIODS[:4]},
        "diluted_shares": {
            "2025Q1": 100.0, "2025Q2": 98.0, "2025Q3": 96.0, "2025Q4": 94.0,
        },
    })

    grids = grid.build(history, "annual")
    cell = _cell(grids, "income", "diluted_shares", "FY2025")

    assert cell.value == pytest.approx(97.0)
    assert cell.origin == "derived", "an averaged figure must not read as reported"
    assert "not additive" in (cell.note or "")


def test_a_non_additive_item_missing_a_quarter_has_no_annual_figure():
    """Averaging three quarters and calling it the year is worse than a gap: it
    is a number nobody can reconcile to the 10-K. NVDA has exactly this — Q4 has
    no share count, because Q4 is derived by subtraction and EPS does not
    subtract."""
    history = _history({"diluted_shares": {
        "2025Q1": 100.0, "2025Q2": 98.0, "2025Q3": 96.0,
    }})

    grids = grid.build(history, "annual")
    cell = _cell(grids, "income", "diluted_shares", "FY2025")

    assert cell is None or cell.value is None


def test_a_part_finished_year_is_marked_incomplete():
    """The current fiscal year is partial by definition, and a partial year that
    renders identically to a full one is how a 25% figure gets read as a 100%
    one."""
    history = _history({"revenue": {p: 100.0 for p, _ in PERIODS}})

    grids = grid.build(history, "annual")
    periods = {p.id: p for p in grids["income"].periods}

    assert periods["FY2026"].complete is True
    assert periods["FY2027"].complete is False
    assert periods["FY2027"].quarters == 1


def test_growth_is_not_computed_against_a_part_finished_year():
    """NVDA's FY2027 held one quarter and printed −62.2% revenue growth. That is
    not a decline, it is three missing quarters."""
    history = _history({"revenue": {p: 100.0 for p, _ in PERIODS}})

    grids = grid.build(history, "annual")
    growth = _cell(grids, "income", "revenue_growth", "FY2027")

    assert growth is None or growth.value is None


def test_working_capital_days_scale_to_the_periods_actual_length():
    """A balance is a full instant even in a part-finished year while the flow is
    only the quarters filed. Against a fixed 365 that printed DSO of 182 for a
    company collecting in 65 — the balance right, the flow a quarter, the ratio
    three times reality."""
    history = _history({
        "revenue": {p: 100.0 for p, _ in PERIODS},
        "receivables": {p: 100.0 for p, _ in PERIODS},
    })

    grids = grid.build(history, "annual")
    full = _cell(grids, "balance", "dso", "FY2026").value
    partial = _cell(grids, "balance", "dso", "FY2027").value

    assert full == pytest.approx(91.25, abs=0.5)
    assert partial == pytest.approx(91.25, abs=0.5), "a partial year inflated DSO"


# --------------------------------------------------------------------------- #
# provenance is what sets the colour
# --------------------------------------------------------------------------- #


def test_a_reported_quarter_is_an_actual_and_carries_its_filing():
    """Blue means "we were told this". A blue cell with no filing behind it is an
    assertion wearing the colour of a fact."""
    history = _history({"revenue": {"2025Q1": 100.0}})

    grids = grid.build(history, "quarter")
    cell = _cell(grids, "income", "revenue", "2025Q1")

    assert cell.origin == "actual"
    assert cell.form == "10-Q"
    assert cell.filed == "2025-03-28"


def test_a_computed_row_is_derived_not_actual():
    history = _history({
        "revenue": {"2025Q1": 100.0},
        "gross_profit": {"2025Q1": 60.0},
    })

    grids = grid.build(history, "quarter")

    assert _cell(grids, "income", "gross_margin", "2025Q1").origin == "derived"
    assert _cell(grids, "income", "gross_margin", "2025Q1").value == pytest.approx(0.6)


def test_a_figure_arriving_from_another_statement_is_marked_as_a_link():
    """The distinction the whole layout exists to make. Net income on the cash
    flow statement is not an independent number — it is the income statement's,
    and a reader has to be able to see that without being told."""
    history = _history({"net_income": {"2025Q1": 100.0}, "cash": {"2025Q1": 50.0}})

    grids = grid.build(history, "quarter")

    assert _cell(grids, "cashflow", "net_income", "2025Q1").origin == "link"
    assert _cell(grids, "cashflow", "cash_close", "2025Q1").origin == "link"


def test_the_linkages_travel_with_the_row():
    """A reader's first question about a linked cell is where it comes from. The
    answer is attached to the row rather than living in a legend."""
    history = _history({"net_income": {"2025Q1": 100.0}})

    grids = grid.build(history, "quarter")
    row = next(r for r in grids["income"].rows if r.id == "net_income")

    targets = {(link.statement, link.row) for link in row.links}
    assert ("cashflow", "net_income") in targets
    assert ("balance", "retained_earnings") in targets


# --------------------------------------------------------------------------- #
# the model has to tie
# --------------------------------------------------------------------------- #


def test_the_balance_check_is_computed_and_present_even_when_empty():
    """Never hidden and never dropped. A model with the check row missing is a
    model whose author did not want you to see it."""
    history = _history({
        "total_assets": {"2025Q1": 1000.0},
        "total_liabilities": {"2025Q1": 400.0},
        "equity": {"2025Q1": 600.0},
    })

    grids = grid.build(history, "quarter")

    assert _cell(grids, "balance", "balance_check", "2025Q1").value == 0.0
    assert any(r.id == "balance_check" for r in grids["balance"].rows)


def test_an_unbalanced_sheet_reports_the_size_of_the_gap():
    """"Does not balance" is not useful on its own — the analyst needs the
    magnitude to know where to hunt."""
    history = _history({
        "total_assets": {"2025Q1": 1000.0},
        "total_liabilities": {"2025Q1": 400.0},
        "equity": {"2025Q1": 550.0},
    })

    grids = grid.build(history, "quarter")

    assert _cell(grids, "balance", "balance_check", "2025Q1").value == 50.0


def test_a_subtotal_the_filer_omitted_is_summed_from_its_parts():
    """Filers stop tagging subtotals. An empty "total operating expenses" in a
    linked model is not blank — it is a zero that propagates into operating
    income."""
    history = _history({
        "revenue": {"2025Q1": 100.0},
        "rnd": {"2025Q1": 30.0},
        "sgna": {"2025Q1": 12.0},
    })

    grids = grid.build(history, "quarter")
    cell = _cell(grids, "income", "opex", "2025Q1")

    assert cell.value == 42.0
    assert cell.origin == "derived"
    assert "summed from" in (cell.note or "")


def test_ebitda_is_struck_from_reported_da_not_from_a_guess():
    """D&A is disclosed on the cash flow statement. Taking it from there is the
    only version of EBITDA that ties to something the company filed — stripping
    depreciation out of cost of revenue requires a split filers do not give."""
    history = _history({
        "revenue": {"2025Q1": 100.0},
        "operating_income": {"2025Q1": 20.0},
        "depreciation": {"2025Q1": 5.0},
    })

    grids = grid.build(history, "quarter")

    assert _cell(grids, "income", "ebitda", "2025Q1").value == 25.0


def test_cash_rolls_forward_from_the_prior_period():
    """Opening cash is last period's closing cash. If that link is not real the
    cash flow statement is three unrelated columns."""
    history = _history({"cash": {"2025Q1": 50.0, "2025Q2": 70.0}})

    grids = grid.build(history, "quarter")

    assert _cell(grids, "cashflow", "cash_open", "2025Q2").value == 50.0
    assert _cell(grids, "cashflow", "cash_close", "2025Q1").value == 50.0


# --------------------------------------------------------------------------- #


def test_an_empty_row_is_dropped_but_headers_and_the_check_survive():
    """A company that reports no goodwill should not get a goodwill row of
    dashes; a company whose balance sheet does not tie must still get a check."""
    history = _history({"revenue": {"2025Q1": 100.0}})

    grids = grid.build(history, "quarter")
    ids = {r.id for r in grids["balance"].rows}

    assert "goodwill" not in ids
    assert "balance_check" in ids
    assert "assets_header" in ids


def test_no_periods_raises_rather_than_returning_an_empty_grid():
    with pytest.raises(ValueError, match="no periods"):
        grid.build(History("EMPTY", AS_OF, {}), "quarter")


def test_the_json_round_trips_every_cell_and_its_provenance():
    """Keys are short and empty fields are dropped. `asdict` on every cell of 74
    quarters × 87 rows × 3 statements produced a 1.9 MB payload, most of it the
    string "null" — and the UI fetches this on page load."""
    history = _history({"revenue": {"2025Q1": 100.0}})

    payload = grid.to_json(grid.build(history, "quarter"))

    cell = payload["income"]["rows"][0]["cells"]["2025Q1"]
    assert cell["v"] == 100.0
    assert cell["o"] == "actual"
    # The filing is referenced by index into a per-statement table rather than
    # repeated on every cell.
    assert payload["income"]["filings"][cell["s"]]["form"] == "10-Q"
    assert payload["income"]["filings"][cell["s"]]["filed"] == "2025-03-28"
    assert payload["income"]["periods"][0]["label"] == "1Q25A"


def test_a_derived_cell_omits_the_origin_key_because_derived_is_the_default():
    """The commonest case carries the fewest bytes."""
    history = _history({"revenue": {"2025Q1": 100.0}, "gross_profit": {"2025Q1": 60.0}})

    payload = grid.to_json(grid.build(history, "quarter"))
    margin = next(r for r in payload["income"]["rows"] if r["id"] == "gross_margin")

    assert "o" not in margin["cells"]["2025Q1"]
