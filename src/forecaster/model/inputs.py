"""`History` → `StatementInputs`: the join between the data layer and the model.

These two halves were built separately and never met. `History` holds long
quarterly series — 69 of them for NVDA, one per line item. `StatementInputs`
wants about twenty single numbers describing one quarter. Nothing converted
between them, which is why the model layer had nothing to consume.

The conversion is not a copy, because the two shapes differ in four ways:

1. **Opening balances come from the PREVIOUS quarter.** `receivables_open` is
   the base quarter's closing figure, not the modelled quarter's. Off by one
   here and every working-capital line is wrong by a quarter.

2. **Some inputs are ratios that are not line items.** `gross_margin` is
   `gross_profit / revenue`; `tax_rate` is `tax / pretax_income`.

3. **The balance sheet stores LEVELS and the cash flow needs CHANGES.** A
   closing receivable is projected by holding days-sales-outstanding constant
   against forecast revenue, so the delta falls out of the forecast rather than
   being copied from a historical delta.

4. **The forecast quarter has not happened.** `revenue` is an argument, not a
   lookup. History supplies the base to roll forward from and the historical
   relationships to hold; the forward view comes from the lenses.

**Ratios are medians, never means.** One quarter carrying an inventory
provision, a legal settlement or a 53rd week should not set an assumption for
the next one. `CLAUDE.md` is explicit that this codebase uses robust statistics
only.

**On `equity_open`.** The model's balance sheet is deliberately reduced: assets
are cash, receivables, inventory and net PP&E; the other side is payables, debt
and equity. Real filers carry much more — short-term investments, goodwill,
accrued liabilities, deferred revenue. Work the links through and
`balance_check` at the close reduces exactly to the imbalance at the open, so
the model balances if and only if the opening balance sheet does. Feeding it
reported `StockholdersEquity` would therefore report a broken link on every
company, when nothing is broken and the reduced statement is simply narrower.
So `equity_open` is a residual, and the gap against reported equity is logged
rather than hidden.
"""

from __future__ import annotations

import statistics

import structlog

from forecaster.data.history import History, Observation
from forecaster.data.lineitems import BY_KEY
from forecaster.model.statements import StatementInputs
from forecaster.schemas import Claim, Source, SourceKind

log = structlog.get_logger()

# Two years. Long enough that one odd quarter cannot set the assumption, short
# enough that a business which has changed shape is not averaged with its past.
RATIO_WINDOW = 8


def claim_for(history: History, observation: Observation) -> Claim:
    """An `Observation` as a citable `Claim`, in the evidence store's own shape.

    Deliberately identical to what `sec_source.get_actuals` emits, so a figure
    the model rests on and the same figure in the evidence store are one claim
    with one id, rather than two spellings that can drift apart.
    """
    item = BY_KEY[observation.key]
    return Claim(
        id=f"sec:{history.ticker}:{observation.period}:{item.label}",
        label=item.label,
        value=observation.value,
        unit=item.unit,
        period=observation.period,
        source=Source(
            kind=SourceKind.XBRL,
            uri=(
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{history.cik.lstrip('0')}/"
                f"{observation.accession.replace('-', '')}/"
            ),
            as_of=observation.filed,
            accession=observation.accession,
            page_or_section=observation.form,
        ),
        verbatim_quote=(
            f"{item.label}={observation.value} for the quarter ended "
            f"{observation.period_end} (form {observation.form}, "
            f"accn {observation.accession}"
            f"{', derived' if observation.derived else ''})"
        ),
    )


def _require_shares(
    history: History, base: str, override: float | None = None
) -> float:
    """The opening diluted share count, or a refusal naming the cause.

    This used to fall back to 1.0, which divides net income by a single share
    and reports an EPS in the billions. Absurd here, but the same fallback on a
    company with a partial series would produce something merely wrong.

    The failure has one common cause worth naming in the message. A filer with
    several listed share classes tags its weighted-average count — and often its
    EPS — against a class dimension, and SEC's `companyfacts` endpoint exposes
    only facts with no dimensions. Visa has no weighted-average share tag in
    `companyfacts` at all, and no diluted EPS either, while reporting both every
    quarter in the filing itself. No tag list fixes that; the numbers are not in
    the response.
    """
    observation = history.get("diluted_shares", base)
    if observation is not None and observation.value:
        return observation.value
    if override:
        return override
    raise ValueError(
        f"{history.ticker}: no diluted share count for {base}, so EPS has no "
        "denominator. Companies with multiple listed share classes tag the "
        "count against a class dimension, which SEC's companyfacts endpoint "
        "omits — the figure has to come from the filing itself or a market "
        "data source."
    )


def next_period(period: str) -> str:
    """`2027Q1` -> `2027Q2`, `2026Q4` -> `2027Q1`. Fiscal labels throughout."""
    year, quarter = int(period[:4]), int(period[-1])
    return f"{year}Q{quarter + 1}" if quarter < 4 else f"{year + 1}Q1"


def _upto(history: History, key: str, period: str, window: int) -> list[Observation]:
    """The `window` most recent observations of `key` at or before `period`."""
    periods = history.periods()
    if period not in periods:
        return []
    allowed = set(periods[: periods.index(period) + 1])
    return [o for o in history.series.get(key, []) if o.period in allowed][-window:]


def _median_ratio(
    history: History, numerator: str, denominator: str, period: str, window: int
) -> float | None:
    """Median of `numerator / denominator` over the window, or None.

    Paired by period, so a quarter present in one series and absent from the
    other contributes nothing rather than silently pairing with its neighbour.
    """
    top = {o.period: o.value for o in _upto(history, numerator, period, window)}
    bottom = {o.period: o.value for o in _upto(history, denominator, period, window)}
    ratios = [top[p] / bottom[p] for p in top if bottom.get(p)]
    return statistics.median(ratios) if ratios else None


def _median_level(
    history: History, key: str, period: str, window: int
) -> float | None:
    rows = _upto(history, key, period, window)
    return statistics.median([o.value for o in rows]) if rows else None


def inputs_for(
    history: History,
    revenue: float,
    avg_price: float,
    gross_margin: float | None = None,
    base_period: str | None = None,
    window: int = RATIO_WINDOW,
    shares_open: float | None = None,
) -> StatementInputs:
    """Build the model's inputs for the quarter after `base_period`.

    `revenue` is the forecast top line and is required — it is the one number
    that cannot come from history, and making it an argument keeps this function
    deterministic and keeps the lens boundary at exactly one place.
    `gross_margin` defaults to the historical median if the caller has no view.

    `avg_price` is also required, and deliberately has no default. A filing
    reports what a buyback COST, never how many shares it retired, so the share
    count cannot be derived from SEC data alone. A placeholder of 1.0 does not
    fail — it silently retires `buyback_spend` shares, which for NVDA removed
    5.2 billion from a 24.4 billion denominator and produced an EPS that looked
    entirely reasonable and was 27% too high. EPS is a ratio; an unowned
    denominator is not a small approximation. Make the caller supply it.
    """
    base = base_period or history.latest_period()
    if base is None:
        raise ValueError(f"{history.ticker}: no history to build a model from")
    if not avg_price or avg_price <= 0:
        raise ValueError(
            f"{history.ticker}: avg_price must be a positive share price. "
            "Buyback dollars are in the cash flow statement but the shares they "
            "retired are not, so this cannot be inferred from filings."
        )

    claims: dict[str, Claim] = {}
    notes: dict[str, str] = {}

    def level(field: str, key: str) -> float:
        """An opening balance: the base quarter's CLOSING figure, with its claim."""
        observation = history.get(key, base)
        if observation is None:
            notes[field] = f"{key} not reported for {base} — treated as zero"
            return 0.0
        claims[field] = claim_for(history, observation)
        return observation.value

    def scaled(field: str, key: str, fallback: float = 0.0) -> float:
        """A flow projected by holding its share of revenue constant."""
        ratio = _median_ratio(history, key, "revenue", base, window)
        if ratio is None:
            notes[field] = f"no {key}/revenue history through {base} — assumed {fallback}"
            return fallback
        notes[field] = (
            f"median {key}/revenue of {ratio:.4f} over {window} quarters to "
            f"{base}, applied to forecast revenue"
        )
        return ratio * revenue

    # ---- income statement ------------------------------------------------ #
    notes["revenue"] = f"forecast top line for {next_period(base)}"
    if gross_margin is None:
        gross_margin = _median_ratio(history, "gross_profit", "revenue", base, window)
        if gross_margin is None:
            raise ValueError(f"{history.ticker}: no gross margin history to fall back on")
        notes["gross_margin"] = (
            f"median of {window} quarters to {base}; no caller view supplied"
        )
    else:
        notes["gross_margin"] = "supplied by the caller"

    opex = scaled("opex", "opex")
    da = scaled("da", "depreciation")
    tax_rate = _median_ratio(history, "tax", "pretax_income", base, window)
    if tax_rate is None:
        tax_rate, notes["tax_rate"] = 0.0, "no tax/pre-tax history — assumed zero"
    else:
        notes["tax_rate"] = f"median effective rate over {window} quarters to {base}"
    other_income = _median_level(history, "other_income", base, window) or 0.0
    notes.setdefault("other_income", f"median level over {window} quarters to {base}")

    # ---- working capital: levels in, changes out -------------------------- #
    receivables_open = level("receivables_open", "receivables")
    inventory_open = level("inventory_open", "inventory")
    payables_open = level("payables_open", "payables")

    def delta(field: str, key: str, opening: float) -> float:
        """Hold the ratio to revenue constant and let the change fall out."""
        ratio = _median_ratio(history, key, "revenue", base, window)
        if ratio is None:
            notes[field] = f"no {key}/revenue history — assumed unchanged"
            return 0.0
        notes[field] = (
            f"{key} held at {ratio:.4f} of revenue (median of {window} quarters "
            f"to {base}); the change follows from forecast revenue"
        )
        return ratio * revenue - opening

    # ---- assemble --------------------------------------------------------- #
    cash_open = level("cash_open", "cash")
    ppe_net_open = level("ppe_net_open", "ppe_net")
    debt = level("debt", "long_term_debt")

    carried_assets = cash_open + receivables_open + inventory_open + ppe_net_open
    equity_open = carried_assets - payables_open - debt
    reported = history.get("equity", base)
    notes["equity_open"] = (
        "residual: the model's balance sheet carries cash, receivables, "
        "inventory and net PP&E against payables, debt and equity, so equity "
        "absorbs every line it does not carry. Reported equity was "
        f"{reported.value:,.0f}" if reported else "residual; equity not reported"
    )
    if reported is not None:
        log.info(
            "equity_open_residual",
            ticker=history.ticker,
            period=base,
            residual=round(equity_open, 0),
            reported=round(reported.value, 0),
            omitted_lines=round(reported.value - equity_open, 0),
        )

    inputs = StatementInputs(
        revenue=revenue,
        gross_margin=gross_margin,
        opex=opex,
        da=da,
        tax_rate=tax_rate,
        other_income=other_income,
        cash_open=cash_open,
        receivables_open=receivables_open,
        inventory_open=inventory_open,
        ppe_net_open=ppe_net_open,
        payables_open=payables_open,
        debt=debt,
        equity_open=equity_open,
        capex=scaled("capex", "capex"),
        buyback_spend=_median_level(history, "buyback", base, window) or 0.0,
        dividends=_median_level(history, "dividends", base, window) or 0.0,
        delta_receivables=delta("delta_receivables", "receivables", receivables_open),
        delta_inventory=delta("delta_inventory", "inventory", inventory_open),
        delta_payables=delta("delta_payables", "payables", payables_open),
        shares_open=_require_shares(history, base, shares_open),
        avg_price=avg_price,
        sbc_dilution=0.0,
        claims=claims,
        notes=notes,
    )
    notes.setdefault("buyback_spend", f"median spend over {window} quarters to {base}")
    notes.setdefault("dividends", f"median paid over {window} quarters to {base}")
    notes["avg_price"] = (
        f"caller-supplied average execution price of {avg_price:,.2f}. Not "
        "derivable from filings — a market data source owns this number"
    )
    notes["sbc_dilution"] = "assumed zero — not derivable from the cash flow statement"
    return inputs
