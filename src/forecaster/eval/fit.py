"""Fitting λ. This is the thesis turned from an assertion into a measurement.

    actual = α · consensus + β · own + ε

**β is λ.** Not a number chosen because it felt right — the coefficient that
falls out of regressing what actually happened on the two estimates available
beforehand. Expect it small. A small β is the honest answer and knowing it
empirically beats asserting it, which is precisely the distinction this whole
repo is built around.

Then fit it again per regime, because consensus is much weaker on a four-analyst
name with stale estimates than on a sixty-one-analyst mega-cap with segment-level
models. That per-bucket table is the thesis as a statistical model rather than a
vibe, and it is what replaces the placeholder constants in `f_lambda`.

Constrained so α + β = 1 and both are non-negative. Unconstrained OLS on two
highly collinear regressors happily returns β = 2.4 and α = −1.4, which fits the
sample beautifully and means "triple your deviation and short the Street" — a
number that would look like a finding and destroy the run.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import structlog

from forecaster.eval.shrinkage import winsorize
from forecaster.pipeline.v3_calibrate import Regime

log = structlog.get_logger()

# Below this many observations a bucket's β is noise. The pooled fit is used
# instead and the fallback is recorded, so the table never quietly presents a
# 6-observation coefficient as if it were measured.
MIN_OBS = 30


@dataclass
class Observation:
    """One firm-quarter with both estimates and the outcome."""

    ticker: str
    period: str
    consensus: float
    own: float
    actual: float
    regime: Regime = field(default_factory=lambda: Regime("normal", "tight"))


@dataclass
class Fit:
    alpha: float
    beta: float
    n: int
    r_squared: float
    source: str

    @property
    def summary(self) -> str:
        return (
            f"β={self.beta:.3f} (α={self.alpha:.3f}) on n={self.n}, "
            f"R²={self.r_squared:.3f}, from {self.source}"
        )


def fit_beta(observations: list[Observation], label: str = "pooled") -> Fit | None:
    """Constrained least squares for β in `actual = α·consensus + β·own`.

    With α = 1 − β the model reduces to

        actual − consensus = β · (own − consensus) + ε

    which is a one-parameter regression through the origin — and, not
    coincidentally, exactly the shrinkage form λ is applied in. β is then the
    covariance of the two deviations over the variance of our own deviation.
    """
    if len(observations) < MIN_OBS:
        log.info("fit_skipped", label=label, n=len(observations), need=MIN_OBS)
        return None

    # Winsorize the deviations before fitting. One Micron-style print sets the
    # coefficient for every other name otherwise — the same reason nothing in
    # this repo calibrates on a cap-weighted aggregate.
    x = winsorize([o.own - o.consensus for o in observations])
    y = winsorize([o.actual - o.consensus for o in observations])

    denominator = sum(xi * xi for xi in x)
    if denominator == 0:
        # Our estimate never differed from consensus, so β is unidentifiable.
        # That is a real and reportable finding — the pipeline added nothing —
        # not a reason to emit a default.
        log.warning("fit_degenerate", label=label,
                    why="own estimate never deviated from consensus")
        return None

    beta = sum(xi * yi for xi, yi in zip(x, y, strict=True)) / denominator
    beta = max(0.0, min(1.0, beta))  # see the module docstring

    mean_y = statistics.fmean(y)
    ss_total = sum((yi - mean_y) ** 2 for yi in y)
    ss_residual = sum((yi - beta * xi) ** 2 for xi, yi in zip(x, y, strict=True))
    r_squared = 1 - ss_residual / ss_total if ss_total else 0.0

    fit = Fit(
        alpha=1 - beta, beta=beta, n=len(observations),
        r_squared=r_squared, source=label,
    )
    log.info("fit_complete", label=label, beta=round(beta, 4),
             r2=round(r_squared, 4), n=len(observations))
    return fit


def fit_by_regime(observations: list[Observation]) -> dict[str, Fit]:
    """Per-bucket β, falling back to pooled where a bucket is thin.

    The output of this is what replaces `FITTED_BETA` and the regime multipliers
    in `f_lambda` — at which point the thesis stops being asserted.
    """
    pooled = fit_beta(observations, "pooled")
    buckets: dict[str, list[Observation]] = {}
    for observation in observations:
        buckets.setdefault(observation.regime.key(), []).append(observation)

    out: dict[str, Fit] = {}
    if pooled:
        out["pooled"] = pooled

    for key, group in sorted(buckets.items()):
        fitted = fit_beta(group, key)
        if fitted is not None:
            out[key] = fitted
        elif pooled is not None:
            out[key] = Fit(
                alpha=pooled.alpha, beta=pooled.beta, n=len(group),
                r_squared=pooled.r_squared,
                source=f"pooled (only {len(group)} obs in {key}, need {MIN_OBS})",
            )
    return out


def report(fits: dict[str, Fit]) -> dict:
    """The table that goes on the eval screen and into `f_lambda`.

    `is_measured` is the load-bearing column: it distinguishes a coefficient
    that was fitted on its own bucket from one borrowed from the pooled fit. A
    table that hid that distinction would present borrowed numbers as measured
    ones, which is the exact failure this module exists to end.
    """
    return {
        "buckets": {
            key: {
                "beta": round(fit.beta, 4),
                "alpha": round(fit.alpha, 4),
                "n": fit.n,
                "r_squared": round(fit.r_squared, 4),
                "source": fit.source,
                "is_measured": not fit.source.startswith("pooled ("),
            }
            for key, fit in sorted(fits.items())
        },
        "interpretation": (
            "β is λ: the weight the data puts on our own estimate versus "
            "consensus. Expect it small. A β near zero on heavy-coverage names "
            "is the correct result, not a failure — shrinking to sixty-one "
            "analysts with segment models is the skilful answer."
        ),
    }
