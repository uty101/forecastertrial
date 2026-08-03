"""Quarterly history, assembled from raw XBRL facts.

This is the layer that was missing. `companyfacts` returns every fact a company
has ever tagged — for NVDA, 305 diluted-EPS facts and 227 share counts, roughly
a decade of quarters — and `get_actuals` was filtering all of it down to a single
period and discarding the rest. A three-statement model cannot be built from one
quarter, so there was nothing for the model layer to consume and it was never
wired in.

Two things here are not plumbing:

**Q4 does not exist in XBRL.** There is no fourth 10-Q. A company files three
quarterlies and then a 10-K covering the full year, so Q4 for any FLOW item has
to be derived as FY minus the three quarters. Stock items need no such treatment
— a balance sheet at year end is simply the year-end instant. Filers that do tag
a Q4 duration directly are preferred over the derived figure when present.

**Point-in-time survives the assembly.** Every quarter carries the `filed` date
of the fact it came from, and a derived Q4 carries the latest `filed` of its
components — the date on which that number first became knowable. Losing this in
the reshaping step would reintroduce look-ahead through the back door, after the
source layer went to some trouble to prevent it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import structlog

from forecaster.data.lineitems import BY_KEY, LINE_ITEMS, LineItem

log = structlog.get_logger()

QUARTERS = ("Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True)
class Observation:
    """One line item, one fiscal quarter, with the date it became knowable."""

    key: str
    fy: int
    fp: str
    value: float
    unit: str
    period_end: date
    filed: date
    form: str
    accession: str
    """Q4 flows are computed as FY − (Q1+Q2+Q3) rather than read off a filing.
    Surfaced rather than hidden: it changes how much you should trust the
    number, and a reconciler is entitled to know."""
    derived: bool = False

    @property
    def period(self) -> str:
        return f"{self.fy}{self.fp}"


@dataclass
class History:
    """Quarterly series per line item, oldest first."""

    ticker: str
    as_of: date
    series: dict[str, list[Observation]]
    """Carried so a consumer can build a resolvable EDGAR URI from an
    Observation's accession without going back to the source layer for it."""
    cik: str = ""

    def get(self, key: str, period: str) -> Observation | None:
        return next((o for o in self.series.get(key, []) if o.period == period), None)

    def latest(self, key: str) -> Observation | None:
        rows = self.series.get(key)
        return rows[-1] if rows else None

    def periods(self) -> list[str]:
        """Every fiscal quarter any line item covers, oldest first."""
        seen: dict[str, date] = {}
        for rows in self.series.values():
            for o in rows:
                seen.setdefault(o.period, o.period_end)
                seen[o.period] = min(seen[o.period], o.period_end)
        return sorted(seen, key=lambda p: seen[p])

    def latest_period(self) -> str | None:
        """The most recent fiscal quarter with any data, or None.

        Callers want this instead of constructing a label. Fiscal labels are
        derived from period end dates, so a January year-end filer sits in
        fiscal 2027 while the calendar reads 2026 — a guessed label is not
        merely wrong, it fails to match anything and looks like absent data.
        """
        periods = self.periods()
        return periods[-1] if periods else None

    def filed_for(self, period: str) -> date | None:
        """When this quarter became fully knowable.

        The LATEST filing date across the period's line items, not the earliest:
        the quarter is only readable once its last component has landed, and a
        derived Q4 is not knowable until the 10-K arrives.
        """
        filed = [
            o.filed
            for rows in self.series.values()
            for o in rows
            if o.period == period
        ]
        return max(filed) if filed else None

    def n_quarters(self) -> int:
        return len(self.periods())

    def coverage(self) -> dict[str, int]:
        return {key: len(rows) for key, rows in self.series.items() if rows}


def _as_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _span_days(fact: dict) -> int | None:
    if not fact.get("start"):
        return None
    return (_as_date(fact["end"]) - _as_date(fact["start"])).days


def _pick_latest(facts: list[dict]) -> dict:
    """Among facts covering the same dates, the most recently filed wins.

    That is the newest restatement we were entitled to see at `as_of` — the
    source layer has already dropped anything filed later.
    """
    return max(facts, key=lambda f: f["filed"])


def fiscal_year_end_month(facts: list[dict]) -> int:
    """The month the company's fiscal year ends, inferred from its own filings.

    Needed because the fiscal label cannot be read off the fact (see below) and
    a hardcoded December is wrong for a large minority of filers — NVDA's year
    ends in late January, so its "Q1" ends in April.
    """
    months: dict[int, int] = {}
    for fact in facts:
        days = _span_days(fact)
        if days is not None and 350 <= days <= 380:
            month = _as_date(fact["end"]).month
            months[month] = months.get(month, 0) + 1
    if not months:
        return 12
    return max(months, key=lambda m: months[m])


def label_for(period_end: date, fye_month: int) -> tuple[int, str]:
    """Fiscal (year, quarter) for a period ending on this date.

    DERIVED FROM DATES, NEVER FROM `fy`/`fp`.

    Those two fields describe the FILING the fact appeared in, not the fact.
    A 10-K carries its comparatives, so `fy=2026 fp=FY` sits on the FY2024,
    FY2025 and FY2026 figures alike; and a ninety-day quarter lifted into a 10-K
    is tagged `fp='FY'` too. Trusting them produced a Q4 with negative gross
    profit sorted before Q1, and silently dropped every quarter of revenue.
    """
    fiscal_year = (
        period_end.year if period_end.month <= fye_month else period_end.year + 1
    )
    offset = (period_end.month - fye_month - 1) % 12
    return fiscal_year, f"Q{offset // 3 + 1}"


def build_series(
    item: LineItem, facts: list[dict], fye_month: int
) -> list[Observation]:
    """Reshape raw facts for one line item into a quarterly series.

    `fye_month` is passed in rather than inferred here, and that is not a style
    choice. Inferring it per line item lets two items disagree about where the
    fiscal year starts — some concepts have few annual facts, so the mode is
    noisy — and then revenue lands in 2027Q1 while EPS lands in 2027Q2 for the
    same three months. Every line of the model would be internally consistent
    and quietly describing two different quarters.
    """
    if not facts:
        return []

    # Keyed on the fact's own dates, which are the only thing that means what it
    # says. Flows: (start, end). Stocks: (end,) — a balance has no duration.
    quarterly: dict[tuple, list[dict]] = {}
    annual: dict[date, list[dict]] = {}
    # Every dated flow fact, grouped by the date its period starts. Cumulative
    # figures are kept here rather than discarded — see the ladder below.
    ladders: dict[str, list[dict]] = {}

    for fact in facts:
        end = _as_date(fact["end"])
        if item.kind == "flow":
            days = _span_days(fact)
            if days is None:
                continue
            if item.additive:
                ladders.setdefault(fact["start"], []).append(fact)
            # A quarter is 80–100 days and a year 350–380; filers wobble by a few
            # days around 52/53-week calendars. Anything else is a half-year, a
            # nine-month cumulative or a stub, and treating one of those as a
            # quarter is the units error that stays internally consistent.
            if 80 <= days <= 100:
                quarterly.setdefault((fact["start"], fact["end"]), []).append(fact)
            elif 350 <= days <= 380:
                annual.setdefault(end, []).append(fact)
        else:
            quarterly.setdefault((fact["end"],), []).append(fact)

    out: list[Observation] = []
    for candidates in quarterly.values():
        fact = _pick_latest(candidates)
        end = _as_date(fact["end"])
        fy, fp = label_for(end, fye_month)
        out.append(
            Observation(
                key=item.key,
                fy=fy,
                fp=fp,
                value=float(fact["val"]),
                unit=item.unit,
                period_end=end,
                filed=_as_date(fact["filed"]),
                form=str(fact.get("form", "")),
                accession=str(fact.get("accn", "")),
            )
        )

    # Cash flow statements are filed YEAR TO DATE, never per quarter: a 10-Q's
    # cash flow covers 0–3, then 0–6, then 0–9 months. Only Q1 is a quarter in
    # its own right, so the span filter above — which is correct, a nine-month
    # cumulative really is not a quarter — left the entire third statement at
    # roughly one quarter in four while income and balance sheet ran near 100%.
    #
    # Differencing consecutive rungs of the year-to-date ladder recovers the
    # rest, and it is the same move as the Q4 rule below, one step finer:
    #
    #     Q2 = YTD(6m) − YTD(3m)   Q3 = YTD(9m) − YTD(6m)   Q4 = FY − YTD(9m)
    #
    # Only for additive items. Differencing a ratio or a weighted-average share
    # count is the arithmetic that produced a −4.49 EPS quarter.
    #
    # Rungs must share a start date, so a ladder cannot span two fiscal years,
    # and a directly tagged quarter always wins over a derived one.
    if item.kind == "flow" and item.additive:
        have = {o.period_end for o in out}
        for rungs in ladders.values():
            by_end: dict[str, list[dict]] = {}
            for fact in rungs:
                by_end.setdefault(fact["end"], []).append(fact)
            ordered = [_pick_latest(by_end[end]) for end in sorted(by_end)]

            for previous, current in zip(ordered, ordered[1:], strict=False):
                end = _as_date(current["end"])
                if end in have:
                    continue
                if not 80 <= (end - _as_date(previous["end"])).days <= 100:
                    continue
                fy, fp = label_for(end, fye_month)
                out.append(
                    Observation(
                        key=item.key,
                        fy=fy,
                        fp=fp,
                        value=float(current["val"]) - float(previous["val"]),
                        unit=item.unit,
                        period_end=end,
                        # Knowable only once BOTH rungs are filed. The later one
                        # is normally the current filing, but a restated opening
                        # figure can land afterwards.
                        filed=max(
                            _as_date(current["filed"]), _as_date(previous["filed"])
                        ),
                        form=str(current.get("form", "")),
                        accession=str(current.get("accn", "")),
                        derived=True,
                    )
                )
                have.add(end)

    # Q4 for flows: FY − (Q1+Q2+Q3), where the filer did not tag it directly.
    # There is no fourth 10-Q; the fourth quarter only ever appears inside the
    # annual figure. Matched on DATES — the three quarters must fall inside the
    # annual window — so a comparative year in a 10-K cannot be mistaken for the
    # current one.
    if item.kind == "flow" and item.additive:
        have = {o.period_end for o in out}
        for year_end, candidates in annual.items():
            if year_end in have:
                continue
            fy_fact = _pick_latest(candidates)
            year_start = _as_date(fy_fact["start"])
            parts = [o for o in out if year_start <= o.period_end < year_end]
            if len(parts) != 3:
                continue
            fy, fp = label_for(year_end, fye_month)
            out.append(
                Observation(
                    key=item.key,
                    fy=fy,
                    fp=fp,
                    value=float(fy_fact["val"]) - sum(p.value for p in parts),
                    unit=item.unit,
                    period_end=year_end,
                    # Knowable only once the 10-K lands, which is later than any
                    # of the three quarters it is derived from.
                    filed=max([_as_date(fy_fact["filed"])] + [p.filed for p in parts]),
                    form=str(fy_fact.get("form", "")),
                    accession=str(fy_fact.get("accn", "")),
                    derived=True,
                )
            )

    out.sort(key=lambda o: o.period_end)
    return out


def _fill_from_identity(
    series: dict[str, list[Observation]],
    target: str,
    minuend: str,
    subtrahend: str,
) -> None:
    """Fill `target` as `minuend − subtrahend` wherever it has no observation.

    Two line items are routinely missing not because the company lacks them but
    because it never tagged the TOTAL — and both follow from an exact identity
    rather than an estimate:

        total_liabilities = total_assets  − equity            (A = L + E)
        opex              = gross_profit  − operating_income

    AMD has 128 facts for `LiabilitiesAndStockholdersEquity` and none at all for
    `Liabilities`, and tags `OperatingExpenses` in 15 filings out of 67 — which
    read as a core balance-sheet line at zero coverage and an income-statement
    line at 13%, for a company that plainly has both.

    For the first of those, the tempting shortcut is the dangerous one: adding
    `LiabilitiesAndStockholdersEquity` to the tag list as a synonym would yield
    total ASSETS — several times too large, internally consistent, and balancing
    against nothing.

    Derived periods are marked. A reconciler is entitled to know which numbers
    were read off a filing and which were computed.
    """
    if target not in series:
        return
    left = {o.period: o for o in series.get(minuend, [])}
    right = {o.period: o for o in series.get(subtrahend, [])}
    if not left or not right:
        return

    filled = list(series[target])
    have = {o.period for o in filled}
    for period, base in left.items():
        deduction = right.get(period)
        if period in have or deduction is None:
            continue
        filled.append(
            Observation(
                key=target,
                fy=base.fy,
                fp=base.fp,
                value=base.value - deduction.value,
                unit=base.unit,
                period_end=base.period_end,
                filed=max(base.filed, deduction.filed),
                form=base.form,
                accession=base.accession,
                derived=True,
            )
        )
    filled.sort(key=lambda o: o.period_end)
    series[target] = filled


def build_history(
    ticker: str,
    as_of: date,
    facts_for: Callable[[LineItem], list[dict]],
    keys: tuple[str, ...] | None = None,
    cik: str = "",
) -> History:
    """Assemble every requested line item into quarterly series.

    `facts_for` is injected rather than imported so this module stays pure and
    testable without a network or a cache — the reshaping logic is where the
    subtle errors live, and it should be exercisable on a dict.
    """
    items = [BY_KEY[k] for k in keys] if keys else list(LINE_ITEMS)
    fetched = {item.key: facts_for(item) for item in items}

    # One fiscal calendar for the whole company, inferred from every annual fact
    # we have rather than per item. See build_series for why this matters.
    fye_month = fiscal_year_end_month([f for rows in fetched.values() for f in rows])

    series: dict[str, list[Observation]] = {}
    for item in items:
        series[item.key] = build_series(item, fetched[item.key], fye_month)

    # Cross-item, so these cannot live in build_series, and they must run before
    # `missing_core` below or a derivable line still reports as missing.
    _fill_from_identity(series, "total_liabilities", "total_assets", "equity")
    _fill_from_identity(series, "opex", "gross_profit", "operating_income")

    history = History(ticker=ticker, as_of=as_of, series=series, cik=cik)
    missing_core = [
        i.key for i in items if i.core and not series.get(i.key)
    ]
    log.info(
        "history_built",
        ticker=ticker,
        quarters=history.n_quarters(),
        items_with_data=sum(1 for v in series.values() if v),
        items_requested=len(items),
        missing_core=missing_core or None,
    )
    return history
