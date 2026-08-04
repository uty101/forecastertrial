"""Verification layer 3 — calibration by bootstrapping our own residuals.

Model-stated confidence is uncalibrated and always will be. The judge's 10-90
span is a reasonable ordering of "more sure" versus "less sure", but there is no
reason for it to cover 80% of outcomes, and it won't.

So replace it. Take the residuals this pipeline actually produced on the
backtest — conditioned on regime, because the error distribution on a
four-analyst name is not the error distribution on a sixty-one-analyst name —
and bootstrap the interval from those. The result then reflects how wrong we
*have been*, not how wrong the model *thinks* it might be.

Pure statistics, no model call. Which is the point: this is the layer that makes
the reliability diagram in the eval screen mean something, and a calibration
step that itself needed calibrating would be circular.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import structlog

from forecaster.eval.shrinkage import mad, winsorize
from forecaster.schemas import Consensus, Distribution

log = structlog.get_logger()

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)

# Below this many residuals in a bucket, the empirical quantiles are noise and
# we fall back to the pooled distribution. Eight residuals cannot tell you where
# the 10th percentile is.
MIN_BUCKET = 25


@dataclass(frozen=True)
class Regime:
    """The conditioning variables. Deliberately few and coarse: every extra
    dimension halves the residuals per bucket, and an empty bucket is worse than
    a crude one."""

    coverage: str  # thin | normal | heavy
    dispersion: str  # tight | wide

    @classmethod
    def of(cls, consensus: Consensus | None) -> Regime:
        if consensus is None:
            return cls("normal", "tight")
        n = consensus.n_analysts
        coverage = (
            "thin" if n is not None and n <= 5
            else "heavy" if n is not None and n >= 40
            else "normal"
        )
        d = consensus.dispersion
        dispersion = "wide" if d is not None and d > 0.15 else "tight"
        return cls(coverage, dispersion)

    def key(self) -> str:
        return f"{self.coverage}/{self.dispersion}"


@dataclass
class ResidualBook:
    """Backtest residuals, as fractions of consensus EPS.

    Fractions, not cents: a 5-cent miss on a $0.40 print and a 5-cent miss on a
    $12 print are not the same error, and pooling them in absolute terms lets
    the mega-caps set the interval for the small names.
    """

    by_regime: dict[str, list[float]] = field(default_factory=dict)

    def add(self, regime: Regime, residual: float) -> None:
        self.by_regime.setdefault(regime.key(), []).append(residual)

    def pooled(self) -> list[float]:
        return [r for rs in self.by_regime.values() for r in rs]

    def for_regime(self, regime: Regime) -> tuple[list[float], str]:
        """Residuals to use, and which bucket they came from.

        Returning the source matters: an interval built from the pooled book
        because the bucket was thin is a weaker claim than one built from its
        own regime, and the UI should be able to say which it was.
        """
        own = self.by_regime.get(regime.key(), [])
        if len(own) >= MIN_BUCKET:
            return own, regime.key()
        pooled = self.pooled()
        return pooled, f"pooled (only {len(own)} in {regime.key()}, need {MIN_BUCKET})"

    def summary(self) -> dict:
        return {
            "n_total": len(self.pooled()),
            "buckets": {k: len(v) for k, v in sorted(self.by_regime.items())},
        }


def calibrate(
    distribution: Distribution,
    residuals: ResidualBook,
    consensus: Consensus | None,
    point: float | None = None,
) -> tuple[Distribution, str]:
    """Rebuild the interval from empirical residuals. Returns (distribution, note).

    The centre is preserved — this layer has no view on the level, only on the
    width. Moving the point estimate here would silently overwrite the judge's
    work with a statistical artefact.
    """
    regime = Regime.of(consensus)
    sample, source = residuals.for_regime(regime)

    if len(sample) < MIN_BUCKET:
        note = (
            f"NOT CALIBRATED: only {len(sample)} backtest residuals available "
            f"(need {MIN_BUCKET}). The interval below is the judge's own, which "
            "is uncalibrated by nature — do not read the 80% band as 80% coverage."
        )
        log.warning("calibration_skipped", n=len(sample), regime=regime.key())
        return distribution, note

    centre = point if point is not None else distribution.median
    clipped = winsorize(sample)
    quantiles = {
        str(q): centre * (1 + _empirical_quantile(clipped, q)) for q in QUANTILES
    }

    # Preserve the judge's median as the 0.5 point. The residual book's own
    # median encodes our historical bias, which h_lambda already handles; a
    # second correction here would double-count it.
    quantiles["0.5"] = centre

    calibrated = Distribution(
        median=centre,
        mean=centre * (1 + statistics.fmean(clipped)),
        quantiles=dict(sorted(quantiles.items(), key=lambda kv: float(kv[0]))),
        stdev=abs(centre) * mad(clipped),
        calibrated=True,
    )
    note = (
        f"Calibrated on {len(sample)} backtest residuals from {source}. The band "
        f"is how wrong this pipeline has been on comparable names, not how wrong "
        f"the model estimated it might be."
    )
    log.info(
        "calibrated",
        regime=regime.key(),
        source=source,
        n=len(sample),
        p10=round(calibrated.quantiles["0.1"], 4),
        p90=round(calibrated.quantiles["0.9"], 4),
    )
    return calibrated, note


def _empirical_quantile(values: list[float], q: float) -> float:
    """Lower-interpolation percentile.

    `int(q * n)` is wrong and silently so — for n=20, q=0.95 it returns index
    19, which IS the maximum, so the 95th percentile equals the max and nothing
    is ever excluded. The correct index is `q * (n - 1)`. This is the same bug
    that made `winsorize` a no-op; it is written out here so it does not get
    reintroduced by someone copying the pattern.
    """
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = int(q * (len(ordered) - 1))
    return ordered[idx]


def coverage(
    predicted: list[tuple[float, float]], actuals: list[float]
) -> float:
    """Fraction of actuals inside their predicted interval.

    This is the number on the reliability diagram, and it is the only honest
    test of whether calibration worked. An 80% interval that covers 55% is a
    finding to report, not a chart to quietly leave off the slide.
    """
    if not actuals:
        return 0.0
    inside = sum(
        lo <= actual <= hi
        for (lo, hi), actual in zip(predicted, actuals, strict=True)
    )
    return inside / len(actuals)
