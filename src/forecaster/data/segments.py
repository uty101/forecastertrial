"""Segment, geographic and customer-concentration disclosure, from the filing.

**This file exists because the alternative was a hardcoded list of twelve
companies with their driver decomposition written out by hand.** That worked for
twelve names and produced nothing for the thousands of others, which is the
wrong shape for a system handed a ticker at 10am.

Everything here derives from the filing itself, for any XBRL filer since 2009.

**Why not `companyfacts`.** Segment revenue is tagged against a dimension axis —
`StatementBusinessSegmentsAxis`, `SegmentGeographicalGroupsOfCountriesAxis` —
and the `companyfacts` endpoint exposes only facts with NO dimensions. Every
segment number a filer reports is invisible to it. That is the same limitation
that hid Visa's diluted share count, and no tag list fixes it: the numbers are
not in the response.

**What is used instead.** Every filing folder carries `FilingSummary.xml`, an
index of the seventy-odd rendered report tables SEC generates from the XBRL. The
segment note is one of them. Find it by name, fetch the R-file, read the table.
No model call, deterministic, and the source is a filing URL that cites cleanly.

The tables come with the prior-year comparative in the adjacent column, so
segment GROWTH falls out of the filing rather than out of an assumption — which
is the whole point of a driver decomposition.

**Three things this closes at once.** The Drivers lens gets a real bottom-up
build on any ticker. Margins gets the mix argument it exists to make. And the
geographic table IS the FX exposure the Mechanical lens needs, so the one leg of
that lens I had written off as unavailable turns out to be in the same document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import structlog

log = structlog.get_logger()

Kind = Literal["segment", "geography", "product", "concentration"]

# Report names, matched case-insensitively against `ShortName` in the index.
# Ordered by how directly each answers "how does this company's revenue split".
#
# The `Details` suffix matters: SEC renders each note three times — the narrative,
# the tables block, and the tagged detail. Only the last carries machine-readable
# numbers, and matching without it returns a page of prose.
#
# SPECIFIC BEFORE GENERIC, and the order is load-bearing. NVDA titles every one
# of its notes "Segment Information — …", so a generic `segment information`
# pattern checked first claims the geographic table too and the FX exposure
# disappears. Matching stops at the first hit, so the narrow patterns have to
# come first and the catch-all last.
NAME_PATTERNS: tuple[tuple[Kind, tuple[str, ...]], ...] = (
    ("geography", ("geographic", "by country", "by region")),
    ("concentration", ("concentration",)),
    ("product", ("revenue by market", "revenue by product", "disaggregat",
                 "net sales", "revenue by category", "by market platform")),
    ("segment", ("reportable segment", "operating segment", "segment revenue",
                 "segment information", "segment financial", "business segment")),
)

# Banks overload the word: "Loans — By Portfolio Segment" is a loan book, not a
# line of business. Anything matching these is skipped regardless of what else
# it matched, because a loan portfolio parsed as a revenue split produces a
# decomposition that does not sum to revenue and is wrong in a way that looks
# structured.
EXCLUDE = (
    "portfolio segment", "loans", "allowance", "fair value", "financial instrument",
    "maturit", "derivative", "credit quality", "impairment", "goodwill by",
    # A narrative page carries the prose facts — "number of reportable segments:
    # 2" — and no revenue schedule. Parsed as one it yields rows like "Number of
    # operating segments = 2" sitting beside revenue in millions.
    "narrative",
)

MAX_REPORTS = 8


@dataclass(frozen=True)
class SegmentLine:
    """One row of a disaggregation table, with its comparative."""

    kind: Kind
    label: str
    value: float
    prior_value: float | None
    unit: str
    period_label: str
    prior_period_label: str
    report: str
    source_uri: str

    @property
    def growth(self) -> float | None:
        """Year-over-year, straight from the filing's own two columns.

        Not an assumption and not a derivation across two documents — the
        comparative is printed beside the figure in the same table, which is
        what makes a segment build defensible rather than reconstructed.
        """
        if not self.prior_value:
            return None
        return self.value / self.prior_value - 1


def _clean(text: str) -> str:
    text = re.sub(r"&#160;|&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def _scale(header: str) -> float:
    """`$ in Millions` in the table header, applied to every figure below it.

    A table read at face value when it is quoted in millions is wrong by six
    orders of magnitude and internally consistent — the segments still sum to
    the total, so nothing downstream catches it.
    """
    low = header.lower()
    if "in billions" in low:
        return 1e9
    if "in millions" in low:
        return 1e6
    if "in thousands" in low:
        return 1e3
    return 1.0


def _number(cell: str) -> float | None:
    text = _clean(cell).replace("$", "").replace(",", "").strip()
    if not text or text in {"-", "—", "–"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def find_reports(summary_xml: str) -> list[tuple[Kind, str, str]]:
    """(kind, short name, R-file) for every disaggregation table in the filing.

    Ranked by `NAME_PATTERNS` order, so a product/market split — the closest
    thing to a driver tree — is preferred over a bare segment schedule.
    """
    found: list[tuple[int, Kind, str, str]] = []
    for block in re.findall(r"<Report[^>]*>(.*?)</Report>", summary_xml, re.S):
        name_match = re.search(r"<ShortName>(.*?)</ShortName>", block, re.S)
        file_match = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", block, re.S)
        if not name_match or not file_match:
            continue
        name = _clean(name_match.group(1))
        low = name.lower()
        if "(details)" not in low:
            continue
        if any(bad in low for bad in EXCLUDE):
            continue
        for rank, (kind, patterns) in enumerate(NAME_PATTERNS):
            if any(p in low for p in patterns):
                found.append((rank, kind, name, file_match.group(1)))
                break

    found.sort(key=lambda row: row[0])
    return [(kind, name, path) for _, kind, name, path in found[:MAX_REPORTS]]


def parse_report(html: str, kind: Kind, report: str, uri: str) -> list[SegmentLine]:
    """Read one rendered R-file table into lines.

    SEC's renderer emits a stable shape: a caption carrying the units, a header
    row of period labels, then one row per tagged fact where the first cell is
    the label and the rest are values in period order. Rows whose label repeats
    a boilerplate axis header ("Revenue from External Customer [Line Items]")
    carry no figures and are skipped.
    """
    caption = re.search(r"<th[^>]*class=\"tl\"[^>]*>(.*?)</th>", html, re.S)
    scale = _scale(_clean(caption.group(1))) if caption else 1.0

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    periods: list[str] = []
    lines: list[SegmentLine] = []
    # The axis label most recently seen. SEC renders a dimension member as its
    # own row and the figures for it on the rows beneath, so the member name has
    # to be carried down.
    member: str | None = None

    for row in rows:
        headers = re.findall(r"<th[^>]*>(.*?)</th>", row, re.S)
        if headers and not periods:
            candidates = [_clean(h) for h in headers[1:]]
            periods = [c for c in candidates if re.search(r"\d{4}", c)]
            continue

        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        label_match = re.search(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        if not label_match:
            continue
        label = _clean(re.sub(r"<[^>]+>", " ", label_match.group(1)))
        if not label:
            continue

        values = [_number(re.sub(r"<[^>]+>", " ", c)) for c in cells]
        values = [v for v in values if v is not None]

        if not values:
            # A bare label with no figures is the dimension member itself —
            # "United States", "Data Center" — and the figures for it are on the
            # rows beneath, so it has to be carried down.
            #
            # Unless it is the section header. The market-platform table heads
            # each block with "Revenue from External Customer [Line Items]",
            # which the bracket test catches; the geographic table heads it with
            # a bare "Revenues", which it does not. That one word overwrote the
            # member on every row and every geography came back labelled
            # "Revenues", so the whole table parsed to nothing usable.
            if "[" not in label and len(label) < 80 and not _is_boilerplate(label):
                member = label
            continue

        # A tagged line under a member: the member is what it is about.
        name = member if member and _is_boilerplate(label) else label
        if not name or _is_boilerplate(name):
            continue

        lines.append(
            SegmentLine(
                kind=kind,
                label=name,
                value=values[0] * scale,
                prior_value=values[1] * scale if len(values) > 1 else None,
                unit="USD",
                period_label=periods[0] if periods else "",
                prior_period_label=periods[1] if len(periods) > 1 else "",
                report=report,
                source_uri=uri,
            )
        )

    return lines


def _is_boilerplate(label: str) -> bool:
    low = label.lower()
    return (
        "[line items]" in low
        or "[abstract]" in low
        or "[member]" in low
        or "[axis]" in low
        or low in {"revenue", "revenues", "total", "net sales"}
    )


MAX_SUBSET_SEARCH = 18


def _best_subset(
    group: list[SegmentLine], target: float, tolerance: float
) -> list[SegmentLine] | None:
    """The finest subset of these lines that sums to reported revenue.

    **A rendered segment table is a hierarchy flattened into rows.** NVDA's
    market-platform note lists Data Center at 75,246 and then Hyperscale at
    37,869 and AI Clouds at 37,377 underneath it — the parent and its two
    children, all as sibling rows. Summing every row double-counts: 156,861
    against 81,615 of actual revenue.

    Nothing in the text says which is which. What does say it is arithmetic:
    exactly one subset of these rows reconciles to the revenue the company
    reported, and here there are two — {Data Center, Edge} and {Hyperscale,
    AI Clouds, Edge}. The finer of the two is the better driver tree, so ties
    break toward more members.

    Exhaustive over subsets, capped: a filer with more than eighteen rows in one
    disaggregation table is disclosing something other than a segment split, and
    guessing at it is worse than declining.
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


def reconcile(lines: list[SegmentLine], reported_revenue: float | None,
              tolerance: float = 0.02) -> tuple[list[SegmentLine], list[str]]:
    """Keep only the splits whose parts sum to the revenue the company reported.

    **The check that makes this usable rather than plausible.** A parse that
    picks up a sub-segment alongside its parent double-counts, and a parse that
    misses a member under-counts; both produce a decomposition that looks
    structured and is wrong. Neither is detectable by looking at the numbers.

    A split that does not reconcile is dropped with its reason rather than
    passed on partially — a driver tree missing a third of the revenue is worse
    than no driver tree, because a lens will build on it and never know.
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
            # A concentration note lists customers above a threshold; it is not
            # meant to sum to revenue and rejecting it for that would be wrong.
            kept.extend(group)
            continue

        subset = _best_subset(group, reported_revenue, tolerance)
        if subset:
            kept.extend(subset)
            if len(subset) < len(group):
                notes.append(
                    f"{kind}: {len(group)} rows collapsed to the {len(subset)} that "
                    f"reconcile to revenue — the rest are parents or subtotals of "
                    "those, and counting both double-counts"
                )
            continue

        total = sum(line.value for line in group)
        notes.append(
            f"{kind}: no subset of the {len(group)} rows sums to reported revenue "
            f"of {reported_revenue:,.0f} (all of them together give {total:,.0f}) — "
            "dropped rather than used partially"
        )
        log.info("segment_split_rejected", kind=kind, rows=len(group))

    return kept, notes


def to_block(lines: list[SegmentLine]) -> str:
    """The decomposition as prose for the Drivers and Margins lenses.

    Growth is printed beside each part because it is the number the lens is
    being asked to forecast, and it came out of the filing rather than out of
    anyone's model.
    """
    if not lines:
        return ""

    by_kind: dict[Kind, list[SegmentLine]] = {}
    for line in lines:
        by_kind.setdefault(line.kind, []).append(line)

    titles = {
        "product": "Revenue by product or market",
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
            f"{titles[kind]} — {head.report}"
            + (f"  ({head.period_label} vs {head.prior_period_label})"
               if head.prior_period_label else "")
        )
        total = sum(line.value for line in group) or 1.0
        for line in group:
            share = line.value / total
            growth = (f"{line.growth:+.1%}" if line.growth is not None else "n/a")
            out.append(
                f"  {line.label[:44]:46} {line.value / 1e6:>12,.0f}m"
                f"  {share:>6.1%} of total   YoY {growth:>8}"
            )
        out.append("")
    return "\n".join(out).rstrip()


def geo_mix(lines: list[SegmentLine]) -> list[tuple[str, float]]:
    """(region, share of revenue) — the Mechanical lens's FX exposure.

    The geographic revenue table IS the currency exposure, near enough: a filer
    reporting 22% of revenue from Taiwan has that much translation risk whatever
    its hedging. Mapping a region to a currency is a separate step and a lossy
    one, which is why this returns regions rather than pretending to know.
    """
    geo = [line for line in lines if line.kind == "geography"]
    total = sum(line.value for line in geo)
    if not total:
        return []
    return [(line.label, line.value / total) for line in geo]


def as_of_ok(filed: date, as_of: date) -> bool:
    return filed <= as_of
