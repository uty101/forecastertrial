"""E6 — what the internet thinks, and why it must never touch the model.

**This is the one input in the system that is deliberately kept away from the
three-statement model, and the reason is worth stating precisely.**

Sentiment is not evidence about what will happen. It is evidence about what is
already believed — and what is already believed is, by definition, already in the
price. Feeding it into `revenue_growth` would be a category error twice over:
once because a forecast built partly on optimism is not a forecast, and once
because it would double-count, since the optimism is why the multiple is what it
is.

So perception lands in exactly two places:

    lambda      crowded positioning shrinks conviction. A good quarter into a
                consensus long is a bad outcome, and that is a POSITION-SIZING
                fact, not a forecasting one.

    the judge   as context for interpreting agreement. Seven lenses agreeing
                with a narrative the whole internet already holds is weaker
                evidence than seven lenses agreeing against it.

**Why it is worth having at all.** The thesis of the project is that consensus
is beatable where it is structurally weak. Perception is the most direct
measurement of what consensus currently is — not the printed EPS estimate, but
the story underneath it, which is what actually breaks when a quarter surprises.
A reverse DCF says the price requires 29% growth; perception says whether anyone
believes that is hard.

**The trap it is built to avoid.** Article counts and word polarity produce a
number that looks quantitative and measures publication volume. Coverage spikes
before every print regardless of direction. So this scores DISPERSION and
DIRECTION separately and treats a unanimous narrative as a warning rather than
as a confirmation: the most dangerous setup is not bad news, it is everybody
agreeing.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import structlog

log = structlog.get_logger()

Stance = Literal["bullish", "neutral", "bearish"]
Subject = Literal["company", "industry"]

# Below this there is no distribution to speak of, only anecdote.
MIN_ITEMS = 4

# A narrative this one-sided is crowded. Not a signal about direction — a signal
# that the direction is already priced, which shrinks how far it is worth
# deviating rather than telling you which way to deviate.
CROWDED = 0.70


@dataclass(frozen=True)
class Read:
    """One article, scored. The quote is what makes it auditable."""

    subject: Subject
    stance: Stance
    conviction: float
    claim: str
    quote: str
    url: str
    published: date

    @property
    def signed(self) -> float:
        return {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}[
            self.stance
        ] * self.conviction


@dataclass
class Perception:
    ticker: str
    reads: list[Read] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def _subset(self, subject: Subject | None) -> list[Read]:
        return [r for r in self.reads if subject is None or r.subject == subject]

    def tilt(self, subject: Subject | None = None) -> float | None:
        """Median signed stance. Median because one hyperbolic piece should not
        set the reading, same rule as everywhere else here."""
        scores = [r.signed for r in self._subset(subject)]
        if len(scores) < MIN_ITEMS:
            return None
        return statistics.median(scores)

    def dispersion(self, subject: Subject | None = None) -> float | None:
        """How much the coverage disagrees with itself.

        The more useful half of the reading. Wide dispersion means the story is
        contested and a surprise has somewhere to go; narrow dispersion means
        everyone has already decided, which is when a forecast that agrees with
        them earns nothing and one that disagrees is expensive to hold.
        """
        scores = [r.signed for r in self._subset(subject)]
        if len(scores) < MIN_ITEMS:
            return None
        return statistics.pstdev(scores)

    def crowded(self, subject: Subject | None = None) -> bool:
        """One-sided enough that the view is already in the price."""
        subset = self._subset(subject)
        if len(subset) < MIN_ITEMS:
            return False
        bullish = sum(1 for r in subset if r.stance == "bullish") / len(subset)
        bearish = sum(1 for r in subset if r.stance == "bearish") / len(subset)
        return max(bullish, bearish) >= CROWDED

    def lambda_multiplier(self) -> tuple[float, str]:
        """What this does to conviction, and why. NEVER to the estimate.

        A crowded narrative does not tell you the estimate is wrong. It tells you
        that being right earns less and being wrong costs more, which is a
        position-sizing fact — so it moves λ and nothing else.
        """
        if self.crowded("company"):
            return (
                0.85,
                "the coverage is one-sided, so this view is largely priced — "
                "conviction shrinks even where the estimate does not move",
            )
        spread = self.dispersion("company")
        if spread is not None and spread > 0.55:
            return (
                1.05,
                "the coverage disagrees with itself, so a surprise has somewhere "
                "to go and a differentiated estimate is worth more",
            )
        return 1.0, "coverage is neither crowded nor especially contested"


def to_block(result: Perception) -> str:
    """For the judge. Framed as context for weighing agreement, not as evidence.

    The wording matters: a lens told "sentiment is bullish" will drift toward
    bullish. A judge told "the narrative is unanimous, so agreement with it is
    weak evidence" does something useful with the same fact.
    """
    if len(result.reads) < MIN_ITEMS:
        return (
            "(no usable perception reading — fewer than four dated, scored items. "
            "Coverage volume is not a signal and none is claimed.)"
        )

    lines = [
        f"PERCEPTION — {result.ticker}, {len(result.reads)} scored items. "
        "This is evidence about what is ALREADY BELIEVED, not about what will "
        "happen. It moves conviction, never the estimate.",
        "",
    ]

    for subject in ("company", "industry"):
        subset = result._subset(subject)  # type: ignore[arg-type]
        if len(subset) < MIN_ITEMS:
            continue
        tilt = result.tilt(subject)  # type: ignore[arg-type]
        spread = result.dispersion(subject)  # type: ignore[arg-type]
        crowded = result.crowded(subject)  # type: ignore[arg-type]
        lines.append(
            f"  {subject:9} n={len(subset):<3} tilt {tilt:+.2f}   "
            f"dispersion {spread:.2f}   "
            + ("CROWDED — already priced" if crowded else "contested")
        )

    multiplier, why = result.lambda_multiplier()
    lines += [
        "",
        f"  Effect on lambda: x{multiplier:.2f} — {why}.",
        "",
        "  Read it this way: lenses agreeing with a narrative the whole internet "
        "already holds is WEAKER evidence than lenses agreeing against it. The "
        "dangerous setup is not bad news, it is everybody agreeing.",
    ]
    if result.skipped:
        lines += ["", "  Not scored:"] + [f"    {s}" for s in result.skipped[:4]]
    return "\n".join(lines)
