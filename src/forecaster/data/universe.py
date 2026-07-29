"""The prep-time universe: peers, sectors, and driver definitions.

Nothing in the pipeline is ticker-specific — everything keys off ticker → CIK →
filings. This file is the one deliberate exception, and it is a *warm start*
rather than a dependency: if the company handed over on the day is in here, the
Peer read and Drivers lenses begin with a known value chain and a known
decomposition. If it is not, they derive both from the 10-K. Slower, still works.

Two things this buys that are hard to get any other way:

- **The value chain, not just the sector.** A peer read needs a transmission
  mechanism, and "same GICS code" does not supply one. A supplier relationship
  does. So `suppliers` and `customers` are listed separately from `peers`.
- **Same quarter-end.** The strongest read-across comes from a company reporting
  on the *same weeks of demand*. A peer with a March year-end tells you much
  less about a company's June quarter than one with the same calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    sector: str
    fiscal_quarter_end: str  # "calendar" or the month the fiscal year ends
    peers: tuple[str, ...] = ()
    suppliers: tuple[str, ...] = ()
    customers: tuple[str, ...] = ()
    macro_series: tuple[str, ...] = ()
    drivers: str = ""

    def value_chain(self) -> tuple[str, ...]:
        """Everyone whose disclosure could implicate this company's quarter."""
        return tuple(dict.fromkeys(self.peers + self.suppliers + self.customers))


# The 26–27 August cluster plus the two high-variance rehearsal names. Prepared
# because forecasts lock on the 17th and this cluster resolves in 9–10 days —
# but the code path is identical for a company that is not in here.
UNIVERSE: dict[str, Company] = {
    "NVDA": Company(
        ticker="NVDA", name="NVIDIA", sector="semiconductors",
        fiscal_quarter_end="january",
        peers=("AMD", "AVGO", "MRVL", "INTC"),
        suppliers=("TSM", "SK hynix", "MU"),
        customers=("MSFT", "META", "GOOGL", "AMZN", "ORCL", "DELL", "SMCI"),
        macro_series=("IPG3344S", "DTWEXBGS"),
        drivers=(
            "Datacentre revenue is the quarter. Decompose as GPU units x ASP by "
            "product generation, cross-checked against named hyperscaler capex "
            "guidance. Gaming and Automotive are second order. 61 analysts cover "
            "this name with segment-level models — consensus is strong here and "
            "the correct answer is usually close to it."
        ),
    ),
    "MU": Company(
        ticker="MU", name="Micron", sector="semiconductors",
        fiscal_quarter_end="august",
        peers=("SK hynix", "Samsung", "WDC", "STX"),
        customers=("NVDA", "AAPL", "DELL", "HPQ"),
        macro_series=("IPG3344S", "WPU1178"),
        drivers=(
            "Bit shipments x price per bit, split DRAM and NAND. Memory pricing "
            "is the whole story and it moves 20%+ in a quarter. Consensus has "
            "been off by 15-40% for six straight quarters — the highest-variance "
            "name in the window and where an agent can actually show something."
        ),
    ),
    "FDX": Company(
        ticker="FDX", name="FedEx", sector="logistics",
        fiscal_quarter_end="may",
        peers=("UPS", "DHL", "XPO"),
        customers=("AMZN", "WMT", "TGT"),
        macro_series=("INDPRO", "RSAFS", "PAYEMS", "DFF"),
        drivers=(
            "Average daily package volume x yield per package, by segment "
            "(Express, Ground, Freight). Fuel surcharge is a pass-through that "
            "distorts yield. Two-sided surprise tails: one quarter -$1.22, "
            "another +$1.13, so the distribution matters more than the point."
        ),
    ),
    "CRM": Company(
        ticker="CRM", name="Salesforce", sector="software",
        fiscal_quarter_end="january",
        peers=("ORCL", "SAP", "NOW", "WDAY", "ADBE"),
        macro_series=("DTWEXBGS", "PAYEMS"),
        drivers=(
            "Subscription revenue from cRPO conversion. Current remaining "
            "performance obligation is disclosed and converts on a stable "
            "schedule — the most reliable software driver available. ~30% "
            "international revenue makes FX material."
        ),
    ),
    "COST": Company(
        ticker="COST", name="Costco", sector="retail",
        fiscal_quarter_end="august",
        peers=("WMT", "TGT", "BJ", "KR"),
        macro_series=("RSAFS", "CPIAUCSL", "UMCSENT"),
        drivers=(
            "Comparable sales x warehouse count, plus membership fee income "
            "(high margin, very predictable). Costco publishes MONTHLY sales, so "
            "most of a quarter's revenue is reconstructable before it reports — "
            "an unusual and exploitable disclosure. No formal EPS guidance."
        ),
    ),
    "ADBE": Company(
        ticker="ADBE", name="Adobe", sector="software",
        fiscal_quarter_end="november",
        peers=("CRM", "MSFT", "AUTODESK", "FIGMA"),
        macro_series=("DTWEXBGS",),
        drivers=(
            "Net new digital media ARR x pricing. Four of four recent beats in a "
            "tight +$0.10-0.19 band — low variance. Good for demonstrating "
            "calibration, poor for demonstrating edge."
        ),
    ),
    "DELL": Company(
        ticker="DELL", name="Dell", sector="hardware",
        fiscal_quarter_end="january",
        peers=("HPQ", "HPE", "SMCI", "LNVGY"),
        suppliers=("NVDA", "INTC", "MU"),
        macro_series=("INDPRO", "DTWEXBGS"),
        drivers=(
            "AI server backlog conversion x margin, against a declining PC base. "
            "Routinely beats on EPS while the stock falls on guidance — "
            "irrelevant if scoring is EPS surprise, a trap if it is price."
        ),
    ),
    "CRWD": Company(
        ticker="CRWD", name="CrowdStrike", sector="software",
        fiscal_quarter_end="january",
        peers=("PANW", "ZS", "S", "FTNT"),
        macro_series=("PAYEMS",),
        drivers=(
            "Net new ARR x module attach rate. Three of three beats in a very "
            "tight band."
        ),
    ),
    "SNOW": Company(
        ticker="SNOW", name="Snowflake", sector="software",
        fiscal_quarter_end="january",
        peers=("DDOG", "MDB", "PLTR"),
        customers=("MSFT", "AMZN"),
        macro_series=("PAYEMS",),
        drivers=(
            "Consumption revenue: credits consumed x price. Product revenue is "
            "the line that matters."
        ),
    ),
    "MRVL": Company(
        ticker="MRVL", name="Marvell", sector="semiconductors",
        fiscal_quarter_end="january",
        peers=("AVGO", "NVDA", "AMD"),
        customers=("AMZN", "GOOGL", "MSFT"),
        macro_series=("IPG3344S",),
        drivers=(
            "Custom AI silicon ramp x content per unit, plus a cyclical "
            "networking base."
        ),
    ),
    "ULTA": Company(
        ticker="ULTA", name="Ulta Beauty", sector="retail",
        fiscal_quarter_end="january",
        peers=("EL", "COTY", "TGT", "SBH"),
        macro_series=("RSAFS", "UMCSENT"),
        drivers="Comparable sales (transactions x ticket) x store count.",
    ),
    "DG": Company(
        ticker="DG", name="Dollar General", sector="retail",
        fiscal_quarter_end="january",
        peers=("DLTR", "WMT", "FIVE"),
        macro_series=("RSAFS", "CPIAUCSL", "UNRATE"),
        drivers=(
            "Comparable sales x store count, with a consumables mix that moves "
            "gross margin."
        ),
    ),
}

# Companies that are not in the universe still need a sector guess for the Macro
# lens. Coarse and honest: better a wrong-but-declared sector than a silent
# "unknown" that makes the lens abstain for the wrong reason.
DEFAULT_MACRO = ("DFF", "DGS10", "DTWEXBGS", "CPIAUCSL")


@dataclass
class Profile:
    """What acquisition needs to know about a company it may never have seen."""

    ticker: str
    sector: str = "unknown"
    peers: tuple[str, ...] = ()
    macro_series: tuple[str, ...] = field(default=DEFAULT_MACRO)
    drivers: str = ""
    prepared: bool = False


def profile(ticker: str) -> Profile:
    """Warm start if we prepared for this company, cold start if not.

    `prepared` is surfaced in the run manifest so a thin peer read on an
    unprepared name is explainable rather than mysterious.
    """
    company = UNIVERSE.get(ticker.upper())
    if company is None:
        return Profile(ticker=ticker.upper())
    return Profile(
        ticker=company.ticker,
        sector=company.sector,
        peers=company.value_chain(),
        macro_series=company.macro_series or DEFAULT_MACRO,
        drivers=company.drivers,
        prepared=True,
    )
