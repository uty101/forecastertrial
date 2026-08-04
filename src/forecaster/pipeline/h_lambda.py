"""Lambda — positioning against the Street. The thesis, in code.

Everything upstream of here produces an estimate. This decides how much to trust
that estimate against sixty-one analysts with segment-level models.

    forecast = consensus + lambda * (own_estimate - consensus)

Lambda is FITTED, not guessed. Regress actual on (consensus, own) across your
backtest and read the coefficient off; expect it small. Then condition it on
regime, because consensus is much weaker on some names than others.

Three presets, one per metric family, all backtested during prep. On the day you
pick one from the decision card in about sixty seconds — the scoring rule stops
being a design input and becomes a config value.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from forecaster.schemas import (
    Consensus,
    LambdaDecision,
    LambdaPreset,
    LensOutput,
)

# Fitted on backtest during prep — these are placeholders until Block 1 runs.
# The whole point is that these are measured numbers, not intuitions.
FITTED_BETA: dict[LambdaPreset, float] = {
    LambdaPreset.SHRINK: 0.20,
    LambdaPreset.BARBELL: 0.55,
    LambdaPreset.CALIBRATED: 0.30,
}

# Flip to True in the same commit that replaces the numbers above with the output
# of `forecast fit`. Nothing reads λ differently either way — this exists so the
# distinction between an asserted coefficient and a measured one is a fact in the
# code rather than a comment, and so the system sheet can report it honestly
# instead of implying the thesis has been demonstrated when it has not.
FITTED_BETA_MEASURED = False

# Regime multipliers. Consensus is weak when coverage is thin, dispersion wide,
# or estimates stale — those are the only places worth spending deviation.
THIN_COVERAGE_MULT = 1.8
WIDE_DISPERSION_MULT = 1.4
STALE_CONSENSUS_MULT = 1.3
HEAVY_COVERAGE_MULT = 0.4  # 40+ analysts: shrink hard, and say so on stage

# When our own lenses disagree this much (coefficient of variation), our evidence
# is weak regardless of what the meta-layer says about consensus.
DISAGREEMENT_CEILING = 0.25

# The minimum meaningful deviation under a pure win-rate metric, where matching
# consensus scores exactly zero and magnitude is irrelevant.
TINY_TILT = 0.005


@dataclass
class LambdaInputs:
    consensus: Consensus
    lenses: list[LensOutput]
    own_estimate: float
    comparability_flag: str | None = None
    tiny_tilt: bool = False


def internal_disagreement(lenses: list[LensOutput]) -> float:
    """Coefficient of variation across lens EPS estimates.

    Doubles as a confidence signal: high inter-lens spread means shrink, and
    high inter-*run* spread (k=5) means the same thing. A single run of a model
    is a coin flip wearing a suit.
    """
    values = [lens.eps for lens in lenses if lens.eps is not None]
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0
    return statistics.stdev(values) / abs(mean)


def decide(preset: LambdaPreset, inputs: LambdaInputs) -> LambdaDecision:
    consensus = inputs.consensus
    base = FITTED_BETA[preset]
    reasons: list[str] = [f"preset={preset.value}, fitted base beta={base:.2f}"]

    lam = base

    # --- regime conditioning ------------------------------------------------
    if consensus.is_thin:
        lam *= THIN_COVERAGE_MULT
        reasons.append(
            f"thin coverage ({consensus.n_analysts} analysts) — consensus is nearly "
            f"a single opinion, x{THIN_COVERAGE_MULT}"
        )
    elif consensus.n_analysts is not None and consensus.n_analysts >= 40:
        lam *= HEAVY_COVERAGE_MULT
        reasons.append(
            f"heavy coverage ({consensus.n_analysts} analysts with segment-level "
            f"models) — shrinking to the Street is the skilful answer, "
            f"x{HEAVY_COVERAGE_MULT}"
        )

    dispersion = consensus.dispersion
    if dispersion is not None and dispersion > 0.15:
        lam *= WIDE_DISPERSION_MULT
        reasons.append(f"wide dispersion ({dispersion:.1%}), x{WIDE_DISPERSION_MULT}")

    if consensus.is_stale:
        lam *= STALE_CONSENSUS_MULT
        reasons.append(
            f"stale consensus ({consensus.days_since_last_revision}d since last "
            f"revision), x{STALE_CONSENSUS_MULT}"
        )

    # --- our own uncertainty ------------------------------------------------
    disagreement = internal_disagreement(inputs.lenses)
    if disagreement > DISAGREEMENT_CEILING:
        damp = DISAGREEMENT_CEILING / disagreement
        lam *= damp
        reasons.append(
            f"lenses disagree ({disagreement:.1%} CV) — our evidence is weak, x{damp:.2f}"
        )

    # --- comparability ------------------------------------------------------
    # When the quarter isn't comparable, historical priors do not apply and the
    # system should be *least* confident exactly where it would otherwise be most.
    if inputs.comparability_flag:
        lam *= 0.25
        reasons.append(
            f"comparability flag ({inputs.comparability_flag}) — historical priors "
            "do not apply, x0.25"
        )

    # --- preset-specific behaviour -----------------------------------------
    if preset is LambdaPreset.BARBELL:
        # Skill scored against consensus with no credit for matching it: matching
        # is pure downside. Commit where confident, sit at zero elsewhere.
        confident = disagreement < 0.10 and (consensus.is_thin or consensus.is_stale)
        if not confident:
            lam = 0.0
            reasons.append("barbell: not a top-conviction name, lambda=0")

    if inputs.tiny_tilt:
        # Pure win-rate metric: being closer than consensus is all that counts,
        # by any margin. Direction is everything, magnitude is nothing.
        lam = max(lam, TINY_TILT) if lam > 0 else TINY_TILT
        reasons.append(
            f"win-rate metric: minimum meaningful deviation, lambda={lam:.3f}"
        )

    lam = max(0.0, min(1.0, lam))

    return LambdaDecision(
        preset=preset,
        value=lam,
        n_analysts=consensus.n_analysts,
        dispersion=dispersion,
        consensus_stale=consensus.is_stale,
        internal_disagreement=disagreement,
        comparability_flag=inputs.comparability_flag,
        rationale="; ".join(reasons),
    )


def apply(consensus_eps: float, own_estimate: float, decision: LambdaDecision) -> float:
    """The shrinkage itself. Deliberately one line — all the thinking is above."""
    return consensus_eps + decision.value * (own_estimate - consensus_eps)


def baseline(consensus_eps: float, shrunk_company_surprise: float) -> float:
    """The number to beat.

    Not a strawman: 78% of S&P 500 companies beat consensus EPS, aggregate
    surprise +7%. `consensus * (1 + tilt)` is a genuinely strong forecaster and
    it appears on every chart. If the pipeline cannot beat it, lambda should
    have been zero — and saying that out loud beats pretending otherwise.
    """
    return consensus_eps * (1 + shrunk_company_surprise)
