"""Currency, and the three different things it tells you.

The FX leg was inert: the geographic split gave the exposure, but regions are
not currencies — "Americas" is not a rate — so the adjustment degraded to zero
and sat in the Mechanical lens doing nothing.

Fixing it properly means noticing that a currency move is **three separate
claims**, only the first of which the old design was reaching for:

    1. TRANSLATION   a Swiss company earning euros reports fewer francs when the
                     euro falls. Pure arithmetic on the revenue split, no view
                     required, and it lands in the Mechanical lens.

    2. COMPETITIVE   a strong home currency makes your costs expensive in the
                     currency your customers pay in. Nestlé pays Swiss wages and
                     sells in dollars; a rising franc is a margin problem its
                     dollar-cost competitors do not have. This is a claim about
                     RELATIVE POSITION and it belongs to the Market lens.

    3. DEMAND        a currency is a rough read on where an economy sits in the
                     cycle. A currency falling hard against the dollar is often
                     an economy under stress, and an economy under stress buys
                     less. This belongs to the Demand lens, weakly and with the
                     mechanism stated.

The old design collapsed all three into one number and then could not compute
it. This keeps them apart, because they move a forecast in different places and
two of them are not arithmetic at all.

**Currencies come from the same place regions do — the filing.** A company that
breaks out revenue by geography has told you its currency exposure, once the
regions are mapped. That mapping is the piece that was missing, and it is a
lookup rather than a judgement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

# Region label -> (currency, FRED series for that rate against the dollar).
#
# Matched the same way `exposure.series_for_region` matches: short codes on a
# word boundary, longer names as substrings. The list is regions as FILERS write
# them, not as an atlas would — "EMEA", "Greater China" and "Rest of world" are
# what actually appears in a segment note.
REGION_CURRENCY: tuple[tuple[str, str, str], ...] = (
    ("switzerland", "CHF", "DEXSZUS"),
    ("swiss", "CHF", "DEXSZUS"),
    ("eurozone", "EUR", "DEXUSEU"),
    ("euro area", "EUR", "DEXUSEU"),
    ("europe", "EUR", "DEXUSEU"),
    ("emea", "EUR", "DEXUSEU"),
    ("united kingdom", "GBP", "DEXUSUK"),
    ("britain", "GBP", "DEXUSUK"),
    ("japan", "JPY", "DEXJPUS"),
    ("china", "CNY", "DEXCHUS"),
    ("taiwan", "TWD", "DEXTAUS"),
    ("korea", "KRW", "DEXKOUS"),
    ("singapore", "SGD", "DEXSIUS"),
    ("india", "INR", "DEXINUS"),
    ("canada", "CAD", "DEXCAUS"),
    ("mexico", "MXN", "DEXMXUS"),
    ("brazil", "BRL", "DEXBZUS"),
    ("australia", "AUD", "DEXUSAL"),
    # Deliberately last: "americas" contains "america", and a company reporting
    # "Americas" is reporting mostly dollars.
    ("united states", "USD", ""),
    ("america", "USD", ""),
)

# A move smaller than this is noise on a quarterly revenue line, and reporting
# it as a finding trains a reader to ignore the ones that matter.
MATERIAL_MOVE = 0.02


@dataclass(frozen=True)
class CurrencyExposure:
    """One currency, how much revenue sits in it, and what it has done."""

    currency: str
    region: str
    weight: float
    series_id: str = ""
    change: float | None = None

    @property
    def translation_effect(self) -> float | None:
        """Revenue-weighted translation impact. Arithmetic, not a view."""
        return None if self.change is None else self.weight * self.change


@dataclass
class CurrencyMap:
    ticker: str
    reporting_currency: str = "USD"
    exposures: list[CurrencyExposure] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)

    @property
    def covered(self) -> float:
        return sum(e.weight for e in self.exposures)

    @property
    def translation(self) -> float | None:
        """Net translation effect on revenue, where the rates are known.

        None rather than zero when nothing is known. Zero is a measurement and
        this would be an absence, and the difference is the whole reason the old
        FX leg was misleading: it reported no effect when it meant no data.
        """
        effects = [
            e.translation_effect for e in self.exposures
            if e.translation_effect is not None
        ]
        return sum(effects) if effects else None

    @property
    def home_share(self) -> float:
        """Revenue earned in the currency the company reports in.

        The number that decides whether currency is a translation story or a
        competitiveness one. A company earning 90% of revenue in its reporting
        currency has almost no translation exposure and may still have a serious
        cost problem, because its COSTS are all in that currency.
        """
        return sum(
            e.weight for e in self.exposures if e.currency == self.reporting_currency
        )

    def competitive_note(self) -> str:
        """The second claim: what the home currency does to relative position.

        Not an adjustment — a fact for the Market lens to weigh. The mechanism is
        stated rather than implied, because "the franc is strong" is a fact about
        the franc and "the franc is strong and this company pays Swiss wages
        while selling in dollars" is an analysis.
        """
        home = next(
            (e for e in self.exposures if e.currency == self.reporting_currency), None
        )
        if home is None or home.change is None:
            return (
                f"No rate for the reporting currency ({self.reporting_currency}), "
                "so nothing is claimed about competitive position."
            )
        if abs(home.change) < MATERIAL_MOVE:
            return (
                f"{self.reporting_currency} has moved {home.change:+.1%}, inside "
                "the noise band — no competitiveness claim."
            )

        direction = "STRENGTHENED" if home.change > 0 else "WEAKENED"
        consequence = (
            "costs rise in the currencies customers pay in, so gross margin is "
            "pressured against competitors based elsewhere"
            if home.change > 0
            else "costs fall in the currencies customers pay in, which is a "
            "margin tailwind relative to competitors based elsewhere"
        )
        return (
            f"{self.reporting_currency} has {direction} {abs(home.change):.1%}. "
            f"{1 - self.home_share:.0%} of revenue is earned abroad while the "
            f"cost base is largely domestic, so {consequence}. This is a claim "
            "about RELATIVE POSITION, not a translation adjustment — the "
            "translation effect is counted separately and must not be "
            "double-counted here."
        )

    def demand_note(self) -> str:
        """The third claim: currency as a weak read on economic stress."""
        falling = [
            e for e in self.exposures
            if e.change is not None and e.change < -MATERIAL_MOVE * 2
        ]
        if not falling:
            return "No currency in the revenue base has moved enough to imply stress."
        worst = min(falling, key=lambda e: e.change or 0)
        return (
            f"{worst.currency} ({worst.region}, {worst.weight:.0%} of revenue) is "
            f"down {abs(worst.change or 0):.1%}. A currency falling this hard is "
            "often an economy under pressure, and an economy under pressure buys "
            "less — a WEAK signal, stated as one, and worth nothing unless the "
            "volume evidence agrees with it."
        )


def currency_for_region(label: str) -> tuple[str, str] | None:
    """`Greater China` -> (CNY, DEXCHUS). None when the region is not a currency.

    Region strings come from the filer and are matched case-insensitively as
    substrings, in the order declared — "Americas" must not win on "america"
    before a more specific match has been tried.
    """
    lowered = label.lower()
    for token, currency, series in REGION_CURRENCY:
        if token in lowered:
            return currency, series
    return None


def build(
    ticker: str,
    geography: list[tuple[str, float]],
    reporting_currency: str = "USD",
    rates: dict[str, float] | None = None,
) -> CurrencyMap:
    """Map a revenue-by-geography split onto currencies.

    `geography` is [(region label, share of revenue)] straight from the segment
    note. `rates` is {series_id: fractional change} where known — absent rates
    give an exposure with no change rather than an assumed zero.
    """
    rates = rates or {}
    exposures: list[CurrencyExposure] = []
    unmapped: list[str] = []

    for label, weight in geography:
        mapped = currency_for_region(label)
        if mapped is None:
            unmapped.append(label)
            continue
        currency, series = mapped
        exposures.append(
            CurrencyExposure(
                currency=currency,
                region=label,
                weight=weight,
                series_id=series,
                change=rates.get(series),
            )
        )

    # One currency, one line. A filer reporting "Germany" and "France" has two
    # euro exposures and they are one currency risk.
    merged: dict[str, CurrencyExposure] = {}
    for exposure in exposures:
        held = merged.get(exposure.currency)
        if held is None:
            merged[exposure.currency] = exposure
        else:
            merged[exposure.currency] = CurrencyExposure(
                currency=held.currency,
                region=f"{held.region}, {exposure.region}",
                weight=held.weight + exposure.weight,
                series_id=held.series_id,
                change=held.change,
            )

    result = CurrencyMap(
        ticker=ticker,
        reporting_currency=reporting_currency,
        exposures=sorted(merged.values(), key=lambda e: -e.weight),
        unmapped=unmapped,
    )
    log.info(
        "fx_mapped",
        ticker=ticker,
        currencies=len(result.exposures),
        covered=round(result.covered, 3),
        home_share=round(result.home_share, 3),
        unmapped=unmapped,
    )
    return result


def to_block(fx: CurrencyMap) -> str:
    """For the corpus. Three claims, kept apart on purpose."""
    if not fx.exposures:
        return (
            "CURRENCY: the geographic split could not be mapped to currencies "
            f"({', '.join(fx.unmapped[:4]) or 'no split disclosed'}), so no "
            "currency claim is made. Not zero — unknown."
        )

    lines = [
        f"CURRENCY — {fx.ticker}, reporting in {fx.reporting_currency}. "
        f"{fx.home_share:.0%} of revenue is earned at home, "
        f"{1 - fx.home_share:.0%} abroad.",
        "",
        "  Revenue by currency:",
    ]
    for exposure in fx.exposures:
        move = (
            f"{exposure.change:+.1%}" if exposure.change is not None else "rate unknown"
        )
        lines.append(
            f"    {exposure.currency}  {exposure.weight:>5.0%}  {move}   "
            f"({exposure.region[:40]})"
        )

    translation = fx.translation
    lines += [
        "",
        "  1. TRANSLATION (arithmetic — Mechanical lens): "
        + (
            f"{translation:+.2%} on revenue, revenue-weighted."
            if translation is not None
            else "no rates available, so no translation figure. Not zero."
        ),
        "",
        f"  2. COMPETITIVE POSITION (Market lens): {fx.competitive_note()}",
        "",
        f"  3. DEMAND (Demand lens, weak): {fx.demand_note()}",
    ]
    if fx.unmapped:
        lines += ["", f"  Regions with no currency: {', '.join(fx.unmapped[:5])}"]
    return "\n".join(lines)
