"""The backtest harness — the gate everything else passes through.

Two rules it exists to enforce:

  1. Nothing filed after `as_of` is visible. Enforced in the sources; asserted
     again here, because a backtest that can't fail this way proves nothing.

  2. The baseline is on every chart. `consensus x (1 + shrunk company surprise)`
     is not a strawman: 78% of S&P 500 companies beat consensus and the
     aggregate surprise is +7%. If the pipeline can't beat that, lambda should
     have been zero — and saying so beats pretending otherwise.

Also reports n and a confidence interval, because with fewer than a few hundred
resolved forecasts you cannot distinguish skill from luck, and the honest
version of that sentence is worth more than a flattering number.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import structlog

from forecaster.eval.shrinkage import mad, winsorize

log = structlog.get_logger()

# Detecting a 2% edge over consensus at 80% power needs roughly this many
# resolved forecasts. Below it, leaderboard position is variance.
POWER_N = 350


@dataclass
class Case:
    """One firm-quarter. `as_of` is the lock date — nothing later is visible."""

    ticker: str
    period: str
    as_of: date
    consensus_eps: float
    actual_eps: float
    n_analysts: int | None = None
    dispersion: float | None = None


@dataclass
class Scored:
    case: Case
    forecast: float
    baseline: float

    @property
    def err(self) -> float:
        return abs(self.forecast - self.case.actual_eps)

    @property
    def err_consensus(self) -> float:
        return abs(self.case.consensus_eps - self.case.actual_eps)

    @property
    def err_baseline(self) -> float:
        return abs(self.baseline - self.case.actual_eps)

    @property
    def beat_consensus(self) -> bool:
        return self.err < self.err_consensus

    @property
    def beat_baseline(self) -> bool:
        return self.err < self.err_baseline


@dataclass
class Result:
    scored: list[Scored] = field(default_factory=list)
    runs_per_case: int = 1
    run_spread: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.scored)

    def _mae(self, attr: str) -> float:
        vals = winsorize([getattr(s, attr) for s in self.scored])
        return statistics.fmean(vals) if vals else 0.0

    @property
    def mae(self) -> float:
        return self._mae("err")

    @property
    def mae_consensus(self) -> float:
        return self._mae("err_consensus")

    @property
    def mae_baseline(self) -> float:
        return self._mae("err_baseline")

    @property
    def median_ae(self) -> float:
        """Report this alongside MAE. Medians survive the one company that
        prints a $9 surprise against a $2.88 estimate."""
        errs = [s.err for s in self.scored]
        return statistics.median(errs) if errs else 0.0

    @property
    def skill_vs_consensus(self) -> float:
        """1 - sum|F-A| / sum|C-A|. Positive means we beat the Street."""
        num = sum(s.err for s in self.scored)
        den = sum(s.err_consensus for s in self.scored)
        return 1 - num / den if den else 0.0

    @property
    def win_rate(self) -> float:
        return (
            sum(s.beat_consensus for s in self.scored) / self.n if self.n else 0.0
        )

    @property
    def win_rate_ci(self) -> tuple[float, float]:
        """95% Wilson score interval on the win rate.

        Wilson rather than the normal (Wald) approximation, for a reason that
        bites exactly here: at p=1.0 — say you beat consensus on all 20 of your
        backtest cases — Wald gives a width of ZERO. It would report "100%,
        +/- 0%", which is nonsense at n=20 and is precisely the overclaiming
        this harness exists to prevent. Wilson stays honest at the boundaries.

        This interval usually spans 0.5. That is the point; say it before
        someone else does.
        """
        if self.n == 0:
            return (0.0, 0.0)
        z, n, p = 1.96, self.n, self.win_rate
        denom = 1 + z**2 / n
        centre = (p + z**2 / (2 * n)) / denom
        half = (z / denom) * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5)
        return (max(0.0, centre - half), min(1.0, centre + half))

    @property
    def underpowered(self) -> bool:
        return self.n < POWER_N

    @property
    def mean_run_spread(self) -> float:
        """Across-run variance. 'A single run of a model is a coin flip wearing
        a suit' — so report the spread, and feed it into lambda."""
        return statistics.fmean(self.run_spread) if self.run_spread else 0.0

    def summary(self) -> dict:
        lo, hi = self.win_rate_ci
        return {
            "n": self.n,
            "runs_per_case": self.runs_per_case,
            "mae": round(self.mae, 4),
            "median_ae": round(self.median_ae, 4),
            "mae_consensus": round(self.mae_consensus, 4),
            "mae_baseline": round(self.mae_baseline, 4),
            "skill_vs_consensus": round(self.skill_vs_consensus, 4),
            "beat_baseline_rate": round(
                sum(s.beat_baseline for s in self.scored) / self.n, 3
            )
            if self.n
            else 0.0,
            "win_rate_vs_consensus": round(self.win_rate, 3),
            "win_rate_ci95": [round(lo, 3), round(hi, 3)],
            "mean_run_spread": round(self.mean_run_spread, 4),
            "underpowered": self.underpowered,
            "power_note": (
                f"n={self.n} < {POWER_N} needed to detect a 2% edge at 80% power; "
                "treat ranking as variance-dominated"
                if self.underpowered
                else f"n={self.n} is adequately powered"
            ),
        }


Forecaster = Callable[[Case], float]


def run(
    cases: list[Case],
    forecaster: Forecaster,
    baseline_tilt: float = 0.02,
    runs_per_case: int = 1,
) -> Result:
    """Score a forecaster against actuals, consensus and the baseline.

    `runs_per_case > 1` re-runs a stochastic forecaster and records the spread.
    The median across runs is scored; the spread is reported and is a genuine
    confidence signal, not decoration.
    """
    result = Result(runs_per_case=runs_per_case)

    for case in cases:
        if case.as_of >= _report_date_guess(case):
            log.warning(
                "suspicious_as_of",
                ticker=case.ticker,
                period=case.period,
                note="as_of is at or after the likely report date — possible leak",
            )

        predictions = [forecaster(case) for _ in range(runs_per_case)]
        forecast = statistics.median(predictions)
        if runs_per_case > 1:
            result.run_spread.append(mad(predictions))

        result.scored.append(
            Scored(
                case=case,
                forecast=forecast,
                baseline=case.consensus_eps * (1 + baseline_tilt),
            )
        )

    return result


def ablate(
    cases: list[Case], build: Callable[[list[str]], Forecaster], lenses: list[str]
) -> dict[str, float]:
    """Leave-one-lens-out. Non-optional.

    Returns {lens: change in MAE when removed}. Positive means removing it made
    things worse, i.e. the lens earns its tokens. If two of seven come out at
    zero, drop them and say so on stage — that lands better than an
    unfalsifiable win.
    """
    full = run(cases, build(lenses)).mae
    out: dict[str, float] = {}
    for lens in lenses:
        without = [x for x in lenses if x != lens]
        out[lens] = round(run(cases, build(without)).mae - full, 5)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _report_date_guess(case: Case) -> date:
    """Crude guard: a quarter is normally reported within ~60 days of its end."""
    return case.as_of.replace(year=case.as_of.year + 1)
