"""E5 — which lines actually decide this company's quarter.

**The question every analyst asks first and this system was answering by
assertion.** Six lenses ran on every company regardless, and the judge weighed
them by a materiality it was told rather than one it measured.

The measurement is available and cheap. Move each driver by ONE STANDARD
DEVIATION of its own quarterly history, one at a time, re-run the projection, and
the EPS attributable to that line falls out. A company whose quarter turns on
gross margin gets Margins run deep and Macro skipped. That is better analysis and
better token allocation at once, and it is a fitted weight rather than an opinion.

**Why one sigma and not a return to the median.** The first version perturbed
each driver to its trailing median, which measures exactly nothing: the model is
SEEDED at that median, so the EPS never moved and every line but revenue growth
scored 0.0%. A swing factor is a line that both MOVES a lot and MATTERS a lot, so
the counterfactual has to be a realistic surprise.

**Why a counterfactual and not a correlation.** Regressing EPS error on each
driver's error across eight quarters would fit noise: eight observations, six
correlated drivers.

That number is directly comparable across lines, which is the property that
makes it a weight. A 100bp gross margin error and a 200bp revenue growth error
are not comparable as percentages and are perfectly comparable as EPS.

**What it deliberately does not do.** It does not rank lenses by how interesting
they are, or by how often they have been right — there is no scored history to
rank on yet. It ranks by how much a line MOVES the answer for this company,
which is a different and more defensible claim: getting an immaterial line right
earns nothing however clever the reasoning.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

# Which model driver each lens is qualified to argue about. The mapping is what
# turns "gross margin decides this quarter" into "run Margins deep".
LENS_FOR_DRIVER: dict[str, tuple[str, ...]] = {
    "revenue_growth": ("drivers", "guidance", "peer_read", "macro"),
    "gross_margin": ("margins", "guidance", "forensics"),
    "opex_pct_revenue": ("margins",),
    "tax_rate": ("margins", "forensics"),
    # Not a lens's to argue: the Mechanical lens computes it from disclosure.
    "diluted_shares": ("mechanical",),
}

DRIVER_LABELS = {
    "revenue_growth": "revenue growth",
    "gross_margin": "gross margin",
    "opex_pct_revenue": "operating expense ratio",
    "tax_rate": "effective tax rate",
    "diluted_shares": "diluted share count",
}

# Below this share of the total swing a line is not worth a lens's tokens. Three
# per cent of the answer is inside the model's own 4.4% reproduction error, so a
# lens arguing about it is arguing beneath the noise floor.
MATERIALITY_FLOOR = 0.03


@dataclass
class Swing:
    """One driver, and what getting it wrong costs in EPS."""

    driver: str
    label: str
    eps_impact: float
    share: float = 0.0
    lenses: tuple[str, ...] = ()

    @property
    def material(self) -> bool:
        return self.share >= MATERIALITY_FLOOR


@dataclass
class SwingFactors:
    ticker: str
    base_eps: float | None = None
    swings: list[Swing] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def top(self, n: int = 3) -> list[Swing]:
        return [s for s in self.swings if s.material][:n]

    def lenses_worth_running(self) -> set[str]:
        """The union of lenses attached to a material driver.

        A lens with no material driver is not dropped for being bad — it is
        dropped for having nothing that moves this company's quarter, which is a
        statement about the company rather than about the lens.
        """
        out: set[str] = set()
        for swing in self.swings:
            if swing.material:
                out.update(swing.lenses)
        return out

    def weights(self) -> dict[str, float]:
        """Materiality per lens, for the judge. Normalised across lenses.

        A lens attached to two material drivers carries both. This is the number
        the judge should weigh by, and it is measured on this company rather
        than asserted in a prompt.
        """
        raw: dict[str, float] = {}
        for swing in self.swings:
            for lens in swing.lenses:
                raw[lens] = raw.get(lens, 0.0) + max(swing.share, 0.0)
        total = sum(raw.values())
        return {k: v / total for k, v in raw.items()} if total else {}


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def measure(
    ticker: str,
    base_eps: float | None,
    perturbed: dict[str, float | None],
) -> SwingFactors:
    """Turn "EPS with this driver held naive" into a ranked set of swings.

    `perturbed[driver]` is the EPS the model produces when that one driver is
    replaced by its trailing median and everything else is left alone. The
    difference from `base_eps` is what a naive assumption on that line costs.
    """
    result = SwingFactors(ticker=ticker, base_eps=base_eps)
    if not _finite(base_eps) or not base_eps:
        result.skipped.append("no base EPS to measure a swing against")
        return result

    swings: list[Swing] = []
    for driver, eps in perturbed.items():
        if not _finite(eps):
            result.skipped.append(f"{driver}: the model did not produce an EPS")
            continue
        swings.append(
            Swing(
                driver=driver,
                label=DRIVER_LABELS.get(driver, driver),
                eps_impact=abs(eps - base_eps),
                lenses=LENS_FOR_DRIVER.get(driver, ()),
            )
        )

    total = sum(s.eps_impact for s in swings)
    for swing in swings:
        swing.share = swing.eps_impact / total if total else 0.0

    result.swings = sorted(swings, key=lambda s: -s.eps_impact)
    log.info(
        "swing_factors",
        ticker=ticker,
        top=[s.driver for s in result.top()],
        immaterial=[s.driver for s in result.swings if not s.material],
    )
    return result


def typical_move(history_values: list[float]) -> float | None:
    """How much this line actually moves, quarter to quarter.

    **Not the distance to its median.** The first version of this perturbed each
    driver to its trailing median and measured the EPS change — which is exactly
    zero, because the model is SEEDED at that median. Every line but revenue
    growth scored 0.0% and the whole ranking collapsed to one driver.

    A swing factor is a line that both MOVES a lot and MATTERS a lot, so the
    counterfactual has to be a realistic surprise rather than a return to the
    average. One standard deviation of the line's own quarterly history is that:
    it is measured on this company, it is in the line's own units, and a line
    that has never moved correctly scores nothing however large it is.

    Standard deviation rather than a fixed percentage because a gross margin
    that has sat between 73% and 75% for three years is not capable of the same
    surprise as one that has swung from 40% to 62%, and treating them alike
    would rank a stable line above a volatile one purely on size.
    """
    usable = [v for v in history_values if _finite(v)]
    if len(usable) < 3:
        return None
    return statistics.pstdev(usable)


def naive_value(history_values: list[float]) -> float | None:
    """The trailing median — what a forecaster with no view would assume.

    Retained for the post-mortem, where the question is "what would doing
    nothing have produced" rather than "how much can this line surprise".
    """
    usable = [v for v in history_values if _finite(v)]
    return statistics.median(usable) if usable else None


def to_block(factors: SwingFactors) -> str:
    """For the judge, and for whoever is deciding where to spend tokens."""
    if not factors.swings:
        return (
            "(swing factors not measured — "
            + "; ".join(factors.skipped or ["no drivers to perturb"])
            + ")"
        )

    lines = [
        f"SWING FACTORS — {factors.ticker}. What each line is worth in EPS if a "
        "naive assumption is made about it, holding everything else at the "
        "model's own base.",
        "",
    ]
    for swing in factors.swings:
        mark = " " if swing.material else "·"
        lines.append(
            f" {mark} {swing.label:26} {swing.eps_impact:>7.3f} EPS "
            f"{swing.share:>6.1%}   {', '.join(swing.lenses) or '—'}"
        )
    immaterial = [s.label for s in factors.swings if not s.material]
    if immaterial:
        lines += [
            "",
            f"Marked · is below {MATERIALITY_FLOOR:.0%} of the total swing, which "
            "is inside the model's own reproduction error — a view on those lines "
            "cannot be resolved by the arithmetic downstream.",
        ]
    if factors.skipped:
        lines += ["", "Not measured:"] + [f"  {s}" for s in factors.skipped]
    return "\n".join(lines)
