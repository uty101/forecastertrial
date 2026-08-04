"""Turning what the ensemble believes into what the model runs on.

Stage D hands the lenses a model. This is the return leg: the drivers the lenses
argued about, folded into the projection so their view becomes a forecast column
rather than a number sitting next to one.

**Why the ensemble and not the judge.** The judge produces one EPS and a
distribution — the right output for the forecast and the wrong input for a
model, because an EPS cannot be decomposed back into a margin and a growth rate.
The drivers have to come from the lenses that argued about them. What the judge
decides is how far to move off consensus; what the model needs is the shape of
the view underneath, and those are different questions answered at different
stages.

**Median, never mean, and never a vote.** Three lenses offering a gross margin
are three independent readings of the same quantity, and the median is the
robust summary — one lens misreading a segment table by a factor of ten moves a
mean and does not move a median. Note what this is NOT: it is not the ensemble
combining into a forecast. That happens at the judge, weighted by materiality.
This is only the arithmetic of "what do the lenses that spoke to gross margin
think gross margin is".

**A driver nobody argued about stays held.** Silence is not agreement with the
historical ratio — it is silence, and the distinction has to survive onto the
sheet or a model with one forecast driver and fifteen extrapolated ones reads as
a fully-formed view.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import replace
from typing import Any

import structlog

from forecaster.model.project import Driver, YearDrivers
from forecaster.schemas import LensOutput

log = structlog.get_logger()

# Which lens fields map onto which driver, and the sane range for each. A lens
# returning 60 for a gross margin means 60%, and taking it literally produces a
# company with 6000% margins that balances perfectly — the arithmetic stays
# consistent, which is exactly why this has to be caught by range and not by
# looking at the output.
DRIVER_BOUNDS: dict[str, tuple[float, float]] = {
    "revenue_growth": (-0.90, 3.00),
    "gross_margin": (0.0, 0.99),
    "opex_pct_revenue": (0.0, 0.95),
    "tax_rate": (0.0, 0.60),
}


def _usable(value: float | None, field: str) -> bool:
    if value is None or not math.isfinite(value):
        return False
    low, high = DRIVER_BOUNDS[field]
    return low <= value <= high


def _consensus_of(
    lenses: list[LensOutput], field: str
) -> tuple[float | None, list[str], list[str]]:
    """The median view on one driver, plus who spoke and who was rejected."""
    spoke: list[str] = []
    rejected: list[str] = []
    values: list[float] = []

    for lens in lenses:
        value = getattr(lens, field, None)
        if value is None:
            continue
        if not _usable(value, field):
            low, high = DRIVER_BOUNDS[field]
            rejected.append(
                f"{lens.lens.value} gave {field}={value:g}, outside [{low:g}, {high:g}]"
            )
            continue
        spoke.append(lens.lens.value)
        values.append(float(value))

    return (statistics.median(values) if values else None), spoke, rejected


def apply(
    seeded: list[YearDrivers],
    lenses: list[LensOutput],
    apply_to_all_years: bool = False,
) -> tuple[list[YearDrivers], dict[str, Any]]:
    """Overwrite the seeded drivers with the ensemble's view. Returns (drivers, report).

    By default only the FIRST forecast year is touched, and that restraint is the
    point: the lenses were asked about one quarter's worth of business, not about
    2035. Pushing a one-quarter view ten years out would turn a near-term call
    into a decade-long assertion nobody made, which is the same error as holding
    trailing growth flat — just wearing a lens's name.

    Nothing else about the projection changes. The articulation is untouched, so
    the balance sheet still ties for exactly the reasons it tied before.
    """
    if not seeded:
        return seeded, {"applied": {}, "rejected": [], "silent": []}

    applied: dict[str, dict[str, Any]] = {}
    rejected: list[str] = []
    silent: list[str] = []

    for field in DRIVER_BOUNDS:
        value, spoke, bad = _consensus_of(lenses, field)
        rejected.extend(bad)
        if value is None:
            silent.append(field)
            continue
        applied[field] = {"value": value, "lenses": spoke}

    targets = seeded if apply_to_all_years else seeded[:1]
    updated = list(seeded)
    for index, year in enumerate(targets):
        changes = {}
        for field, entry in applied.items():
            changes[field] = Driver(
                entry["value"],
                "forecast",
                f"median of {len(entry['lenses'])} lens view(s): "
                + ", ".join(entry["lenses"]),
            )
        updated[index] = replace(year, **changes)

    report = {
        "applied": applied,
        # Kept as prominently as what was applied. A high rejection rate means a
        # prompt is producing percentages where it was asked for fractions, which
        # is worth knowing before the forecast rests on it.
        "rejected": rejected,
        # Not agreement with the historical ratio — silence. A model with one
        # forecast driver and fifteen extrapolated ones must not read as a
        # fully-formed view.
        "silent": silent,
        "years_touched": len(targets),
    }
    log.info(
        "drivers_from_lenses",
        applied=sorted(applied), rejected=len(rejected), silent=silent,
    )
    return updated, report
