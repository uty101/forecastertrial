"""What the outside world does to this company, and which line it does it to.

**The discipline this module exists to enforce: every external series has to name
the line it moves.** "Copper is up 14%" is a fact about copper. "Copper is up 14%
and this company buys copper, so gross margin compresses" is a forecast. The gap
between the two is where most macro commentary lives and none of it reaches a
number.

So each exposure carries the model driver it feeds:

    geography   -> revenue_growth   weighted by the geographic revenue split
    input cost  -> gross_margin     the company buys this and sells the output
    energy      -> gross_margin     for anyone who runs plants, servers or trucks
    rates       -> interest         already handled by the model's own schedule

**Geographic exposure is only computable because segments are.** The geographic
revenue split from the XBRL instance says 78% of NVDA's revenue is US and 15% is
Taiwan. Multiply each region's share by that economy's growth and you get a
demand-weighted growth rate that is specific to this company rather than to its
sector — and it changes when the mix changes, which is exactly when a top-down
sector view stops working.

**Input costs are mapped from SIC, not from a hand-written list.** A company's own
filing states its industry code; the code implies what it buys. A semiconductor
firm's costs are wafers, energy and equipment; an airline's are fuel and labour.
That mapping is coarse and it is derived, which beats precise and prepared.

Everything degrades to nothing rather than to a guess. A region we cannot map to
a series contributes no growth rather than the world average, and the block says
which regions were unmapped — a demand-weighted rate covering 60% of revenue is a
different claim from one covering 98%.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import structlog

log = structlog.get_logger()

Drives = Literal["revenue_growth", "gross_margin", "opex_pct_revenue", "none"]

# Region -> FRED real activity series. Matched loosely against the member label
# the filing used, because filers name regions every possible way: "US",
# "United States", "Americas", "U.S. and Canada".
#
# Real GDP where it exists; industrial production where it is timelier and the
# customer is industrial. The point is a demand proxy that MOVES, not a precise
# national accounts figure — a quarterly forecast cares about the second
# derivative and GDP is published late.
REGION_SERIES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("united states", "u.s.", "us", "usa", "america", "north america", "domestic"),
     "GDPC1", "US real GDP"),
    (("china", "prc", "hong kong", "greater china"),
     "CHNGDPNQDSMEI", "China GDP"),
    (("taiwan", "twn", "tw"), "TWNPROINDMISMEI", "Taiwan industrial production"),
    (("japan", "jpn", "jp"), "JPNRGDPEXP", "Japan real GDP"),
    (("europe", "emea", "euro", "germany", "france", "united kingdom", "eu"),
     "CLVMNACSCAB1GQEA19", "Euro area real GDP"),
    (("korea", "kor", "singapore", "asia pacific", "apac", "asia"),
     "KORPROINDMISMEI", "Korea industrial production"),
    (("india", "ind"), "INDPROINDMISMEI", "India industrial production"),
    (("canada", "can"), "NGDPRSAXDCCAQ", "Canada real GDP"),
    (("mexico", "latin america", "brazil", "south america"),
     "MEXPROINDMISMEI", "Mexico industrial production"),
)

# SIC prefix -> the input costs that actually move this industry's gross margin.
# Two digits is the right resolution: finer is a taxonomy exercise, coarser puts
# an airline and a bank in the same bucket.
SIC_INPUTS: tuple[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (("36", "35", "38"),  # electronics, computers, instruments
     (("PCU334413334413", "semiconductor producer prices"),
      ("APU000072610", "US electricity price"),
      ("PCOPPUSDM", "copper"))),
    (("28",),  # chemicals, pharmaceuticals
     (("WPU06", "chemicals PPI"),
      ("DHHNGSP", "Henry Hub natural gas"))),
    (("20", "21"),  # food, beverage, tobacco
     (("PWHEAMTUSDM", "wheat"), ("PSUGAISAUSDM", "sugar"),
      ("APU000072610", "US electricity price"))),
    (("33", "34"),  # primary and fabricated metals
     (("PCOPPUSDM", "copper"), ("PIORECRUSDM", "iron ore"),
      ("DHHNGSP", "Henry Hub natural gas"))),
    (("29", "13"),  # petroleum, oil and gas extraction
     (("DCOILWTICO", "WTI crude"), ("DHHNGSP", "Henry Hub natural gas"))),
    (("45", "42", "47"),  # air transport, trucking, freight
     (("DCOILWTICO", "WTI crude"), ("WPU0571", "jet fuel PPI"))),
    (("53", "54", "56", "59"),  # retail
     (("PPIACO", "all commodities PPI"), ("DCOILWTICO", "WTI crude"))),
    (("73", "48"),  # software, services, communications
     (("APU000072610", "US electricity price"),)),
    (("37",),  # motor vehicles, aerospace
     (("PCOPPUSDM", "copper"), ("WPU101", "iron and steel PPI"),
      ("PALUMUSDM", "aluminium"))),
)

# Everyone runs something. A company with no industry-specific input still has
# an energy bill, and for a datacentre operator it is the second-largest line.
UNIVERSAL_INPUTS: tuple[tuple[str, str], ...] = (
    ("PPIACO", "all commodities PPI"),
)


@dataclass(frozen=True)
class Exposure:
    """One external series, what it is worth here, and which line it moves."""

    series_id: str
    label: str
    drives: Drives
    # Share of revenue exposed to it. For geography this is the revenue split;
    # for an input cost it is unknown without a cost breakdown filers do not
    # give, so it is None and the lens is told to size it from the evidence.
    weight: float | None = None
    change: float | None = None
    note: str = ""

    @property
    def contribution(self) -> float | None:
        """Weight times move, for the exposures where the weight is known.

        Only meaningful for geography: a 3% economy carrying 15% of revenue
        contributes 45bp of demand growth. An input cost has no comparable
        arithmetic without knowing what fraction of COGS it is, and inventing
        that fraction would be the whole error this module exists to avoid.
        """
        if self.weight is None or self.change is None:
            return None
        return self.weight * self.change


@dataclass
class ExposureMap:
    ticker: str
    geography: list[Exposure] = field(default_factory=list)
    inputs: list[Exposure] = field(default_factory=list)
    unmapped_regions: list[str] = field(default_factory=list)

    @property
    def covered(self) -> float:
        """Share of revenue whose region we could map to a series.

        Reported alongside the weighted rate, because a demand-weighted growth
        rate covering 60% of revenue is a different claim from one covering 98%
        and the number alone does not say which it is.
        """
        return sum(e.weight or 0.0 for e in self.geography)

    def weighted_growth(self) -> float | None:
        """Demand growth weighted by where this company's revenue actually comes
        from. Specific to the company rather than to its sector, and it changes
        when the mix changes — which is exactly when a top-down view breaks."""
        parts = [e.contribution for e in self.geography if e.contribution is not None]
        if not parts or self.covered <= 0:
            return None
        # Renormalised over covered revenue, so an unmapped region does not
        # silently read as zero growth.
        return sum(parts) / self.covered


def series_for_region(label: str) -> tuple[str, str] | None:
    """(series id, human label) for a geographic member, or None.

    Matched loosely because filers name regions every possible way — "US",
    "United States", "Americas", "U.S. and Canada" all mean the same demand.
    """
    low = re.sub(r"[^a-z ]", " ", label.lower())
    for names, series_id, human in REGION_SERIES:
        for name in names:
            # A short code needs a word boundary — "us" must not match
            # "Australia". A longer name is matched as a substring, because
            # filers pluralise and compound freely: "Americas", "Greater China",
            # "Europe, Middle East and Africa". Requiring a boundary on those
            # meant "Americas" failed to match "america" and 78% of a company's
            # revenue went unmapped on a plural.
            if len(name) <= 4:
                if re.search(rf"\b{re.escape(name)}\b", low):
                    return series_id, human
            elif name in low:
                return series_id, human
    return None


def inputs_for_sic(sic: str | None) -> tuple[tuple[str, str], ...]:
    """The commodity and energy series that move this industry's gross margin.

    From the company's own filed industry code rather than a prepared list, so
    it works on a ticker nobody thought about. Coarse and derived beats precise
    and prepared.
    """
    if not sic:
        return UNIVERSAL_INPUTS
    for prefixes, series in SIC_INPUTS:
        if any(str(sic).startswith(p) for p in prefixes):
            return series
    return UNIVERSAL_INPUTS


def build(
    ticker: str,
    geo_mix: list[tuple[str, float]],
    sic: str | None,
    changes: dict[str, float] | None = None,
) -> ExposureMap:
    """Map this company's revenue and cost base onto external series.

    `changes[series_id]` is the series' move over the window, supplied by the
    caller so this module stays free of the network and testable without one.
    """
    changes = changes or {}
    result = ExposureMap(ticker=ticker)

    for region, share in geo_mix or []:
        found = series_for_region(region)
        if found is None:
            result.unmapped_regions.append(region)
            continue
        series_id, human = found
        result.geography.append(
            Exposure(
                series_id=series_id,
                label=f"{region} — {human}",
                drives="revenue_growth",
                weight=share,
                change=changes.get(series_id),
                note=f"{share:.1%} of revenue is exposed to this economy",
            )
        )

    for series_id, human in inputs_for_sic(sic):
        result.inputs.append(
            Exposure(
                series_id=series_id,
                label=human,
                drives="gross_margin",
                weight=None,
                change=changes.get(series_id),
                note=(
                    "an input cost for this industry. The share of COGS it "
                    "represents is not disclosed, so size it from the evidence "
                    "rather than assuming one"
                ),
            )
        )

    log.info(
        "exposure_built", ticker=ticker, sic=sic,
        regions=len(result.geography), unmapped=result.unmapped_regions,
        inputs=len(result.inputs), covered=round(result.covered, 3),
    )
    return result


def series_ids(result: ExposureMap) -> list[str]:
    """Every series this company is exposed to — what to actually fetch."""
    return sorted({e.series_id for e in (*result.geography, *result.inputs)})


def to_block(result: ExposureMap) -> str:
    """For the Macro and Margins lenses. Each line names what it moves."""
    if not result.geography and not result.inputs:
        return ""

    lines = [
        f"EXTERNAL EXPOSURE — {result.ticker}. Each series names the model driver "
        "it moves; a series with no line attached is commentary.",
        "",
    ]

    if result.geography:
        weighted = result.weighted_growth()
        lines.append("Demand, weighted by where revenue actually comes from:")
        for exposure in result.geography:
            change = f"{exposure.change:+.1%}" if exposure.change is not None else "n/a"
            lines.append(
                f"  {exposure.label[:46]:48} weight {exposure.weight:>6.1%}"
                f"   move {change:>8}   -> revenue_growth"
            )
        if weighted is not None:
            lines.append(
                f"  weighted demand growth {weighted:+.2%} across "
                f"{result.covered:.0%} of revenue"
            )
        if result.unmapped_regions:
            lines.append(
                "  UNMAPPED: " + ", ".join(result.unmapped_regions)
                + " — excluded rather than assumed to be average, so the weighted "
                "rate above covers less than all revenue"
            )
        lines.append("")

    if result.inputs:
        lines.append("Input costs for this industry (from its own SIC code):")
        for exposure in result.inputs:
            change = f"{exposure.change:+.1%}" if exposure.change is not None else "n/a"
            lines.append(
                f"  {exposure.label[:46]:48} {'':13}   move {change:>8}"
                "   -> gross_margin"
            )
        lines.append(
            "  The share of COGS each represents is NOT disclosed. Size it from "
            "the evidence or say you cannot — an assumed cost share is the whole "
            "error this block exists to avoid."
        )

    return "\n".join(lines)
