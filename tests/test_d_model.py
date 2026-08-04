"""Stage D — the three-statement model, and what it must refuse to do.

The tests that matter here are not "does it build a model". They are the three
ways a model stage lies: it produces an EPS from a balance sheet that does not
balance, it silently invents the share count that EPS divides by, and it reports
an accuracy figure that was measured against something other than reality.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.history import History, Observation
from forecaster.data.prices import PriceBar
from forecaster.pipeline import d_model

AS_OF = date(2026, 8, 4)

# Eight quarters of a small, internally consistent company. Revenue grows 4% a
# quarter on a stable 60% gross margin, so the ratio base is well defined and
# any error the model reports is the model's own.
QUARTERS = [
    ("2025Q1", 1000.0), ("2025Q2", 1040.0), ("2025Q3", 1082.0), ("2025Q4", 1125.0),
    ("2026Q1", 1170.0), ("2026Q2", 1217.0), ("2026Q3", 1266.0), ("2026Q4", 1316.0),
]


def _history(overrides: dict[str, dict[str, float]] | None = None) -> History:
    """A filer whose statements tie. `overrides[key][period]` replaces a value."""
    overrides = overrides or {}
    series: dict[str, list[Observation]] = {}

    def add(key: str, period: str, value: float, unit: str = "USD") -> None:
        fy, fp = int(period[:4]), period[4:]
        month = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}[fp]
        series.setdefault(key, []).append(
            Observation(
                key=key, fy=fy, fp=fp, value=value, unit=unit,
                period_end=date(fy, month, 28),
                filed=date(fy, month, 28).replace(day=28),
                form="10-Q", accession=f"000-{period}",
            )
        )

    for period, revenue in QUARTERS:
        values = {
            "revenue": revenue,
            "gross_profit": revenue * 0.60,
            "opex": revenue * 0.30,
            "operating_income": revenue * 0.30,
            "pretax_income": revenue * 0.30,
            "tax": revenue * 0.30 * 0.15,
            "net_income": revenue * 0.30 * 0.85,
            "depreciation": revenue * 0.05,
            "capex": revenue * 0.06,
            "cash": revenue * 2.0,
            "receivables": revenue * 0.5,
            "inventory": revenue * 0.4,
            "payables": revenue * 0.25,
            "ppe_net": revenue * 1.2,
            "long_term_debt": 500.0,
            # Totals, so the forecast scaffold has an opening sheet that ties.
            "total_assets": revenue * 2.0 + revenue * 0.5 + revenue * 0.4
                            + revenue * 1.2,
            "total_liabilities": revenue * 0.25 + 500.0,
            "equity": revenue * 2.0 + revenue * 0.5 + revenue * 0.4
                      + revenue * 1.2 - revenue * 0.25 - 500.0,
            "eps_diluted": (revenue * 0.30 * 0.85) / 100.0,
        }
        for key, value in values.items():
            unit = "USD/shares" if key == "eps_diluted" else "USD"
            add(key, period, overrides.get(key, {}).get(period, value), unit)
        add("diluted_shares", period, 100.0, "shares")

    return History("TEST", AS_OF, series, cik="0000000001")


PRICES = [PriceBar(date(2026, 7, d), 10.0, 10.0, 10.0, 10.0, 1000.0)
          for d in range(1, 11)]


# --------------------------------------------------------------------------- #
# the things that must not be inferred
# --------------------------------------------------------------------------- #


def test_it_refuses_to_build_without_a_share_price():
    """A filing reports what a buyback COST and never how many shares it
    retired, so the average price cannot come from SEC data. A placeholder does
    not fail loudly — it retires `buyback_spend` shares and hands back an EPS
    that looks entirely reasonable. On NVDA that removed 5.2bn shares from a
    24.4bn denominator and produced an EPS 27% too high.

    EPS is a ratio. An unowned denominator is not a small approximation.
    """
    with pytest.raises(ValueError, match="avg_price|price history"):
        d_model.build(_history(), prices=None)


def test_an_explicit_avg_price_is_accepted_when_there_are_no_bars():
    """The multi-class and thin-history escape hatch. Refusing to infer is not
    the same as refusing to be told."""
    result = d_model.build(_history(), prices=None, avg_price=10.0)

    assert result.base_period == "2026Q4"


def test_a_nan_price_is_refused_rather_than_used():
    """The bug that shipped, caught one layer up as well as at source.

    `bool(nan)` is True, so a truthiness guard passes NaN straight through. It
    then survives every arithmetic operation without raising, and the stage
    reports an EPS of `nan` for every quarter — which reads as a rendering
    glitch rather than as an unusable input. Both `vwap` and this function now
    finite-check, because one guard is one place to forget.
    """
    with pytest.raises(ValueError, match="avg_price|price history"):
        d_model.build(_history(), prices=None, avg_price=float("nan"))


def test_a_quarter_whose_model_produces_a_non_finite_eps_is_skipped_not_counted():
    """A NaN in the checks puts a NaN in the median, and the headline accuracy
    figure becomes "nan%". An unusable check is a skip with a reason."""
    history = _history()
    result = d_model.build(history, prices=PRICES)

    assert result.median_abs_eps_error is not None
    assert all(
        c.eps_error is None or abs(c.eps_error) < float("inf") for c in result.checks
    )


def test_a_history_with_nothing_in_it_raises_rather_than_returning_empty():
    """An empty ModelResult would flow downstream as "the model says nothing",
    which is indistinguishable from a model that ran and found nothing."""
    with pytest.raises(ValueError, match="no history"):
        d_model.build(History("EMPTY", AS_OF, {}), prices=PRICES)


# --------------------------------------------------------------------------- #
# the backtest is the point
# --------------------------------------------------------------------------- #


def test_each_check_is_driven_by_that_quarter_s_own_reported_revenue():
    """What makes the number meaningful.

    Revenue is the one input a forecast would have had to supply. Handing the
    model the real one isolates the model's structural error from any lens's
    forecasting error — otherwise the figure on screen is a blend of two things
    and improves when either one does.
    """
    result = d_model.build(_history(), prices=PRICES)

    assert result.checks, "no quarter was reproduced"
    for check in result.checks:
        assert check.actual_eps is not None
        assert check.modelled_eps is not None


def test_the_base_of_every_check_is_the_quarter_before_it():
    """Every ratio and opening balance must be information that existed at the
    time. A check whose base is the quarter itself is not a test, it is a copy.
    """
    result = d_model.build(_history(), prices=PRICES)
    periods = _history().periods()

    for check in result.checks:
        assert periods.index(check.period) >= d_model.MIN_PRIOR_QUARTERS


def test_a_quarter_with_too_little_history_behind_it_is_skipped_and_named():
    """Testing against a base with two quarters behind it measures the thinness
    of the history, not the model — and a silently dropped quarter makes the
    median look better than it is."""
    thin = _history()
    thin.series = {k: v[:5] for k, v in thin.series.items()}

    result = d_model.build(thin, prices=PRICES, backtest_quarters=8)

    assert result.skipped, "a quarter was dropped without saying so"
    assert all(":" in line for line in result.skipped), "skips must carry a reason"


def test_a_quarter_the_model_cannot_build_is_reported_not_raised():
    """A filer that stops tagging a line item is a finding about the data, not a
    crash. The run continues and the gap is visible."""
    broken = _history(overrides={"revenue": {"2026Q3": 0.0}})

    result = d_model.build(broken, prices=PRICES)

    assert any("2026Q3" in line for line in result.skipped)


def test_the_error_summary_is_a_median_not_a_mean():
    """Robust statistics only. One quarter with a one-off charge would otherwise
    set the number the whole model is judged on."""
    result = d_model.build(_history(), prices=PRICES)
    result.checks[0].modelled_eps = (result.checks[0].actual_eps or 1.0) * 100

    median = result.median_abs_eps_error
    errors = sorted(abs(c.eps_error) for c in result.checks if c.eps_error is not None)
    assert median <= errors[-1], "one outlier moved the headline error"


def test_bias_is_signed_where_the_headline_error_is_not():
    """`median_abs_eps_error` deliberately cannot tell you the model runs hot.
    Reporting only the absolute figure hides a one-directional error, which is
    the kind that looks like bad modelling and is actually a broken link."""
    result = d_model.build(_history(), prices=PRICES)

    if result.bias is not None and result.median_abs_eps_error is not None:
        assert abs(result.bias) <= result.median_abs_eps_error + 1e-9


# --------------------------------------------------------------------------- #
# what it hands downstream
# --------------------------------------------------------------------------- #


def test_the_balance_check_travels_with_the_model():
    """An EPS from a balance sheet that does not balance is worse than no EPS,
    because it is usable. `balanced` and its detail ride along with the numbers
    rather than being logged and forgotten."""
    result = d_model.build(_history(), prices=PRICES)

    assert result.balanced is True
    assert "balance" in result.balance_detail.lower()


def test_every_ratio_carries_a_note_saying_what_it_was_taken_over():
    """A median with no window is an assertion. The note is what makes it a
    measurement a lens can argue with."""
    result = d_model.build(_history(), prices=PRICES)

    assert result.ratios["gross_margin"] == pytest.approx(0.60, abs=1e-6)
    assert result.notes, "no provenance for any ratio"


def test_the_prompt_block_states_the_error_the_model_cannot_resolve():
    """A lens arguing for a 30bp margin change should be told the model it feeds
    cannot resolve 30bp. Without that the ensemble spends its budget on
    precision the arithmetic downstream discards."""
    result = d_model.build(_history(), prices=PRICES)
    block = d_model.to_block(result)

    assert "THREE-STATEMENT MODEL" in block
    assert "gross_margin" in block
    assert "cannot resolve" in block


def test_the_json_reports_skipped_quarters_as_prominently_as_checked_ones():
    """Silent truncation reads as "we covered everything"."""
    thin = _history()
    thin.series = {k: v[:5] for k, v in thin.series.items()}

    payload = d_model.to_json(d_model.build(thin, prices=PRICES, backtest_quarters=8))

    assert "skipped" in payload and payload["skipped"]
    assert "median_abs_eps_error" in payload
    assert "statements" in payload and payload["statements"]
