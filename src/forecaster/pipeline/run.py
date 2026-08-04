"""The whole pipeline, A through G, in one readable function.

This file is the architecture diagram as code, and it is deliberately flat: you
should be able to read `forecast()` top to bottom and see every stage in order,
because on the day you will need to explain layers C to F under questioning and
a clever abstraction here would cost you that.

    B  ACQUIRE     numbers · filings · industry · macro
    C  STRUCTURE   evidence store · guidance · landing distribution
    E  ANALYSE     7 lenses, blind to each other
    V1 RECONCILE   arithmetic + citations — fail drops the lens
    F  CHALLENGE   argue each case, then argue against it
    G  JUDGE       impact-weighted → a distribution
    V2 COMPARABLE  M&A · accounting change · 53rd week → λ collapses
    H  POSITION    λ vs consensus, fitted and regime-conditioned
    V3 CALIBRATE   bootstrap our own backtest residuals
    I  OUTPUT      forecast + model + trace

Every stage emits events, so the live architecture view is driven by running the
pipeline rather than by a separate animation — and replay mode is free, because
the UI reads a recorded event log through this identical code path.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import structlog

from forecaster.data.loader import Loader
from forecaster.eval import baseline as baseline_mod
from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.pipeline import (
    b_acquire,
    c_structure,
    d_model,
    dossier,
    e_lenses,
    extract,
    f_champion,
    g_judge,
    h_lambda,
    v1_reconcile,
    v2_comparability,
    v3_calibrate,
)
from forecaster.pipeline.e_lenses.base import LensContext
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
    dossier_path: Path | str | None = None,
) -> RunResult:
    """A through G. Pass `dossier_path` to start from a recorded acquisition.

    Reading the dossier instead of re-acquiring is what makes prompt iteration
    affordable: acquire once, restructure and re-run the lenses fifty times
    without touching the network. It is also the honest way to compare two
    prompt versions — same evidence, byte for byte, so the difference measured
    is the prompt rather than a document that changed underneath it.
    """
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
    replayed = dossier_path is not None
    if replayed:
        acquired, guides, _ = dossier.read(dossier_path)
        guide_claims, rejections = [], []
        events.emit(
            EventType.NODE_DONE,
            "B_acquire",
            replayed_from=str(dossier_path),
            claims=len(acquired.claims),
            documents=len(acquired.documents),
        )
    else:
        acquired = b_acquire.acquire(
            config.ticker, config.period, config.as_of, loader, events
        )
    consensus: Consensus | None = acquired.consensus  # type: ignore[assignment]

    # ---- B5: extract guidance ------------------------------------------ #
    #
    # Acquisition brings back the earnings release as TEXT. Until something
    # reads it, the guidance paragraph, the non-GAAP bridge and the segment
    # table sit in the corpus as prose that no claim points at — so no lens can
    # cite them, `EvidenceStore.guidance` stays empty, and the forecast comes
    # out on a GAAP basis while consensus is quoted non-GAAP. Different units,
    # a median 31% apart.
    #
    # This is the one extraction that needs a model, because guidance lives in
    # sentences rather than in XBRL. Every extracted quote is string-matched
    # back against its source inside `extract_guidance`, and one that cannot be
    # found is dropped — a range assembled from two different sentences reads
    # perfectly and is not what the company said.
    # A dossier already carries its guidance, and re-extracting would spend a
    # model call to reproduce a result recorded on disk.
    if not replayed:
        with events.node("B5_extract"):
            guides, guide_claims, rejections = _extract_guidance(
                client, config.ticker, acquired, events
            )

    # ---- B: structure ------------------------------------------------- #
    with events.node("C_structure"):
        store = c_structure.build(
            claims=acquired.claims + guide_claims,
            documents=acquired.documents,
            consensus=consensus,
            guidance=guides,
        )
        events.emit(EventType.CLAIM_ADDED, "C_structure", n=store.n_claims)

    # ---- D: model ----------------------------------------------------- #
    #
    # Deterministic, and deliberately before the lenses rather than after the
    # judge. Only the PROJECTION needs a revenue view; the historical statements,
    # the ratio base and the model's own measured error are arithmetic on
    # filings, and a lens that can see the company's margin trajectory is
    # reasoning about a company rather than about a bag of claims.
    #
    # A failure here is not fatal. The lenses ran without a model until now and
    # can again; what they lose is context, not their inputs.
    model = None
    with events.node("D_model"):
        if acquired.history is None:
            log.info("model_skipped", why="no history in the dossier")
        else:
            try:
                model = d_model.build(acquired.history, prices=acquired.prices)
                events.emit(
                    EventType.NODE_DONE, "D_model",
                    balanced=model.balanced,
                    quarters_checked=len(model.checks),
                    median_abs_eps_error=model.median_abs_eps_error,
                )
            except (ValueError, KeyError) as exc:
                log.warning("model_failed", error=f"{type(exc).__name__}: {exc}")

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
        model=d_model.to_block(model) if model else "",
    )

    # ---- C: analyse --------------------------------------------------- #
    lens_results = e_lenses.run_all(
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
    lenses = f_champion.develop(
        client, lenses, store, config.ticker, config.period, events, config.run_index
    )

    # ---- E: judge ------------------------------------------------------ #
    distribution, judge_rationale = g_judge.judge(
        client, lenses, dropped, consensus, config.ticker, config.period,
        config.basis, events, config.run_index,
    )

    # ---- V2: comparability --------------------------------------------- #
    comparability_flag, comparability_note = v2_comparability.check(
        client, config.ticker, config.period, config.as_of,
        _events_block(store), events,
    )

    # ---- F: position ---------------------------------------------------- #
    with events.node("H_lambda"):
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
            decision = h_lambda.decide(
                config.preset,
                h_lambda.LambdaInputs(
                    consensus=consensus,
                    lenses=lenses,
                    own_estimate=own_estimate,
                    comparability_flag=comparability_flag,
                    tiny_tilt=config.tiny_tilt,
                ),
            )
            final_eps = h_lambda.apply(consensus.eps, own_estimate, decision)
            built = baseline_mod.build(
                consensus.eps, config.ticker,
                config.own_surprises, config.peer_surprises,
            )
            baseline_eps, baseline_note = built.eps, built.rationale
        events.emit(
            EventType.NODE_DONE,
            "H_lambda",
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
        decision = h_lambda.LambdaDecision(
            preset=config.preset,
            value=1.0,
            internal_disagreement=h_lambda.internal_disagreement(lenses),
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
        droppee_lenses=dropped,
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
        # Stage D. `statements` and `balance_check` are lifted to the top level
        # because the model sheet has read them from there since before the
        # stage existed — it was rendering a key nothing ever wrote.
        "model": d_model.to_json(model) if model else None,
        "statements": model.statements if model else None,
        "balance_check": model.balance_detail if model else None,
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


def _unique_guides(guides: list) -> list:
    """Collapse guides carrying identical figures for the same metric and period."""
    seen: set[tuple] = set()
    unique = []
    for guide in guides:
        signature = (guide.metric, guide.period, guide.low, guide.high, guide.point)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(guide)
    return unique


def _extract_guidance(
    client: LLMClient,
    ticker: str,
    acquired: b_acquire.Acquired,
    events: EventLog,
) -> tuple[list, list, list[str]]:
    """Run the extractor over the earnings-release exhibits, newest first.

    Only the EX-99 exhibits, and only the most recent earnings 8-K's. An 8-K's
    primary document is a cover page with no guidance in it, a 10-Q body is
    150k characters of footnotes, and older releases carry guidance for
    quarters that have already been reported — historical sandbagging is a
    lens's question, not a model input. Extraction is the one step here that
    costs a model call per document, so it is pointed at the two documents that
    contain the answer.
    """
    exhibits = [
        claim
        for claim in acquired.claims
        if (claim.source.page_or_section or "").startswith("EX-99")
        and claim.source.uri in acquired.documents
    ]
    # Newest filing first; within it EX-99.1 before EX-99.2.
    exhibits.sort(
        key=lambda c: (c.source.as_of, c.source.page_or_section or ""), reverse=True
    )
    latest = exhibits[0].source.as_of if exhibits else None
    targets = [c for c in exhibits if c.source.as_of == latest]

    guides, guide_claims, rejections = [], [], []
    for claim in targets:
        found, claims, rejected = extract.extract_guidance(
            client,
            ticker,
            acquired.documents[claim.source.uri],
            claim.source.uri,
            claim.source.as_of,
            source_kind=claim.source.kind,
        )
        guides.extend(found)
        guide_claims.extend(claims)
        rejections.extend(rejected)

    # One fact, once. The guidance sentence appears in BOTH the press release
    # and the CFO commentary, and the extractor reports it under each basis —
    # so NVDA's single revenue range arrived four times. Deduplicated on the
    # NUMBERS rather than including the basis: revenue has no GAAP/non-GAAP
    # distinction, and two entries carrying identical figures are one fact
    # labelled twice. Where the bases genuinely differ, the figures differ too
    # and both survive.
    guides = _unique_guides(guides)

    skipped = len(exhibits) - len(targets)
    log.info(
        "guidance_extraction",
        ticker=ticker,
        documents=len(targets),
        guides=len(guides),
        rejected=len(rejections),
        # Never silent. A dropped source has to be visible in the manifest.
        skipped_older_exhibits=skipped or None,
    )
    events.emit(
        EventType.NODE_DONE,
        "B5_extract",
        documents=len(targets),
        guides=len(guides),
        rejected=len(rejections),
    )
    return guides, guide_claims, rejections


def _working_revenue(acquired: b_acquire.Acquired, consensus: Consensus | None) -> str:
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


def _events_block(store: c_structure.EvidenceStore) -> str:
    """Filing-level facts for the comparability check. Only what is dated and
    disclosed; this check must never see a derived figure."""
    lines = [
        f"- {c.label} (filed {c.source.as_of}, {c.source.kind.value})"
        for c in store.claims.values()
    ]
    return "\n".join(sorted(set(lines))) or "(no filings acquired)"
