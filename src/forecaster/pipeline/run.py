"""The whole pipeline, A through G, in one readable function.

This file is the architecture diagram as code, and it is deliberately flat: you
should be able to read `forecast()` top to bottom and see every stage in order,
because on the day you will need to explain layers C to F under questioning and
a clever abstraction here would cost you that.

    A  ACQUIRE     numbers · filings · industry · macro
    B  STRUCTURE   evidence store · guidance · landing distribution
    C  ANALYSE     7 lenses, blind to each other
    V1 RECONCILE   arithmetic + citations — fail drops the lens
    D  CHALLENGE   argue each case, then argue against it
    E  JUDGE       impact-weighted → a distribution
    V2 COMPARABLE  M&A · accounting change · 53rd week → λ collapses
    F  POSITION    λ vs consensus, fitted and regime-conditioned
    V3 CALIBRATE   bootstrap our own backtest residuals
    G  OUTPUT      forecast + model + trace

Every stage emits events, so the live architecture view is driven by running the
pipeline rather than by a separate animation — and replay mode is free, because
the UI reads a recorded event log through this identical code path.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import date

import structlog

from forecaster.data.loader import Loader
from forecaster.eval import baseline as baseline_mod
from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.pipeline import (
    a_acquire,
    b_structure,
    c_lenses,
    d_champion,
    e_judge,
    f_lambda,
    v1_reconcile,
    v2_comparability,
    v3_calibrate,
)
from forecaster.pipeline.c_lenses.base import LensContext
from forecaster.schemas import (
    Basis,
    Consensus,
    EventType,
    Forecast,
    LambdaPreset,
    LensName,
    LensOutput,
)

log = structlog.get_logger()


@dataclass
class RunConfig:
    ticker: str
    period: str
    as_of: date
    preset: LambdaPreset = LambdaPreset.SHRINK
    basis: Basis = Basis.NON_GAAP
    tiny_tilt: bool = False
    run_index: int = 0
    sector: str = "unknown"
    only_lenses: list[LensName] | None = None
    residuals: v3_calibrate.ResidualBook = field(
        default_factory=v3_calibrate.ResidualBook
    )
    own_surprises: list[float] = field(default_factory=list)
    peer_surprises: dict[str, list[float]] = field(default_factory=dict)


@dataclass
class RunResult:
    forecast: Forecast
    trace: dict


def forecast(
    config: RunConfig,
    loader: Loader,
    client: LLMClient,
    events: EventLog,
) -> RunResult:
    started = time.monotonic()
    # Note the kwargs: `EventLog.emit` collects **payload, so passing
    # `payload={...}` would nest it a second time and every consumer reading
    # `event.payload.ticker` would get undefined.
    events.emit(
        EventType.RUN_START,
        ticker=config.ticker,
        period=config.period,
        as_of=config.as_of.isoformat(),
        preset=config.preset.value,
        run_index=config.run_index,
    )

    # ---- A: acquire --------------------------------------------------- #
    acquired = a_acquire.acquire(
        config.ticker, config.period, config.as_of, loader, events
    )
    consensus: Consensus | None = acquired.consensus  # type: ignore[assignment]

    # ---- B: structure ------------------------------------------------- #
    with events.node("B_structure"):
        store = b_structure.build(
            claims=acquired.claims,
            documents=acquired.documents,
            consensus=consensus,
        )
        events.emit(EventType.CLAIM_ADDED, "B_structure", n=store.n_claims)

    ctx = LensContext(
        ticker=config.ticker,
        period=config.period,
        as_of=config.as_of,
        basis=config.basis,
        # Acquisition knows the sector from the prepared universe; the caller's
        # value is only a fallback for a company we never prepared for.
        sector=acquired.sector if acquired.sector != "unknown" else config.sector,
        prior_year=acquired.prior_year_block,
        drivers=acquired.driver_block,
        peers=acquired.peer_block,
        macro=acquired.macro_block,
        working_revenue=_working_revenue(acquired, consensus),
    )

    # ---- C: analyse --------------------------------------------------- #
    lens_results = c_lenses.run_all(
        client, store, ctx, events, config.run_index, config.only_lenses
    )
    lenses: list[LensOutput] = list(lens_results.kept)
    dropped: dict[str, str] = dict(lens_results.dropped)

    # ---- V1: reconcile ------------------------------------------------ #
    with events.node("V1_reconcile"):
        verified, failed = v1_reconcile.verify_citations(
            [store.claims[cid] for lens in lenses for cid in lens.claim_ids
             if cid in store.claims],
            store.documents,
        )
        reconciled = []
        for lens in lenses:
            lens_failed = [cid for cid in lens.claim_ids if cid in failed]
            reconciled.append(v1_reconcile.reconcile_lens(lens, None, lens_failed))
        lenses, newly_dropped = v1_reconcile.drop_failed(reconciled)
        dropped.update(newly_dropped)
        events.emit(
            EventType.NODE_DONE,
            "V1_reconcile",
            verified=len(verified),
            failed=len(failed),
            lenses_dropped=len(newly_dropped),
        )

    if not lenses:
        raise RuntimeError(
            f"every lens was dropped for {config.ticker} {config.period}. "
            f"Reasons: {dropped}. This is a pipeline failure, not a forecast."
        )

    # ---- D: challenge -------------------------------------------------- #
    lenses = d_champion.develop(
        client, lenses, store, config.ticker, config.period, events, config.run_index
    )

    # ---- E: judge ------------------------------------------------------ #
    distribution, judge_rationale = e_judge.judge(
        client, lenses, dropped, consensus, config.ticker, config.period,
        config.basis, events, config.run_index,
    )

    # ---- V2: comparability --------------------------------------------- #
    comparability_flag, comparability_note = v2_comparability.check(
        client, config.ticker, config.period, config.as_of,
        _events_block(store), events,
    )

    # ---- F: position ---------------------------------------------------- #
    with events.node("F_lambda"):
        own_estimate = distribution.point(
            "squared" if config.preset is LambdaPreset.SHRINK else "absolute"
        )
        if consensus is None:
            # Without consensus there is nothing to shrink toward, so λ is
            # meaningless and the own estimate stands. Say so rather than
            # silently applying a λ against a zero.
            decision = None
            final_eps = own_estimate
            baseline_eps = own_estimate
            baseline_note = "no consensus available — λ not applied"
        else:
            decision = f_lambda.decide(
                config.preset,
                f_lambda.LambdaInputs(
                    consensus=consensus,
                    lenses=lenses,
                    own_estimate=own_estimate,
                    comparability_flag=comparability_flag,
                    tiny_tilt=config.tiny_tilt,
                ),
            )
            final_eps = f_lambda.apply(consensus.eps, own_estimate, decision)
            built = baseline_mod.build(
                consensus.eps, config.ticker,
                config.own_surprises, config.peer_surprises,
            )
            baseline_eps, baseline_note = built.eps, built.rationale
        events.emit(
            EventType.NODE_DONE,
            "F_lambda",
            lambda_value=decision.value if decision else None,
            own=own_estimate,
            consensus=consensus.eps if consensus else None,
            final=final_eps,
        )

    # ---- V3: calibrate --------------------------------------------------- #
    with events.node("V3_calibrate"):
        distribution, calibration_note = v3_calibrate.calibrate(
            distribution, config.residuals, consensus, point=final_eps
        )
        events.emit(
            EventType.NODE_DONE, "V3_calibrate", calibrated=distribution.calibrated
        )

    # ---- G: output -------------------------------------------------------- #
    wall_clock_ms = int((time.monotonic() - started) * 1000)
    cost = client.report()

    if decision is None:
        # `Forecast` requires a decision; record the degenerate one explicitly
        # rather than fabricating a λ that was never computed.
        decision = f_lambda.LambdaDecision(
            preset=config.preset,
            value=1.0,
            internal_disagreement=f_lambda.internal_disagreement(lenses),
            rationale="no consensus available — the own estimate stands unshrunk",
        )

    result = Forecast(
        ticker=config.ticker,
        period=config.period,
        as_of=config.as_of,
        eps_non_gaap=final_eps,
        eps_gaap=None,  # set by the caller when a verified bridge exists
        revenue=_median_revenue(lenses),
        distribution=distribution,
        consensus=consensus
        or Consensus(eps=final_eps, basis=config.basis, as_of=config.as_of),
        lambda_decision=decision,
        lenses=lenses,
        dropped_lenses=dropped,
        baseline_eps=baseline_eps,
        total_cost_usd=cost["total_cost_usd"],
        total_input_tokens=sum(c.usage.input_tokens for c in client.calls),
        total_output_tokens=sum(c.usage.output_tokens for c in client.calls),
        wall_clock_ms=wall_clock_ms,
    )

    events.emit(
        EventType.RUN_DONE,
        eps=final_eps,
        baseline=baseline_eps,
        lambda_value=decision.value,
        cost_usd=cost["total_cost_usd"],
    )
    log.info(
        "run_complete",
        ticker=config.ticker,
        period=config.period,
        eps=round(final_eps, 4),
        consensus=round(consensus.eps, 4) if consensus else None,
        lam=round(decision.value, 3),
        kept=len(lenses),
        dropped=len(dropped),
        cost_usd=cost["total_cost_usd"],
        wall_clock_ms=wall_clock_ms,
    )

    trace = {
        "judge_rationale": judge_rationale,
        "comparability": {"flag": comparability_flag, "note": comparability_note},
        "calibration": calibration_note,
        "baseline": baseline_note,
        "citations": {"verified": len(verified), "failed": len(failed)},
        "evidence": {"claims": store.n_claims, "deduped": len(store.dropped)},
        "budgets": acquired.budgets,
        "sources": loader.report(),
        "cost": cost,
    }
    return RunResult(forecast=result, trace=trace)


def _working_revenue(acquired: a_acquire.Acquired, consensus: Consensus | None) -> str:
    """The working top line handed to the Margins lens.

    Sourced from prior-year actuals and the Street's revenue estimate — NOT from
    the Drivers lens. If Margins read Drivers' output the two would agree by
    construction, and the judge would read that manufactured agreement as
    corroboration from two independent views. It isn't.
    """
    parts = []
    if acquired.prior_year_block:
        parts.append(acquired.prior_year_block)
    if consensus is not None and consensus.revenue:
        parts.append(
            f"Street revenue estimate for this quarter: {consensus.revenue:,.0f}"
        )
    if not parts:
        return ""
    parts.append(
        "This is a working assumption from the prior-year base and the Street's "
        "own number. It is not a figure to defend, and it did not come from "
        "another lens."
    )
    return "\n\n".join(parts)


def _median_revenue(lenses: list[LensOutput]) -> float | None:
    """Median, not mean — one lens with a units error must not set the number."""
    values = [lens.revenue for lens in lenses if lens.revenue is not None]
    return statistics.median(values) if values else None


def _events_block(store: b_structure.EvidenceStore) -> str:
    """Filing-level facts for the comparability check. Only what is dated and
    disclosed; this check must never see a derived figure."""
    lines = [
        f"- {c.label} (filed {c.source.as_of}, {c.source.kind.value})"
        for c in store.claims.values()
    ]
    return "\n".join(sorted(set(lines))) or "(no filings acquired)"
