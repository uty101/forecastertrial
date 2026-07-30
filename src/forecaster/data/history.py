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

    for fact in facts:
        end = _as_date(fact["end"])
        if item.kind == "flow":
            days = _span_days(fact)
            if days is None:
                continue
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


def build_history(
    ticker: str,
    as_of: date,
    facts_for: Callable[[LineItem], list[dict]],
    keys: tuple[str, ...] | None = None,
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

    history = History(ticker=ticker, as_of=as_of, series=series)
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
