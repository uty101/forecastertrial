"""Revenue disaggregation, read from the XBRL instance rather than a rendering.

**This exists because the alternative was a hardcoded list of twelve companies
with their driver decomposition typed out by hand.** That gave twelve names a
warm start and everything else an empty string, which is the wrong shape for a
system handed a ticker at 10am.

**Why not `companyfacts`.** Segment revenue is tagged against a dimension axis —
`StatementBusinessSegmentsAxis`, `ProductOrServiceAxis` — and that endpoint
exposes only facts with NO dimensions. Every segment number a filer publishes is
invisible to it. Same limitation that hid Visa's diluted share count; no tag list
fixes it, because the numbers are not in the response.

**Why not the rendered tables either.** SEC also publishes `FilingSummary.xml`
indexing seventy-odd HTML report tables, and that route works — for some filers.
It got to 7 of 12 and each additional filer cost its own fix: Microsoft writes
`(Detail)` where everyone else writes `(Details)`; the geographic note heads each
block with a bare `Revenues` where the product note uses a bracketed label;
Coca-Cola's schedule is 87 rows of which six are revenue. Every one of those is a
quirk of how a filer's accountants laid out a page, and the supply of them is
unbounded.

**What is used instead.** The XBRL instance document in the same folder, where
the same numbers carry their dimension as DATA:

    <context id="c-42">
      <entity><segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementGeographicalAxis"
          >country:TW</xbrldi:explicitMember>
      </segment></entity>
      <period><startDate>2026-01-26</startDate>…</period>
    </context>

The axis states what kind of split it is, so nothing has to be inferred from a
report title or a table layout. There is no page to lay out wrongly.

The instance carries every period it reports, so the prior-year comparative comes
from the same document — segment GROWTH falls out of the filing rather than out
of an assumption, which is the whole point of a driver decomposition.

**Three things this closes at once.** The Drivers lens gets a real bottom-up
build on any ticker. Margins gets the mix argument it exists to make. And the
geographic split IS the FX exposure the Mechanical lens needs, so the one leg of
that lens written off as unavailable is in the same document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import structlog

log = structlog.get_logger()

Kind = Literal["segment", "geography", "product", "concentration"]

# The dimension axis says what the split IS. No report titles, no table layouts,
# no filer-specific naming — this is the taxonomy's own classification and it is
# the same for every company that files.
AXIS_KIND: dict[str, Kind] = {
    "StatementBusinessSegmentsAxis": "segment",
    "OperatingSegmentsAxis": "segment",
    "SegmentReportingInformationBySegmentAxis": "segment",
    "StatementGeographicalAxis": "geography",
    "SegmentGeographicalGroupsOfCountriesAxis": "geography",
    "GeographicalAxis": "geography",
    "ProductOrServiceAxis": "product",
    "SegmentProductsAndServicesAxis": "product",
    "MajorCustomersAxis": "concentration",
    "ConcentrationRiskByCustomerAxis": "concentration",
}

# Axes that appear alongside a revenue fact without splitting it. The
# consolidation axis in particular tags the CONSOLIDATED total as
# `OperatingSegmentsMember`, which parses as a one-member split summing exactly
# to revenue — a decomposition into one part, which is no decomposition at all.
IGNORE_AXES = {
    "ConsolidationItemsAxis",
    "StatementEquityComponentsAxis",
    "StatementScenarioAxis",
    "StatementClassOfStockAxis",
}

# Tried in order. A company-specific extension (`nvda:SomeRevenueMember`) is not
# needed here — the us-gaap revenue tags are what filers dimension.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    # Banks and brokers. The same omission cost Goldman its entire revenue line
    # in `lineitems.py` and it cost JPMorgan its segment split here — the
    # geographic axis parsed fine and the business segments were invisible,
    # because a bank's top line is revenue NET of interest expense.
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
)

MAX_SUBSET_SEARCH = 18


@dataclass(frozen=True)
class SegmentLine:
    """One member of one axis, with its prior-year comparative."""

    kind: Kind
    label: str
    value: float
    prior_value: float | None
    unit: str
    period_label: str
    prior_period_label: str
    report: str
    source_uri: str
    axis: str = ""
    member: str = ""

    @property
    def growth(self) -> float | None:
        """Year-over-year, from two facts in the same document.

        Not an assumption and not a join across two filings — the instance
        carries every period it reports, which is what makes a segment build
        defensible rather than reconstructed.
        """
        if not self.prior_value:
            return None
        return self.value / self.prior_value - 1


# --------------------------------------------------------------------------- #
# reading the instance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Context:
    axis: str | None
    member: str | None
    start: str | None
    end: str | None


def _humanise(member: str) -> str:
    """`us-gaap:ChinaIncludingHongKongMember` -> `China Including Hong Kong`.

    Two-letter country codes (`country:TW`) are left alone: expanding them would
    need a lookup table, and "TW" is unambiguous to a reader while a wrong
    expansion is not.
    """
    name = member.split(":")[-1]
    if name.endswith("Member"):
        name = name[: -len("Member")]
    if len(name) <= 3 and name.isupper():
        return name
    # CamelCase to words, keeping runs of capitals together (US, EMEA, AI).
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return spaced.strip() or name


def parse_contexts(xml: str) -> dict[str, _Context]:
    """Every context, with its single dimension if it has exactly one.

    Facts carrying two or more dimensions are cross-tabulations — revenue by
    segment AND geography — and including them double-counts against either
    axis alone. They are dropped rather than assigned to one of the two.
    """
    out: dict[str, _Context] = {}
    for match in re.finditer(r"<context id=\"([^\"]+)\">(.*?)</context>", xml, re.S):
        body = match.group(2)
        members = re.findall(
            r"<xbrldi:explicitMember dimension=\"([^\"]+)\"[^>]*>([^<]+)<", body
        )
        start = re.search(r"<startDate>([^<]+)", body)
        end = re.search(r"<endDate>([^<]+)", body)

        # Drop the axes that qualify a fact without splitting it before deciding
        # whether this is a single-axis context. Exxon and Coca-Cola tag segment
        # revenue against BOTH the segment axis and `ConsolidationItemsAxis`, and
        # requiring exactly one dimension threw every one of those facts away —
        # the two filers with the most revenue facts in the sample returned
        # nothing at all.
        meaningful = [
            (axis.split(":")[-1], member)
            for axis, member in members
            if axis.split(":")[-1] not in IGNORE_AXES
        ]
        axis = member = None
        if len(meaningful) == 1:
            axis, member = meaningful[0]
        out[match.group(1)] = _Context(
            axis=axis,
            member=member,
            start=start.group(1) if start else None,
            end=end.group(1) if end else None,
        )
    return out


def _facts(xml: str, contexts: dict[str, _Context]) -> list[tuple[_Context, float]]:
    seen: set[tuple[str, str, str]] = set()
    rows: list[tuple[_Context, float]] = []
    for tag in REVENUE_TAGS:
        # Attribute order is not guaranteed. Microsoft emits `id=` before
        # `contextRef=`, and a pattern that assumed contextRef came first matched
        # none of its revenue facts — the filer with the cleanest segment
        # tagging in the sample looked like it had no revenue at all.
        pattern = rf"<us-gaap:{tag}\s[^>]*?contextRef=\"([^\"]+)\"[^>]*>([-\d.]+)<"
        for match in re.finditer(pattern, xml):
            context = contexts.get(match.group(1))
            if context is None or context.axis is None or context.start is None:
                continue
            if context.axis not in AXIS_KIND:
                continue
            # One value per (axis, member, period) — NOT per context.
            #
            # A filer often tags the same segment revenue under several contexts
            # that differ only in an axis we ignore: P&G reports each segment
            # both plainly and again qualified by `ConsolidationItemsAxis`. Keyed
            # on the context those are two facts, the members double, and no
            # subset reconciles to revenue — so the whole split is discarded and
            # the company looks like it discloses nothing.
            key = (context.axis, context.member or "", context.start or "")
            if key in seen:
                continue
            seen.add(key)
            rows.append((context, float(match.group(2))))
    return rows


def consolidated_revenue(xml: str, period_start: str) -> float | None:
    """The undimensioned revenue for a given period, from the same document.

    **This is the reconciliation target and it has to come from here.** Using
    the latest quarter out of `History` instead compares an ANNUAL segment split
    against a QUARTERLY total whenever the most recent filing is a 10-K, and
    nothing then reconciles — Exxon, P&G and Coca-Cola all extracted their
    members correctly and had every one of them discarded on that mismatch.

    Same document, same period, no join.
    """
    contexts = parse_contexts(xml)
    candidates: list[float] = []
    for tag in REVENUE_TAGS:
        pattern = rf"<us-gaap:{tag}\s[^>]*?contextRef=\"([^\"]+)\"[^>]*>([-\d.]+)<"
        for match in re.finditer(pattern, xml):
            context = contexts.get(match.group(1))
            # Undimensioned: the consolidated figure, not a slice of it.
            if context and context.axis is None and context.start == period_start:
                candidates.append(float(match.group(2)))
        if candidates:
            break

    if not candidates:
        return None
    # The LARGEST, where a filer tags more than one undimensioned revenue figure
    # for the period. UnitedHealth reports a total and several components of it
    # against the same context, and taking the first found returned a component
    # — against which no segment split could possibly reconcile.
    return max(candidates)


def from_instance(xml: str, uri: str) -> list[SegmentLine]:
    """Every single-axis revenue split in the document, newest period first.

    The comparative is matched by axis and member across periods, so a segment
    that did not exist a year ago simply has no growth rather than being paired
    with an unrelated member.
    """
    contexts = parse_contexts(xml)
    rows = _facts(xml, contexts)
    if not rows:
        return []

    # The most recent period start is the quarter being reported. Everything
    # sharing that start is current; the same duration a year earlier is the
    # comparative.
    starts = sorted({c.start for c, _ in rows if c.start}, reverse=True)
    if not starts:
        return []
    current_start = starts[0]
    current_end = next(
        (c.end for c, _ in rows if c.start == current_start and c.end), None
    )

    current: dict[tuple[str, str], float] = {}
    prior: dict[tuple[str, str], float] = {}
    prior_start = ""
    for context, value in rows:
        key = (context.axis or "", context.member or "")
        if context.start == current_start:
            current[key] = value
        # Same duration, a year earlier. Comparing durations rather than
        # trusting order keeps a year-to-date column from being read as the
        # prior quarter.
        elif (
            context.start
            and context.start < current_start
            and _same_length(context.start, context.end, current_start, current_end)
        ):
            prior[key] = value
            prior_start = context.start

    lines: list[SegmentLine] = []
    for (axis, member), value in current.items():
        kind = AXIS_KIND.get(axis)
        if kind is None:
            continue
        lines.append(
            SegmentLine(
                kind=kind,
                label=_humanise(member),
                value=value,
                prior_value=prior.get((axis, member)),
                unit="USD",
                period_label=current_start,
                prior_period_label=prior_start,
                report=axis,
                source_uri=uri,
                axis=axis,
                member=member,
            )
        )
    return lines


def _same_length(
    start: str | None, end: str | None, ref_start: str | None, ref_end: str | None
) -> bool:
    """Within a fortnight of the reference duration.

    Fiscal quarters are 13 weeks but 52/53-week calendars drift, so an exact
    match would reject a legitimate comparative. A year-to-date column is months
    longer and never gets through this.
    """
    try:
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
        reference = (date.fromisoformat(ref_end) - date.fromisoformat(ref_start)).days
    except (TypeError, ValueError):
        return False
    return abs(span - reference) <= 14


# --------------------------------------------------------------------------- #
# reconciling, which is what makes it usable
# --------------------------------------------------------------------------- #


def _best_subset(
    group: list[SegmentLine], target: float, tolerance: float
) -> list[SegmentLine] | None:
    """The finest subset of these members that sums to reported revenue.

    **An axis is a hierarchy flattened into members.** NVDA tags Data Center at
    75,246 and Hyperscale at 37,869 and AI Clouds at 37,377 all against
    `ProductOrServiceAxis` — the parent and its two children, siblings as far as
    the axis is concerned. Summing every member gives 156,861 against 81,615 of
    actual revenue.

    Nothing in the taxonomy says which is which. Arithmetic does: one subset
    reconciles to the revenue the company reported, and where two do — {Data
    Center, Edge} and {Hyperscale, AI Clouds, Edge} — the finer is the better
    driver tree, so ties break toward more members.
    """
    n = len(group)
    if n == 0 or n > MAX_SUBSET_SEARCH:
        return None

    best: list[SegmentLine] | None = None
    for mask in range(1, 1 << n):
        chosen = [group[i] for i in range(n) if mask & (1 << i)]
        total = sum(line.value for line in chosen)
        if abs(total - target) / abs(target) > tolerance:
            continue
        if best is None or len(chosen) > len(best):
            best = chosen
    return best


def reconcile(
    lines: list[SegmentLine], reported_revenue: float | None, tolerance: float = 0.02
) -> tuple[list[SegmentLine], list[str]]:
    """Keep only the splits whose parts sum to the revenue the company reported.

    **The check that makes this usable rather than plausible.** A split that
    picks up a parent alongside its children double-counts, and one missing a
    member under-counts; both produce a decomposition that looks structured and
    is wrong, and neither is visible by looking at the numbers.

    A split that cannot reconcile is dropped with its reason rather than passed
    on partially — a driver tree missing a third of the revenue is worse than no
    driver tree, because a lens will build on it and never know.
    """
    if not reported_revenue:
        return [], ["no reported revenue to reconcile any split against"]

    kept: list[SegmentLine] = []
    notes: list[str] = []
    by_kind: dict[Kind, list[SegmentLine]] = {}
    for line in lines:
        by_kind.setdefault(line.kind, []).append(line)

    for kind, group in by_kind.items():
        if kind == "concentration":
            # A concentration disclosure names the customers above a threshold.
            # It is not meant to be exhaustive and rejecting it for that would
            # throw away the one disclosure saying who actually buys.
            kept.extend(group)
            continue

        if len(group) == 1:
            # One member is not a split. It is the consolidated total wearing a
            # dimension, and it reconciles perfectly while saying nothing.
            notes.append(f"{kind}: a single member is not a decomposition")
            continue

        subset = _best_subset(group, reported_revenue, tolerance)
        if subset and len(subset) > 1:
            kept.extend(subset)
            if len(subset) < len(group):
                notes.append(
                    f"{kind}: {len(group)} members collapsed to the {len(subset)} that "
                    "reconcile to revenue — the rest are parents of those, and "
                    "counting both double-counts"
                )
            continue

        total = sum(line.value for line in group)
        notes.append(
            f"{kind}: no subset of the {len(group)} members sums to reported revenue "
            f"of {reported_revenue:,.0f} (all together they give {total:,.0f}) — "
            "dropped rather than used partially"
        )
        log.info("segment_split_rejected", kind=kind, members=len(group))

    return kept, notes


# --------------------------------------------------------------------------- #


def to_block(lines: list[SegmentLine]) -> str:
    """The decomposition as prose for the Drivers and Margins lenses.

    Growth is printed beside every part because it is the number the lens is
    being asked to forecast, and it came out of the filing rather than out of
    anyone's model.
    """
    if not lines:
        return ""

    by_kind: dict[Kind, list[SegmentLine]] = {}
    for line in lines:
        by_kind.setdefault(line.kind, []).append(line)

    titles = {
        "product": "Revenue by product or service",
        "segment": "Revenue by reportable segment",
        "geography": "Revenue by geography",
        "concentration": "Customer concentration",
    }
    out: list[str] = []
    for kind in ("product", "segment", "geography", "concentration"):
        group = by_kind.get(kind)
        if not group:
            continue
        head = group[0]
        out.append(
            f"{titles[kind]}  ({head.period_label}"
            + (f" vs {head.prior_period_label}" if head.prior_period_label else "")
            + ")"
        )
        total = sum(line.value for line in group) or 1.0
        for line in sorted(group, key=lambda x: -x.value):
            growth = f"{line.growth:+.1%}" if line.growth is not None else "n/a"
            out.append(
                f"  {line.label[:40]:42} {line.value / 1e6:>12,.0f}m"
                f"  {line.value / total:>6.1%}   YoY {growth:>8}"
            )
        out.append("")
    return "\n".join(out).rstrip()


def geo_mix(lines: list[SegmentLine]) -> list[tuple[str, float]]:
    """(region, share of revenue) — the Mechanical lens's FX exposure.

    The geographic revenue split IS the translation exposure, near enough: a
    filer reporting 15% of revenue from Taiwan carries that much of it whatever
    its hedging. Mapping a region to a currency is a separate and lossy step,
    which is why this returns regions rather than pretending to know.
    """
    geo = [line for line in lines if line.kind == "geography"]
    total = sum(line.value for line in geo)
    if not total:
        return []
    return [(line.label, line.value / total) for line in geo]


def as_of_ok(filed: date, as_of: date) -> bool:
    return filed <= as_of
