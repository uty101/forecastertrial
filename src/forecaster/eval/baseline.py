"""The number to beat.

Not a strawman. 78% of S&P 500 companies beat consensus EPS (5-yr avg), aggregate
surprise +7.0%. `consensus x (1 + tilt)` is a genuinely strong forecaster, every
competent competitor will find it, and it appears on every chart in this repo.

The tilt is per-company and empirical-Bayes shrunk, not the index aggregate.
FactSet's headline "+7%" is CAP-WEIGHTED — Q2 2026's +39.3% collapses to +12.6%
excluding Alphabet alone. Calibrating on it would be a real error.
"""

from __future__ import annotations

from dataclasses import dataclass

from forecaster.eval.shrinkage import ShrunkEstimate, shrink

# 5-yr S&P 500 aggregate surprise, used only when a company has no history.
INDEX_TILT = 0.070


@dataclass
class Baseline:
    eps: float
    tilt: float
    estimate: ShrunkEstimate | None
    rationale: str


def company_tilt(
    ticker: str,
    own_surprises: list[float],
    peer_surprises: dict[str, list[float]],
) -> ShrunkEstimate:
    """Median historical surprise for this name, shrunk toward its peers.

    With n~8 the raw median is mostly sampling noise; shrinkage is what makes it
    usable.
    """
    return shrink(ticker, own_surprises, peer_surprises)


def build(
    consensus_eps: float,
    ticker: str,
    own_surprises: list[float] | None = None,
    peer_surprises: dict[str, list[float]] | None = None,
) -> Baseline:
    if not own_surprises:
        return Baseline(
            eps=consensus_eps * (1 + INDEX_TILT),
            tilt=INDEX_TILT,
            estimate=None,
            rationale=(
                f"no company history; using the 5-yr S&P 500 aggregate tilt "
                f"{INDEX_TILT:+.1%}"
            ),
        )

    est = company_tilt(ticker, own_surprises, peer_surprises or {})
    return Baseline(
        eps=consensus_eps * (1 + est.shrunk),
        tilt=est.shrunk,
        estimate=est,
        rationale=(
            f"{ticker} median surprise {est.raw:+.2%} over {est.n} quarters, "
            f"shrunk {est.weight:.0%} toward a peer median of {est.group:+.2%} "
            f"-> {est.shrunk:+.2%}"
        ),
    )
