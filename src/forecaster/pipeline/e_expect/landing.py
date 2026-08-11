"""E2 — where this company lands inside its own guided range.

**Everyone reads the guidance. Almost nobody builds this**, and it is the single
piece of evidence that turns guidance from an anchor into a signal.

A company guides $89.2bn to $92.8bn. Consensus lands on the midpoint, because
the midpoint is what you print when you have no view about the range. But
companies are not uniform inside their own guidance: some hit the midpoint like
clockwork, some habitually clear the top, and a few guide a range they have not
touched the upper half of in three years. That behaviour is *persistent* — it is
a property of how a management team sets expectations, not of the quarter — and
it is measurable from filings we already hold.

Position is expressed in [0, 1] against the guided range:

    0.0   landed exactly at the low end
    0.5   the midpoint, which is what consensus assumes by default
    1.0   the high end
    >1.0  beat the range entirely

**Why the median and not the mean.** Eight observations, and one quarter with a
one-off charge would drag a mean off a persistent pattern. Same robust-statistics
rule as everywhere else here.

**Why it is then shrunk.** With n ≈ 8 the raw statistic is mostly noise: a
company that landed at 0.9 twice looks like a habitual top-end lander on two
data points. Empirical-Bayes shrinkage toward the sector prior pulls a thin
sample back toward the population and leaves a long sample alone, which is
exactly the property wanted — the shrunk figure is the one to use, and the raw
one is kept only so a reader can see how much work the shrinkage did.

Not built and asserted. If a company has fewer than `MIN_QUARTERS` usable pairs
this returns None rather than a number, because a landing distribution from two
quarters is an anecdote with a decimal point.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import structlog

from forecaster.schemas import Guidance, LandingDistribution

log = structlog.get_logger()

# Below this a "distribution" is an anecdote. Four quarters is a full seasonal
# cycle and the least that can show a pattern rather than a coincidence.
MIN_QUARTERS = 4

# The prior. Absent a sector-specific one, the midpoint: it is what a company
# with no persistent behaviour would do, and it is what consensus already
# assumes — so shrinking toward it means a thin sample makes no claim.
DEFAULT_PRIOR = 0.5

# Empirical-Bayes weight. `n / (n + K)` on the observed median: at n=4 the
# sample carries 40% and at n=16 it carries 73%. K=6 is chosen so that eight
# quarters — the most any company gives you in two years — is worth more than
# the prior but not overwhelmingly so.
SHRINK_K = 6.0


@dataclass(frozen=True)
class Landed:
    """One quarter: what was guided, what was reported, where it landed."""

    period: str
    metric: str
    low: float
    high: float
    actual: float

    @property
    def position(self) -> float | None:
        """Where in the range the actual fell. None if the range is degenerate.

        A zero-width range is a point guide, not a range, and dividing by it
        produces an infinity that then propagates through the median as a
        perfectly ordinary-looking number.
        """
        span = self.high - self.low
        if span <= 0:
            return None
        return (self.actual - self.low) / span


def positions(landed: list[Landed]) -> list[float]:
    return [p for row in landed if (p := row.position) is not None]


def shrink(observed: float, n: int, prior: float = DEFAULT_PRIOR) -> float:
    """Pull the observed median toward the prior in proportion to sample size.

    The whole point of the stage. A company that landed at 0.9 twice is not a
    habitual top-end lander; it is a company with two observations. This says so
    arithmetically instead of leaving a lens to guess how much to trust n.
    """
    weight = n / (n + SHRINK_K)
    return weight * observed + (1 - weight) * prior


def build(
    ticker: str, landed: list[Landed], prior: float = DEFAULT_PRIOR
) -> LandingDistribution | None:
    """The distribution, or None when there is not enough of it to be one."""
    found = positions(landed)
    if len(found) < MIN_QUARTERS:
        log.info(
            "landing_too_thin", ticker=ticker, quarters=len(found),
            needed=MIN_QUARTERS,
        )
        return None

    median = statistics.median(found)
    result = LandingDistribution(
        ticker=ticker,
        n_quarters=len(found),
        positions=found,
        median_position=median,
        shrunk_position=shrink(median, len(found), prior),
    )
    log.info(
        "landing_built", ticker=ticker, quarters=len(found),
        median=round(median, 3), shrunk=round(result.shrunk_position, 3),
    )
    return result


def pair(
    guides: list[Guidance], actuals: dict[str, float], metric: str = "revenue"
) -> list[Landed]:
    """Match each historic guide to what the company actually reported.

    `actuals` is keyed by the period the guide was FOR, which is the join that
    matters and the one that is easy to get wrong: a guide issued in Q1 is a
    guide about Q2, and pairing it with Q1's own result would measure nothing
    except that the company can read its own income statement.
    """
    out: list[Landed] = []
    for guide in guides:
        if guide.metric != metric or guide.low is None or guide.high is None:
            continue
        actual = actuals.get(guide.period)
        if actual is None:
            continue
        out.append(
            Landed(
                period=guide.period,
                metric=metric,
                low=guide.low,
                high=guide.high,
                actual=actual,
            )
        )
    return out


def to_block(distribution: LandingDistribution | None) -> str:
    """For the Guidance lens, which is the whole reason this exists.

    States the shrunk figure as the one to use and shows the raw beside it, so
    the lens can see how thin the sample is rather than being handed a number
    with no error bars.
    """
    if distribution is None:
        return (
            "(no landing distribution — fewer than four quarters of guidance "
            "could be paired with what was actually reported. Treat the guided "
            "midpoint as the anchor and say that is what you are doing.)"
        )

    where = distribution.shrunk_position
    if where > 0.62:
        character = "habitually lands in the UPPER half of its own range"
    elif where < 0.38:
        character = "habitually lands in the LOWER half of its own range"
    else:
        character = "lands near the midpoint of its own range"

    return (
        f"LANDING DISTRIBUTION — {distribution.ticker}, "
        f"{distribution.n_quarters} quarters.\n"
        f"  This company {character}.\n"
        f"  Shrunk position {where:.2f} (0 = low end, 0.5 = midpoint, 1 = high "
        f"end). Raw median {distribution.median_position:.2f}.\n"
        f"  Observed: "
        + ", ".join(f"{p:.2f}" for p in distribution.positions)
        + "\n"
        "  Use the SHRUNK figure. The raw median on this few quarters is mostly "
        "noise, and consensus has already assumed the midpoint — so the only "
        "part of this worth acting on is the distance from 0.50."
    )
