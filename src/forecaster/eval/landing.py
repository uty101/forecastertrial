"""Where a company lands inside its own guided range.

Everyone reads the guidance. Almost nobody builds this, and it is directly
computable from filings that have been public for years: for each past quarter,
take the range the company guided and the number it actually printed, and
express the outcome as a position in [0, 1] — 0 the low end, 1 the high end,
above 1 a beat of the whole range.

Some companies hit the midpoint like clockwork. Some clear the top end every
time. That is a per-company behavioural fact, and it is the difference between
"management guided $2.10–2.20" and a forecast.

**With n≈8 the raw statistic is mostly sampling noise**, which is the reason
this module ends in a shrinkage call rather than a median. Using the raw number
means chasing sampling error; James-Stein shrinkage toward the peer group turns
eight observations into something usable, and the shrunk figure is the one the
prompt tells the model to weight.
"""

from __future__ import annotations

import statistics

import structlog

from forecaster.eval.shrinkage import guide_landing_positions, shrink
from forecaster.schemas import LandingDistribution

log = structlog.get_logger()

# A company with fewer than this many guided quarters has no usable pattern —
# return the peer position rather than a statistic built on three points.
MIN_QUARTERS = 4


def build(
    ticker: str,
    guides: list[tuple[float, float]],
    actuals: list[float],
    peers: dict[str, list[float]] | None = None,
) -> LandingDistribution | None:
    """Build the distribution for one company.

    `guides` is (low, high) per quarter, oldest first; `actuals` is what printed.
    `peers` maps peer tickers to their own position lists — the group the raw
    statistic is shrunk toward.

    Returns None when there is not enough history, rather than a distribution
    built on two quarters. An honest absence lets the Guidance lens fall back to
    the midpoint; a fake distribution sends it confidently to the wrong end of
    the range.
    """
    if len(guides) != len(actuals):
        raise ValueError(
            f"{ticker}: {len(guides)} guided ranges but {len(actuals)} actuals — "
            "these must be aligned quarter for quarter"
        )
    if len(guides) < MIN_QUARTERS:
        log.info("landing_skipped", ticker=ticker, n=len(guides), need=MIN_QUARTERS)
        return None

    positions = guide_landing_positions(guides, actuals)
    estimate = shrink(ticker, positions, peers or {})

    log.info(
        "landing_built",
        ticker=ticker,
        n=len(positions),
        raw=round(estimate.raw, 3),
        shrunk=round(estimate.shrunk, 3),
        weight=round(estimate.weight, 3),
        moved=round(estimate.moved, 3),
    )
    return LandingDistribution(
        ticker=ticker,
        n_quarters=len(positions),
        positions=positions,
        median_position=estimate.raw,
        shrunk_position=estimate.shrunk,
    )


def implied_eps(
    landing: LandingDistribution | None, low: float, high: float
) -> float | None:
    """Turn a guided range plus a landing position into an EPS.

    The arithmetic the Guidance lens is doing in prose, available here as a
    deterministic cross-check — if the model's number and this one disagree
    materially, the model has done something other than what it said.
    """
    if landing is None:
        return None
    span = high - low
    if span <= 0:
        return low
    return low + landing.shrunk_position * span


def summarise(distributions: list[LandingDistribution]) -> dict:
    """Cross-company view for the eval screen.

    The interesting number is how far shrinkage MOVED each company. A large
    average move means the raw per-company statistics were noise, which is the
    empirical justification for the whole shrinkage step rather than an
    assertion about it.
    """
    if not distributions:
        return {"n_companies": 0}

    moves = [abs(d.shrunk_position - d.median_position) for d in distributions]
    return {
        "n_companies": len(distributions),
        "median_shrunk_position": round(
            statistics.median(d.shrunk_position for d in distributions), 3
        ),
        "mean_absolute_shrinkage_move": round(statistics.fmean(moves), 3),
        "companies_landing_above_the_top_end": sum(
            d.shrunk_position > 1.0 for d in distributions
        ),
        "companies_landing_below_the_midpoint": sum(
            d.shrunk_position < 0.5 for d in distributions
        ),
    }
