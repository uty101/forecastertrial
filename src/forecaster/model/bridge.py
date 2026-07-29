"""The GAAP ↔ non-GAAP bridge — the trap that kills silently.

Consensus estimates are **non-GAAP**, universally. SEC XBRL gives you **GAAP**.
The median gap for DJIA companies was 31% in one recent quarter against a
five-year median of 11.7%, and non-GAAP exceeded GAAP at 83% of DJIA companies
reporting both.

Forecast GAAP, get scored against non-GAAP consensus, and every company misses
by 12–30% in the same direction every quarter. It does not look like a units
bug; it looks like a model that is simply bad, which is why teams spend the
afternoon tuning lenses instead of checking the basis.

So the bridge is an explicit, cited object rather than a constant. Each
reconciling item carries the claim it came from, and the total is checked
against the reported figures on both bases. `Forecast` carries both, which turns
"which actual do they score against?" from a design input into a flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from forecaster.schemas import Basis, Claim

log = structlog.get_logger()

# The bridge should reconcile to within a rounding cent per share. Wider than
# this means an item is missing, not that the arithmetic drifted.
TOLERANCE = 0.01

# Items that keep reappearing are not "unusual", whatever the release calls
# them. Four consecutive quarters of the same "one-off" is a permanent cost the
# company has moved below the line — and the Forensics lens should see it.
RECURRENCE_THRESHOLD = 4


@dataclass(frozen=True)
class BridgeItem:
    """One reconciling item, always with the claim it came from.

    `per_share` is positive when the item is ADDED BACK to GAAP to reach
    non-GAAP — which is the usual direction, because companies exclude costs.
    """

    label: str
    per_share: float
    claim: Claim | None = None
    note: str | None = None
    quarters_recurring: int = 1

    def __post_init__(self) -> None:
        if self.claim is None and self.note is None:
            raise ValueError(
                f"bridge item '{self.label}': needs a Claim, or an explicit note "
                "saying why there isn't one. An unsourced adjustment is exactly "
                "the invented number this system exists to prevent."
            )

    @property
    def is_recurring(self) -> bool:
        return self.quarters_recurring >= RECURRENCE_THRESHOLD


@dataclass
class Bridge:
    """GAAP EPS + reconciling items = non-GAAP EPS."""

    eps_gaap: float
    items: list[BridgeItem] = field(default_factory=list)

    @property
    def total_adjustment(self) -> float:
        return sum(item.per_share for item in self.items)

    @property
    def eps_non_gaap(self) -> float:
        return self.eps_gaap + self.total_adjustment

    @property
    def recurring_adjustment(self) -> float:
        """Adjustments that have recurred long enough to be structural.

        This is the number the Forensics lens cares about: it is the part of the
        gap that is not really "unusual" at all, and a company whose non-GAAP
        premium is mostly recurring items has quietly lowered its own bar.
        """
        return sum(item.per_share for item in self.items if item.is_recurring)

    @property
    def gap_pct(self) -> float:
        """Non-GAAP premium as a fraction of GAAP. The DJIA median was 31%."""
        if self.eps_gaap == 0:
            return 0.0
        return self.total_adjustment / abs(self.eps_gaap)

    def to(self, basis: Basis) -> float:
        return self.eps_gaap if basis is Basis.GAAP else self.eps_non_gaap

    def verify(self, reported_non_gaap: float) -> tuple[bool, str]:
        """Does the bridge actually reconcile to the reported figure?

        This is the check to run by hand on ten companies before trusting any of
        it. A bridge that does not tie means an item is missing, and a missing
        item is a systematic error in one direction — the worst kind.
        """
        implied = self.eps_non_gaap
        gap = abs(implied - reported_non_gaap)
        if gap <= TOLERANCE:
            return True, (
                f"bridge ties: GAAP {self.eps_gaap:.4f} + "
                f"{self.total_adjustment:+.4f} = {implied:.4f} vs reported "
                f"{reported_non_gaap:.4f}"
            )
        return False, (
            f"BRIDGE DOES NOT TIE: GAAP {self.eps_gaap:.4f} + "
            f"{self.total_adjustment:+.4f} = {implied:.4f}, but the company "
            f"reported {reported_non_gaap:.4f} — a gap of {gap:.4f}/share. An "
            "item is missing; do not forecast on this bridge."
        )

    def explain(self) -> list[dict]:
        """Rows for the UI. Every line traceable to its filing."""
        rows = [
            {
                "label": "Diluted EPS (GAAP)",
                "per_share": round(self.eps_gaap, 4),
                "source_uri": None,
                "recurring": False,
            }
        ]
        for item in self.items:
            rows.append(
                {
                    "label": item.label,
                    "per_share": round(item.per_share, 4),
                    "source_uri": item.claim.source.uri if item.claim else None,
                    "quote": item.claim.verbatim_quote if item.claim else None,
                    "note": item.note,
                    "recurring": item.is_recurring,
                    "quarters_recurring": item.quarters_recurring,
                }
            )
        rows.append(
            {
                "label": "Diluted EPS (non-GAAP)",
                "per_share": round(self.eps_non_gaap, 4),
                "source_uri": None,
                "recurring": False,
            }
        )
        return rows


def convert(value: float, from_basis: Basis, to_basis: Basis, bridge: Bridge) -> float:
    """Move a per-share figure between bases using a real bridge.

    There is deliberately no default bridge and no fallback ratio. If you do not
    have the reconciling items for this company, you do not know the gap — and
    assuming the sector median here is how you produce a confident forecast that
    is 31% wrong.
    """
    if from_basis is to_basis:
        return value
    delta = bridge.total_adjustment
    converted = value + delta if to_basis is Basis.NON_GAAP else value - delta
    log.info(
        "basis_converted",
        frm=from_basis.value,
        to=to_basis.value,
        before=round(value, 4),
        after=round(converted, 4),
        adjustment=round(delta, 4),
    )
    return converted
