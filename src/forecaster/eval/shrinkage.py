"""Empirical-Bayes shrinkage. Two lines of maths, materially better estimates.

Every per-company statistic in this system has about eight observations — the
median surprise, where a company lands inside its own guided range. At n=8 the
raw statistic is mostly noise, and using it directly means chasing sampling
error rather than signal.

James-Stein: shrink each company's own estimate toward the group mean, weighted
by how noisy that company's history is relative to the spread between companies.

    w = tau^2 / (tau^2 + sigma_i^2 / n_i)
    shrunk_i = w * own_i + (1 - w) * group

where tau^2 is the between-company variance and sigma_i^2 the within-company
variance. A company with a long, consistent record keeps its own number; one
with three erratic quarters gets pulled to the sector.

Robust estimators throughout. One Alphabet-style outlier destroys mean-based
statistics — FactSet's own headline surprise fell from +39.3% to +12.6% on
excluding a single company.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

WINSOR_LO, WINSOR_HI = 0.05, 0.95

# Below this many usable peers, the between-company spread estimate is noise.
MIN_PEERS = 5

# Fallback shrinkage strength when the peer set tells us nothing: a company
# needs this many quarters of its own history to earn half its own estimate.
PRIOR_STRENGTH = 8


def winsorize(values: list[float], lo: float = WINSOR_LO, hi: float = WINSOR_HI):
    """Clip tails before any mean-based statistic. Never calibrate on raw means.

    Indexing note, learned the hard way: `int(hi * n)` is wrong — for n=20 and
    hi=0.95 it gives index 19, which IS the maximum, so nothing is ever clipped
    and the function silently does nothing. The correct index for a percentile
    is `p * (n - 1)` (standard lower-interpolation), which for n=20 gives 18 and
    actually excludes the top observation.

    This mattered: the whole reason winsorization is here is the single
    Alphabet-style print that moved FactSet's headline surprise from +39.3% to
    +12.6%. A no-op would have left that outlier setting the calibration.
    """
    if len(values) < 3:
        return list(values)
    ordered = sorted(values)
    n = len(ordered)
    low = ordered[int(lo * (n - 1))]
    high = ordered[int(hi * (n - 1))]
    return [min(max(v, low), high) for v in values]


def mad(values: list[float]) -> float:
    """Median absolute deviation, scaled to be comparable with a stdev."""
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    return 1.4826 * statistics.median([abs(v - med) for v in values])


@dataclass
class ShrunkEstimate:
    ticker: str
    raw: float
    shrunk: float
    weight: float
    n: int
    group: float

    @property
    def moved(self) -> float:
        return self.shrunk - self.raw


def shrink(
    ticker: str, own: list[float], group_values: dict[str, list[float]]
) -> ShrunkEstimate:
    """Shrink one company's statistic toward the peer group.

    `own` is this company's observations (e.g. eight quarterly surprises).
    `group_values` maps every peer ticker to its own observations.
    """
    if not own:
        flat = [v for vals in group_values.values() for v in vals]
        grp = statistics.median(flat) if flat else 0.0
        return ShrunkEstimate(ticker, grp, grp, 0.0, 0, grp)

    raw = statistics.median(own)

    per_company = [
        statistics.median(vals) for vals in group_values.values() if len(vals) >= 2
    ]
    group = statistics.median(per_company) if per_company else raw

    # between-company variance
    tau2 = mad(per_company) ** 2 if len(per_company) >= MIN_PEERS else 0.0
    # within-company variance of the mean
    sigma2 = (mad(own) ** 2) / len(own) if len(own) >= 2 else None

    if tau2 > 0 and sigma2 is not None:
        weight = tau2 / (tau2 + sigma2)
    else:
        # Degenerate peer set: too few peers, or their medians happen to be
        # identical so MAD is 0. This is NOT evidence that every company is the
        # same — it is an absence of evidence about between-company spread.
        #
        # Setting weight=0 here was a real bug: a company with eight consistent
        # quarters got thrown away entirely because five synthetic peers shared
        # a median. Fall back to sample-size shrinkage instead, so a long own
        # record still counts for something.
        weight = len(own) / (len(own) + PRIOR_STRENGTH)

    return ShrunkEstimate(
        ticker=ticker,
        raw=raw,
        shrunk=weight * raw + (1 - weight) * group,
        weight=weight,
        n=len(own),
        group=group,
    )


def guide_landing_positions(
    guides: list[tuple[float, float]], actuals: list[float]
) -> list[float]:
    """Where a company landed inside its own guided range, per quarter.

    0 = the low end, 1 = the high end, >1 = beat the range entirely.

    Everyone reads the guidance. Almost nobody builds this distribution, and it
    is directly computable: some companies hit the midpoint like clockwork,
    others habitually clear the top end.
    """
    positions = []
    for (low, high), actual in zip(guides, actuals, strict=True):
        span = high - low
        positions.append(0.5 if span == 0 else (actual - low) / span)
    return positions
