"""How often this company reports, and what that changes.

Every number in the model was quarterly by assumption. `BACKTEST_QUARTERS = 4`,
`MIN_PRIOR_QUARTERS = 4`, trailing windows of four, annualisation by ×4 — all of
it correct for a US filer and wrong for most of the world. Nestlé reports twice a
year. Toyota reports quarterly but on a March year-end. A UK smaller company may
report only annually.

The failure this produces is not a crash, which is the problem. A half-yearly
filer with four annual data points and one interim has, on the quarterly
assumption, "not enough prior quarters" — so the ratio base never forms, every
lens abstains for want of anything to argue with, and the run dies at V1 looking
like a model failure rather than a units mismatch.

**What this module is.** One inference — the reporting cadence — and the handful
of constants that follow from it. Everything downstream asks this instead of
assuming:

    periods per year     4, 2 or 1, read from the observed period ends
    seasonal cycle       how many periods make a full year of seasonality
    annualisation        what a single period must be multiplied by
    minimum history      how many prior periods before a ratio means anything

**Inferred, never configured.** A cadence field on a company profile is a thing
somebody has to have filled in, and on the day the ticker is unknown. The spacing
between period ends is a fact already in the data.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import Literal

import structlog

log = structlog.get_logger()

Frequency = Literal["quarterly", "half-yearly", "annual"]

# Median days between period ends, and what that means. Wide bands because a
# fiscal calendar is not a metronome — 13-week quarters, 52/53-week years and a
# February year-end all move the spacing by days.
BANDS: tuple[tuple[float, Frequency], ...] = (
    (135.0, "quarterly"),
    (270.0, "half-yearly"),
    (10_000.0, "annual"),
)

# Below this many observations the spacing is not evidence of a cadence, it is
# two dates and a gap. Default to quarterly: it is what most of the tested
# universe does, and a wrong guess in that direction merely makes the minimum
# history requirement stricter than it needs to be.
MIN_OBSERVATIONS = 3


@dataclass(frozen=True)
class Cadence:
    """The reporting rhythm, and every constant that depends on it."""

    frequency: Frequency
    periods_per_year: int
    observed_gap_days: float
    n_periods: int
    inferred_from: str

    @property
    def seasonal_cycle(self) -> int:
        """Periods in a full year of seasonality.

        The backtest window: a model that reproduces three quarters and misses
        December has a seasonality problem, and a window shorter than the cycle
        hides it. For an annual filer the cycle is 1 and there is no seasonality
        to miss — which is a real difference, not a degenerate case.
        """
        return self.periods_per_year

    @property
    def min_prior_periods(self) -> int:
        """Prior periods needed before a ratio is a ratio and not a datapoint.

        A full cycle for a quarterly filer. For a half-yearly one, a full cycle
        is two periods and that is genuinely too thin to take a median over, so
        it asks for two cycles — the constraint is "enough observations", and
        the cycle length only tells you how they are spaced.
        """
        return max(self.periods_per_year, 3)

    @property
    def annualise(self) -> int:
        """Multiplier taking one period's flow to a year. Never applied to a
        stock: a balance is a balance whatever the reporting frequency."""
        return self.periods_per_year

    @property
    def label(self) -> str:
        return {
            "quarterly": "quarterly (4 periods/year)",
            "half-yearly": "half-yearly (2 periods/year)",
            "annual": "annual (1 period/year)",
        }[self.frequency]

    def describe(self) -> str:
        return (
            f"{self.label} — inferred from {self.n_periods} observed period ends "
            f"a median {self.observed_gap_days:.0f} days apart ({self.inferred_from}). "
            f"Ratio windows use {self.min_prior_periods} periods; a flow is "
            f"annualised x{self.annualise}."
        )


QUARTERLY = Cadence(
    frequency="quarterly",
    periods_per_year=4,
    observed_gap_days=91.0,
    n_periods=0,
    inferred_from="assumed — too few period ends to measure",
)


def infer(period_ends: list[date]) -> Cadence:
    """Read the cadence off the spacing between period ends.

    Median spacing rather than mean: one restated stub period, or a gap where a
    filing is missing, would drag a mean across a band boundary and silently
    reclassify a quarterly filer as half-yearly. The same robust-statistics rule
    the rest of the system runs on.
    """
    unique = sorted(set(period_ends))
    if len(unique) < MIN_OBSERVATIONS:
        return Cadence(
            frequency=QUARTERLY.frequency,
            periods_per_year=QUARTERLY.periods_per_year,
            observed_gap_days=QUARTERLY.observed_gap_days,
            n_periods=len(unique),
            inferred_from=(
                f"assumed quarterly — {len(unique)} period end(s) is not a spacing"
            ),
        )

    gaps = [
        (later - earlier).days
        for earlier, later in zip(unique, unique[1:], strict=False)
    ]
    median_gap = statistics.median(gaps)
    frequency = next(freq for limit, freq in BANDS if median_gap < limit)
    per_year = {"quarterly": 4, "half-yearly": 2, "annual": 1}[frequency]

    cadence = Cadence(
        frequency=frequency,
        periods_per_year=per_year,
        observed_gap_days=median_gap,
        n_periods=len(unique),
        inferred_from=f"median of {len(gaps)} gaps between period ends",
    )
    log.info(
        "cadence_inferred",
        frequency=frequency,
        median_gap_days=median_gap,
        periods=len(unique),
    )
    return cadence


def reported_items(series: dict[str, list], min_periods: int = 2) -> set[str]:
    """Line items this company actually reports, as opposed to all 62.

    The statement grid was the union of everything a US filer discloses, so a
    company that genuinely does not break out research and development showed a
    blank row indistinguishable from one where the extraction failed. Those are
    different facts and a reader is entitled to tell them apart: an absent row
    means "not disclosed", a blank row in a present one means "we could not find
    it".

    `min_periods` because a single stray observation is a tagging accident, not
    a disclosure policy.
    """
    return {
        key for key, rows in series.items() if len(rows) >= min_periods
    }
