"""The contract.

Every stage in the pipeline speaks these types. If you change one thing in this
repo, change it here first — the frontend types are generated from this file
(`make types`), so drift is impossible by construction.

The load-bearing idea: `Claim` is the only way a number enters the system, and it
cannot be constructed without a source and a verbatim quote. "We don't invent
figures" is therefore a validation error, not a code review comment.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #


class Basis(StrEnum):
    """Which earnings definition a figure is stated on.

    Consensus is universally non-GAAP. XBRL is GAAP. The median DJIA gap between
    them was 31% in one recent quarter. Every EPS figure in this system must
    declare which one it is.
    """

    GAAP = "gaap"
    NON_GAAP = "non_gaap"


class SourceKind(StrEnum):
    FILING_8K = "8k"
    FILING_10Q = "10q"
    FILING_10K = "10k"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    XBRL = "xbrl"
    CONSENSUS = "consensus"
    MACRO = "macro"
    PEER = "peer"
    SPONSOR = "sponsor"
    DERIVED = "derived"


class Source(BaseModel):
    """Where a number came from, and when it became knowable.

    `as_of` is what makes point-in-time backtesting possible: it is the date the
    fact was *filed or published*, not the period it describes.
    """

    model_config = ConfigDict(frozen=True)

    kind: SourceKind
    uri: str
    as_of: date
    accession: str | None = None
    page_or_section: str | None = None


class Claim(BaseModel):
    """A single fact, with provenance. The atom of the evidence store.

    Deliberately impossible to construct without a source. `verbatim_quote` is
    verified against the source document by `v1_reconcile.verify_citations` —
    a quote that does not appear in its source drops the whole lens.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    value: float | str | None
    unit: str | None = None
    period: str | None = None
    source: Source
    verbatim_quote: str = Field(min_length=1)
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0

    @model_validator(mode="after")
    def _numeric_claims_need_units(self) -> Claim:
        if isinstance(self.value, float) and self.unit is None:
            raise ValueError(f"claim {self.id}: numeric value requires a unit")
        return self


# --------------------------------------------------------------------------- #
# market context
# --------------------------------------------------------------------------- #


class Consensus(BaseModel):
    """The Street's view, plus the metadata that tells you how much to trust it.

    `n_analysts`, `dispersion` and `days_since_last_revision` are the inputs to
    lambda. They matter more than the estimate itself.
    """

    eps: float
    revenue: float | None = None
    basis: Basis = Basis.NON_GAAP
    n_analysts: int | None = None
    eps_high: float | None = None
    eps_low: float | None = None
    days_since_last_revision: int | None = None
    revisions_up_30d: int | None = None
    revisions_down_30d: int | None = None
    as_of: date

    @property
    def dispersion(self) -> float | None:
        """High-low spread as a fraction of the mean. Wide spread = low information."""
        if self.eps_high is None or self.eps_low is None or self.eps == 0:
            return None
        return abs(self.eps_high - self.eps_low) / abs(self.eps)

    @property
    def is_thin(self) -> bool:
        """The median S&P 1500 company has four estimates. Below that, consensus
        is nearly a single opinion and is materially more beatable."""
        return self.n_analysts is not None and self.n_analysts <= 5

    @property
    def is_stale(self) -> bool:
        return (
            self.days_since_last_revision is not None
            and self.days_since_last_revision > 30
        )


class Guidance(BaseModel):
    """What management told the Street to expect, at the last earnings call.

    58-63% of guiding companies guide *negative*. This is a floor-setting
    exercise, not a forecast — which is why `landing_cdf` below matters more
    than the range itself.
    """

    metric: Literal["eps", "revenue"]
    period: str
    low: float | None = None
    high: float | None = None
    point: float | None = None
    basis: Basis = Basis.NON_GAAP
    constant_currency: bool = False
    claim_id: str

    @property
    def midpoint(self) -> float | None:
        if self.point is not None:
            return self.point
        if self.low is not None and self.high is not None:
            return (self.low + self.high) / 2
        return None


class LandingDistribution(BaseModel):
    """Where this company historically lands *inside its own guided range*.

    Everyone reads the guidance. Almost nobody builds this. Some companies hit
    the midpoint like clockwork; some habitually clear the top end. Expressed as
    a position in [0, 1] where 0 = low end, 1 = high end, >1 = beat the range.
    """

    ticker: str
    n_quarters: int
    positions: list[float]
    median_position: float
    shrunk_position: float = Field(
        description="Empirical-Bayes shrunk toward the sector median. With n~8 the "
        "raw statistic is mostly noise; this is the one to use."
    )


# --------------------------------------------------------------------------- #
# lens output
# --------------------------------------------------------------------------- #


class LensName(StrEnum):
    MECHANICAL = "mechanical"
    GUIDANCE = "guidance"
    DRIVERS = "drivers"
    MARGINS = "margins"
    FORENSICS = "forensics"
    PEER_READ = "peer_read"
    MACRO = "macro"


class LensOutput(BaseModel):
    """One lens's independent view. Lenses never see each other's output —
    if they do they converge, and converging is how you rebuild consensus."""

    lens: LensName
    eps: float | None = None
    revenue: float | None = None
    basis: Basis = Basis.NON_GAAP

    reasoning: str
    claim_ids: list[str] = Field(
        min_length=1,
        description="Every claim this lens relied on. A lens that cites nothing "
        "is dropped by the reconciler.",
    )
    confidence: Annotated[float, Field(ge=0, le=1)]

    # populated by v1_reconcile
    reconciled: bool | None = None
    reconcile_errors: list[str] = Field(default_factory=list)

    # populated by d_champion
    thesis: str | None = None
    counterargument: str | None = None

    # run bookkeeping — "a single run of a model is a coin flip wearing a suit"
    run_index: int = 0
    model_used: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    @property
    def usable(self) -> bool:
        return self.reconciled is not False and self.eps is not None


# --------------------------------------------------------------------------- #
# judgment and positioning
# --------------------------------------------------------------------------- #


class Distribution(BaseModel):
    """The judge's output, and the system's internal currency.

    A distribution is a strict superset of a point forecast: you can emit a
    median for MAE, a mean for MSE, quantiles for CRPS, or a direction for a
    win-rate metric. Building this once makes the scoring rule a config value
    rather than a design input.
    """

    median: float
    mean: float
    quantiles: dict[str, float] = Field(
        description="Keys are quantile levels as strings, e.g. '0.1', '0.5', '0.9'."
    )
    stdev: float | None = None
    calibrated: bool = False

    def point(self, loss: Literal["absolute", "squared"] = "absolute") -> float:
        """Median minimises absolute error; mean minimises squared error."""
        return self.median if loss == "absolute" else self.mean


class LambdaPreset(StrEnum):
    """Precomputed strategies, one per metric family. Chosen at 10:30 on the day
    from the decision card, not designed on the day."""

    SHRINK = "shrink"  # MAE / MAPE / MSE
    BARBELL = "barbell"  # skill score vs consensus, rank leaderboards
    CALIBRATED = "calibrated"  # CRPS / pinball


class LambdaDecision(BaseModel):
    """How far off the Street we go, and why. This is the thesis, made explicit.

    Everything upstream of here forecasts. This decides how much to trust that
    forecast against sixty-one analysts. Keeping it structurally separate is
    the point.
    """

    preset: LambdaPreset
    value: Annotated[float, Field(ge=0, le=1)]

    n_analysts: int | None = None
    dispersion: float | None = None
    consensus_stale: bool = False
    internal_disagreement: float = Field(
        description="Spread across lens estimates. High disagreement means our own "
        "evidence is weak — shrink regardless of what the meta-layer says."
    )
    comparability_flag: str | None = Field(
        default=None,
        description="M&A, accounting change, 53rd week, withdrawn guidance. When "
        "set, lambda collapses — historical priors do not apply.",
    )
    rationale: str


class Forecast(BaseModel):
    """What gets submitted, and what the UI renders.

    Carries *both* bases. Which one is scored is the single largest unknown
    going into the day, and modelling both turns it into a flag.
    """

    ticker: str
    period: str
    as_of: date

    eps_non_gaap: float
    eps_gaap: float | None = None
    revenue: float | None = None

    distribution: Distribution
    consensus: Consensus
    lambda_decision: LambdaDecision

    lenses: list[LensOutput]
    dropped_lenses: dict[str, str] = Field(
        default_factory=dict,
        description="Lens name -> why it was dropped. Surfaced in the UI, never "
        "silently swallowed.",
    )

    baseline_eps: float = Field(
        description="consensus * (1 + shrunk company surprise). Every chart shows "
        "this. If we cannot beat it, lambda should have been zero."
    )

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    wall_clock_ms: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def surprise_vs_consensus(self) -> float:
        """Our deviation from the Street, as a fraction.

        A computed field rather than a plain property so it is serialised into
        `out/results.json` and appears in the generated TypeScript. A bare
        `@property` exists only in Python, which means the UI would have to
        recompute it — and a number recomputed in two places is a number that
        eventually disagrees with itself.
        """
        if self.consensus.eps == 0:
            return 0.0
        return (self.eps_non_gaap - self.consensus.eps) / abs(self.consensus.eps)


# --------------------------------------------------------------------------- #
# run events — the frontend polls these
# --------------------------------------------------------------------------- #


class EventType(StrEnum):
    RUN_START = "run_start"
    NODE_START = "node_start"
    NODE_DONE = "node_done"
    NODE_FAILED = "node_failed"
    CLAIM_ADDED = "claim_added"
    RUN_DONE = "run_done"


class Event(BaseModel):
    """One line of out/events.ndjson. The live architecture view is driven
    entirely by this stream — which is also why replay mode is free."""

    seq: int
    type: EventType
    node: str | None = None
    ts_ms: int
    payload: dict = Field(default_factory=dict)
