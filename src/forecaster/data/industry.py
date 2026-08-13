"""Industry size and market share, built from the filings rather than bought.

**The question this answers is the one that separates a good quarter from a good
company:** is revenue growing because the market is growing, or because this
company is taking share? Those decompose the same top line into two completely
different forecasts, and consensus almost never separates them — a sell-side
model forecasts company revenue directly and the market/share split lives in the
analyst's head, if anywhere.

    company growth  =  market growth  +  share change

Both halves are computable from filings we already fetch. Sum the revenue of
every SIC peer and you have a bottom-up industry size; divide the company's
revenue into it and you have share; do it for two periods and you have the split.

**Why bottom-up rather than a TAM number.** A purchased market-size figure is a
consultancy's estimate of a boundary they drew, published on a lag, and
unauditable. A sum of filed revenues is none of those things: every component
is a number a company signed, the boundary is the SIC code the filer chose for
itself, and it recomputes every quarter for free.

**What it is honestly not.** SIC is a coarse boundary — it will put a company
next to firms it does not compete with and miss competitors filed under another
code, and it covers only US filers. So this measures share of *the filed peer
set*, which is a proxy for share of market and is stated as one. The TREND in
that proxy is far more reliable than its level, and the trend is what a forecast
actually needs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

# Below this a "market" is a handful of companies and the share number is noise.
MIN_PEERS = 3

# A peer whose revenue is this far outside the median is usually a
# misclassification — a conglomerate filed under a narrow code, or a shell.
# Winsorising rather than dropping keeps the boundary honest while stopping one
# entry from being the whole market.
OUTLIER_MULTIPLE = 25.0


@dataclass(frozen=True)
class PeerRevenue:
    ticker: str
    revenue: float
    prior_revenue: float | None = None

    @property
    def growth(self) -> float | None:
        if not self.prior_revenue:
            return None
        return self.revenue / self.prior_revenue - 1


@dataclass
class Industry:
    ticker: str
    sic: str | None
    sic_label: str = ""
    peers: list[PeerRevenue] = field(default_factory=list)
    company: PeerRevenue | None = None
    excluded: list[str] = field(default_factory=list)

    @property
    def size(self) -> float | None:
        """Bottom-up: the sum of everything filed under this code, including us."""
        if not self.peers or self.company is None:
            return None
        return self.company.revenue + sum(p.revenue for p in self.peers)

    @property
    def prior_size(self) -> float | None:
        parts = [
            p.prior_revenue for p in self.peers if p.prior_revenue is not None
        ]
        if not parts or self.company is None or self.company.prior_revenue is None:
            return None
        return self.company.prior_revenue + sum(parts)

    @property
    def share(self) -> float | None:
        size = self.size
        if not size or self.company is None:
            return None
        return self.company.revenue / size

    @property
    def prior_share(self) -> float | None:
        size = self.prior_size
        if not size or self.company is None or self.company.prior_revenue is None:
            return None
        return self.company.prior_revenue / size

    @property
    def market_growth(self) -> float | None:
        prior = self.prior_size
        size = self.size
        if not prior or not size:
            return None
        return size / prior - 1

    @property
    def share_change(self) -> float | None:
        """In percentage points of share, not as a growth rate."""
        now, before = self.share, self.prior_share
        if now is None or before is None:
            return None
        return now - before

    def decompose(self) -> tuple[float, float] | None:
        """(from the market, from share) — the company's growth, split.

        The two do not add exactly, because share is a ratio and the residual is
        the cross term. Reported as the approximation it is rather than forced to
        reconcile, because forcing it would mean inventing an allocation.
        """
        company = self.company.growth if self.company else None
        market = self.market_growth
        if company is None or market is None:
            return None
        return market, company - market

    @property
    def peer_growth_median(self) -> float | None:
        """What the typical filer under this code did. A company growing 60% in a
        market growing 8% is a different story from one growing 60% in a market
        growing 55%, and the headline number cannot tell them apart."""
        rates = [p.growth for p in self.peers if p.growth is not None]
        return statistics.median(rates) if rates else None


def build(
    ticker: str,
    sic: str | None,
    sic_label: str,
    company: PeerRevenue | None,
    peers: list[PeerRevenue],
) -> Industry:
    """Assemble the picture, excluding entries that would distort the boundary."""
    result = Industry(ticker=ticker, sic=sic, sic_label=sic_label, company=company)
    if company is None or not peers:
        result.peers = list(peers)
        return result

    revenues = [p.revenue for p in peers if p.revenue > 0]
    median = statistics.median(revenues) if revenues else 0.0

    for peer in peers:
        if peer.revenue <= 0:
            result.excluded.append(f"{peer.ticker}: no revenue reported")
            continue
        if median and peer.revenue > median * OUTLIER_MULTIPLE:
            # A conglomerate filed under a narrow code would otherwise BE the
            # market, and the company's share would collapse for a reason that
            # has nothing to do with competition.
            result.excluded.append(
                f"{peer.ticker}: {peer.revenue / median:.0f}x the median filer — "
                "almost certainly a misclassification, excluded from the size"
            )
            continue
        result.peers.append(peer)

    log.info(
        "industry_built", ticker=ticker, sic=sic, peers=len(result.peers),
        excluded=len(result.excluded),
        share=round(result.share, 4) if result.share else None,
    )
    return result


def to_block(result: Industry) -> str:
    """For the Market lens. Leads with the decomposition, because that is the
    part consensus does not do."""
    if result.company is None or len(result.peers) < MIN_PEERS:
        return (
            "(no industry picture — fewer than three peers filed under this SIC "
            "code with reported revenue. Share of a three-company set is noise, "
            "so nothing is claimed rather than a thin number being offered.)"
        )

    lines = [
        f"INDUSTRY — {result.ticker}, SIC {result.sic} {result.sic_label}. Built "
        f"bottom-up from {len(result.peers)} peers' filed revenue, not from a "
        "purchased market-size estimate.",
        "",
    ]

    size = result.size
    if size:
        lines.append(f"  filed peer-set revenue   {size / 1e9:>12,.1f}bn")
    if result.share is not None:
        lines.append(f"  this company's share     {result.share:>12.1%}")
    if result.prior_share is not None:
        lines.append(f"  a year ago               {result.prior_share:>12.1%}")

    split = result.decompose()
    if split:
        market, share_effect = split
        lines += [
            "",
            "  Growth decomposed — the split consensus rarely makes:",
            f"    from the market growing   {market:+.1%}",
            f"    from taking share         {share_effect:+.1%}",
        ]
    median = result.peer_growth_median
    if median is not None:
        lines.append(f"    median peer grew          {median:+.1%}")

    lines += [
        "",
        "  Share of the FILED PEER SET, which is a proxy for share of market. "
        "SIC is a coarse boundary: it includes firms this company does not "
        "compete with and misses competitors filed elsewhere or listed abroad. "
        "The TREND is far more reliable than the level, and the trend is what a "
        "forecast needs.",
    ]
    if result.excluded:
        lines += ["", "  Excluded from the size:"] + [
            f"    {reason}" for reason in result.excluded[:4]
        ]
    return "\n".join(lines)
