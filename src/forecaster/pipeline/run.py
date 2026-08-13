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
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import structlog

from forecaster.data import segments
from forecaster.data.loader import Loader
from forecaster.eval import baseline as baseline_mod
from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.model import bridge, from_lenses, project
from forecaster.model import scenarios as scenario_mod
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
from forecaster.pipeline.e_expect import landing, scan, swing
from forecaster.pipeline.e_expect import perception as perception_mod
from forecaster.pipeline.e_lenses import mechanical
from forecaster.pipeline.e_lenses.base import LensContext
from forecaster.schemas import (
    Basis,
    Consensus,
    EventType,
    Forecast,
    LambdaPreset,
    LensName,
    LensOutput,
    SourceKind,
)

log = structlog.get_logger()

# Five earnings releases: one more than `bridge.RECURRENCE_THRESHOLD`, so an item
# CAN reach the recurring threshold without every quarter having to be perfect.
# Each is a cheap-tier call over one exhibit, so the cost is small and bounded.
BRIDGE_QUARTERS = 5


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
    bridges: list = []
    if not replayed:
        with events.node("B5_extract"):
            guides, guide_claims, rejections = _extract_guidance(
                client, config.ticker, acquired, events
            )
            # The bridge reads the SAME documents and needs several quarters of
            # them, because a one-off that has recurred four times is not one.
            bridges, bridge_claims, bridge_notes = _extract_bridges(
                client, config.ticker, acquired, events
            )
            guide_claims.extend(bridge_claims)
            rejections.extend(bridge_notes)

    # ---- B: structure ------------------------------------------------- #
    with events.node("C_structure"):
        store = c_structure.build(
            claims=acquired.claims + guide_claims,
            documents=acquired.documents,
            consensus=consensus,
            guidance=guides,
        )
        store.bridge = _bridge_block(bridges)
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
    # ---- E6/E7: perception and the earnings calls ----------------------- #
    #
    # Both cheap-tier, both producing structure from prose no filing contains,
    # and both run BEFORE stage D — the perception read moves the discount rate
    # in the DCF, and the DCF is built inside stage D.
    # Not guarded on `replayed`: a dossier restores the documents and the
    # transcripts, so a replayed run reads exactly the same prose and should
    # reach the same discount rate. Skipping here would make replay a different
    # pipeline, which is the one thing replay must not be.
    perception_read = None
    calls_read, call_notes = None, []
    if acquired.documents or acquired.transcripts:
        with events.node("E6_perception"):
            # Coverage only: the filings are the evidence base and the
            # transcripts are read separately by `read_calls`, so both are
            # excluded here — a 60k-character transcript truncated to 2,400
            # characters would crowd out every actual article and be scored on
            # its opening pleasantries.
            call_urls = {t.url for t in acquired.transcripts}
            articles = [
                # Dated at `as_of` rather than at publication: the acquisition
                # layer keeps bodies, not mastheads. Staleness is therefore NOT
                # measurable from this leg, and nothing downstream reads it as
                # if it were — only tilt, dispersion and crowding are used.
                {"url": uri, "title": "", "text": body,
                 "publishedDate": config.as_of.isoformat()}
                for uri, body in acquired.documents.items()
                if uri.startswith("http")
                and "sec.gov" not in uri
                and uri not in call_urls
            ]
            perception_read = scan.score_articles(
                client, config.ticker, articles[:14],
                acquired.documents, config.run_index,
            )
            events.emit(
                EventType.NODE_DONE, "E6_perception",
                scored=len(perception_read.reads),
                dropped=len(perception_read.skipped),
            )
        with events.node("E7_calls"):
            calls_read, call_notes = scan.read_calls(
                client, config.ticker, acquired.transcripts, config.run_index
            )
            events.emit(
                EventType.NODE_DONE, "E7_calls",
                quarters=len(acquired.transcripts),
                changes=len(calls_read.changes) if calls_read else 0,
            )

    # Perception reaches the VALUATION, never a driver. It adjusts the equity
    # risk premium and widens the stress grid — see `perception.py` for why the
    # direction is the opposite of what most people assume.
    erp_adjustment, erp_note = (
        perception_read.risk_premium_adjustment() if perception_read else (0.0, "")
    )
    stress, _ = (
        perception_read.stress_multiplier() if perception_read else (1.0, "")
    )

    model = None
    with events.node("D_model"):
        if acquired.history is None:
            log.info("model_skipped", why="no history in the dossier")
        else:
            try:
                model = d_model.build(
                    acquired.history, prices=acquired.prices,
                    erp_adjustment=erp_adjustment, erp_note=erp_note,
                    stress=stress,
                )
                events.emit(
                    EventType.NODE_DONE, "D_model",
                    balanced=model.balanced,
                    quarters_checked=len(model.checks),
                    median_abs_eps_error=model.median_abs_eps_error,
                )
            except (ValueError, KeyError) as exc:
                log.warning("model_failed", error=f"{type(exc).__name__}: {exc}")

    # The model joins the CORPUS rather than each lens's own question, so all six
    # lenses read a byte-identical copy and it is charged once at write rates
    # instead of six times at full rates. Attached here rather than passed to
    # `c_structure.build` because the store is assembled at C and the model is
    # not built until D — and the corpus is only materialised when a lens first
    # asks for it, which is after both.
    if model is not None:
        store.model = d_model.to_block(model)
    store.segments = segments.to_block(acquired.segment_lines)
    store.exposure = getattr(acquired, "exposure_block", "")
    store.calls = scan.to_block(calls_read, call_notes)
    store.perception = (
        perception_mod.to_block(perception_read) if perception_read else ""
    )

    # ---- E: expectations ----------------------------------------------- #
    #
    # What is ALREADY assumed, measured before any lens forms a view. Nothing
    # here forecasts; the thesis is that consensus is beatable where it is
    # structurally weak, and a weakness cannot be located without first stating
    # precisely what is assumed.
    with events.node("E_expect"):
        # E2. The Guidance lens's entire edge, and  has
        # existed since the schema was written with nothing ever assigning it.
        actual_revenue = {}
        if acquired.history is not None:
            for period_label in acquired.history.periods():
                observation = acquired.history.get("revenue", period_label)
                if observation is not None:
                    actual_revenue[period_label] = observation.value
        store.landing = landing.build(
            config.ticker, landing.pair(guides, actual_revenue)
        )

        # E5. Which lines actually decide this company's quarter. Measured by
        # holding each driver at its trailing median and re-running the model,
        # so the judge weighs by something fitted rather than asserted.
        factors = _swing_factors(model, acquired)
        events.emit(
            EventType.NODE_DONE, "E_expect",
            landing=store.landing.n_quarters if store.landing else 0,
            swing=[s.driver for s in factors.top()],
            lenses_worth_running=sorted(factors.lenses_worth_running()),
        )
    # Into the cached corpus, like the model and the segment table: identical
    # for every lens, so charged once at write rates rather than six times.
    store.expectations = "\n\n".join(
        block
        for block in (landing.to_block(store.landing), swing.to_block(factors))
        if block
    )

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
        industry=getattr(acquired, "industry_block", ""),
        value_chain=getattr(acquired, "value_chain_block", ""),
    )

    # ---- C: analyse --------------------------------------------------- #
    lens_results = e_lenses.run_all(
        client, store, ctx, events, config.run_index, config.only_lenses
    )
    lenses: list[LensOutput] = list(lens_results.kept)
    dropped: dict[str, str] = dict(lens_results.dropped)

    # The seventh lens. No model, no tokens, no way to hallucinate — and until
    # now `run.py` had never called it, so the determinism argument the whole
    # architecture rests on was being made about code that did not execute.
    with events.node("E_mechanical"):
        arithmetic = _mechanical(model, acquired, store)
        if arithmetic is not None:
            lenses.append(arithmetic)
            events.emit(
                EventType.NODE_DONE, "E_mechanical",
                eps=arithmetic.eps, revenue=arithmetic.revenue,
            )
        else:
            dropped["mechanical"] = (
                "not enough of the ratio base, share count or price history to "
                "compute it"
            )

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

    # ---- E → D: the ensemble's view, folded back into the model --------- #
    #
    # The return leg. Stage D handed the lenses a model; this puts what they
    # concluded back into it, so their view becomes a forecast column rather than
    # a number sitting beside one.
    #
    # Deliberately AFTER V1: a lens whose citations failed has been dropped, and
    # a dropped lens must not vote on a driver any more than it votes on the
    # forecast. Deliberately BEFORE the judge, because the judge decides how far
    # to move off consensus while the model needs the shape of the view
    # underneath — different questions, different stages.
    driver_report: dict = {}
    if model is not None and model.projected:
        model.projected_drivers, driver_report = from_lenses.apply(
            [year.drivers for year in model.projected], lenses
        )
        model.projected = project.project(
            project.opening_from(acquired.history, model.base_fiscal_year),
            project._fy_totals(acquired.history, model.base_fiscal_year, "revenue"),
            model.projected_drivers,
        )
        events.emit(
            EventType.NODE_DONE, "D_model",
            drivers_applied=sorted(driver_report.get("applied", {})),
            drivers_silent=driver_report.get("silent", []),
            drivers_rejected=len(driver_report.get("rejected", [])),
            balanced=all(year.balanced for year in model.projected),
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

    # ---- G2: bull / base / bear ---------------------------------------- #
    #
    # After the judge, because the base case IS the judged number — building
    # scenarios around a pre-judge estimate would produce three cases nobody
    # forecast. Only the drivers stage E measured as material move; everything
    # else is held, and the sheet says which.
    cases = None
    with events.node("G2_scenarios"):
        cases = _scenarios(model, acquired, factors, distribution)
        if cases:
            events.emit(
                EventType.NODE_DONE, "G2_scenarios",
                eps=[round(c.eps, 3) for c in cases.cases],
                moved=cases.drivers_moved,
                held=cases.held,
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
        # What the ensemble actually moved, what it stayed silent on, and what
        # was rejected out of range. Silence is not agreement with the historical
        # ratio, and a model with one forecast driver and fifteen extrapolated
        # ones must not read as a fully-formed view.
        "model_drivers": driver_report,
        # Stage E: what was already assumed before any lens spoke.
        "landing": store.landing.model_dump(mode="json") if store.landing else None,
        "swing_factors": [
            {
                "driver": s.driver, "label": s.label, "eps_impact": s.eps_impact,
                "share": s.share, "lenses": list(s.lenses), "material": s.material,
            }
            for s in factors.swings
        ],
        "lens_weights": factors.weights(),
        "scenarios": scenario_mod.to_json(cases) if cases else None,
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
            # The pointer claim is FILING_INDEX; what comes OUT of the document
            # is a quoted sentence from an 8-K exhibit, and must be string-matched
            # like one.
            source_kind=SourceKind.FILING_8K,
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


def _extract_bridges(
    client: LLMClient,
    ticker: str,
    acquired: b_acquire.Acquired,
    events: EventLog,
) -> tuple[list, list, list[str]]:
    """Read the non-GAAP reconciliation out of the last few earnings releases.

    Several quarters rather than one, which is the difference between this and
    the guidance extraction above. Guidance for a quarter already reported is
    stale; a reconciling item from four quarters ago is the evidence that this
    quarter's "unusual" item is neither unusual nor an item.

    Only EX-99 exhibits, one per filing — the reconciliation lives in the press
    release, and EX-99.2 (the CFO commentary) repeats it.
    """
    exhibits = [
        claim
        for claim in acquired.claims
        if (claim.source.page_or_section or "").startswith("EX-99")
        and claim.source.uri in acquired.documents
    ]
    exhibits.sort(
        key=lambda c: (c.source.as_of, c.source.page_or_section or ""), reverse=True
    )

    seen_filings: set = set()
    targets = []
    for claim in exhibits:
        if claim.source.as_of in seen_filings:
            continue
        seen_filings.add(claim.source.as_of)
        targets.append(claim)
        if len(targets) >= BRIDGE_QUARTERS:
            break

    bridges, claims, notes = [], [], []
    for claim in targets:
        built, item_claims, rejected = extract.extract_bridge(
            client, ticker, acquired.documents[claim.source.uri],
            claim.source.uri, claim.source.as_of,
            source_kind=SourceKind.FILING_8K,
        )
        notes.extend(rejected)
        if built is None:
            continue
        bridges.append(built)
        claims.extend(item_claims)

    # Recurrence is only visible across the sequence, so it is counted once all
    # of them are in hand rather than per release.
    extract.count_recurrence(bridges)

    log.info(
        "bridges_extracted", ticker=ticker, releases=len(targets),
        bridges=len(bridges), rejected=len(notes),
    )
    events.emit(
        EventType.NODE_DONE, "B6_bridge",
        releases=len(targets), bridges=len(bridges), rejected=len(notes),
    )
    return bridges, claims, notes


def _bridge_block(bridges: list) -> str:
    """The bridge, for the cached corpus. Leads with the number that matters.

    That number is the non-GAAP PREMIUM and how much of it recurs. Every lens
    needs to know which basis it is speaking in, and Forensics needs to know
    that a third of the "adjustments" have been adjusted every quarter for two
    years.
    """
    if not bridges:
        return (
            "GAAP / NON-GAAP: no reconciliation was extracted. Consensus is "
            "quoted non-GAAP and the filings are GAAP, so any EPS figure below "
            "must state its own basis — there is no bridge to convert with, and "
            "a default ratio is not offered because the gap is company-specific "
            "(the DJIA median was 31% in one recent quarter)."
        )

    latest = bridges[0]
    lines = [
        "GAAP -> NON-GAAP BRIDGE — consensus is non-GAAP, the filings are GAAP.",
        "",
        f"  Latest quarter: GAAP {latest.eps_gaap:.2f} "
        f"{latest.total_adjustment:+.2f} = {latest.eps_non_gaap:.2f} per share "
        f"({latest.gap_pct:+.1%} premium)",
    ]
    if latest.recurring_adjustment:
        share = latest.recurring_adjustment / latest.total_adjustment
        lines.append(
            f"  Of that adjustment, {latest.recurring_adjustment:+.2f} "
            f"({share:.0%}) comes from items excluded in at least "
            f"{bridge.RECURRENCE_THRESHOLD} of the quarters read — these are not "
            "unusual items, they are a permanent cost moved below the line."
        )
    lines.append("")
    for item in sorted(latest.items, key=lambda i: -abs(i.per_share)):
        mark = "  [RECURRING]" if item.is_recurring else ""
        lines.append(f"    {item.per_share:+.3f}  {item.label}{mark}")
    if len(bridges) > 1:
        history = ", ".join(f"{b.gap_pct:+.0%}" for b in bridges)
        lines += ["", f"  Premium across the quarters read (newest first): {history}"]
    return "\n".join(lines)


def _swing_factors(model, acquired) -> swing.SwingFactors:
    """E5 — what each driver is worth in EPS, by re-running the model on it.

    Each driver is replaced with what a naive forecaster would assume — its own
    trailing median — and the projection re-run. The change in year-one EPS is
    what getting that one line wrong costs, in cents, on this company's actual
    cost structure. Directly comparable across lines, which is the property that
    makes it a weight.

    A counterfactual rather than a regression on purpose: eight observations and
    six correlated drivers is a fit to noise.
    """
    if model is None or not model.projected or not model.projected_drivers:
        return swing.SwingFactors(ticker=getattr(model, "ticker", "?"))

    base_year = model.projected[0]
    base_eps = base_year.income.get("eps_diluted")
    seeded = model.projected_drivers
    opening = project.opening_from(acquired.history, model.base_fiscal_year)
    revenue = project._fy_totals(acquired.history, model.base_fiscal_year, "revenue")

    perturbed: dict[str, float | None] = {}
    for driver in swing.LENS_FOR_DRIVER:
        if not hasattr(seeded[0], driver):
            continue
        # One standard deviation of this line's OWN quarterly history — a
        # realistic surprise rather than a return to the average. Perturbing to
        # the median instead measures nothing, because the model is seeded at
        # the median: every line but revenue growth scored exactly 0.0%.
        move = swing.typical_move(_driver_history(acquired.history, driver))
        if not move:
            continue
        base_value = getattr(seeded[0], driver).value
        moved = list(seeded)
        moved[0] = replace(
            seeded[0],
            **{driver: project.Driver(base_value + move, "held", "one sigma")},
        )
        try:
            years = project.project(opening, revenue, moved)
            perturbed[driver] = years[0].income.get("eps_diluted")
        except ValueError:
            perturbed[driver] = None

    return swing.measure(model.ticker, base_eps, perturbed)


def _scenarios(model, acquired, factors, distribution):
    """Bull / base / bear around the JUDGED number, on the swing factors only.

    Each case is built by moving one material driver at a time through the same
    three-statement model, so the difference between bull and base is a list of
    specific assumption changes each worth a stated number of cents rather than
    a number somebody felt was about right.
    """
    if model is None or not model.projected or not model.projected_drivers:
        return None
    material = [s.driver for s in factors.swings if s.material]
    if not material:
        return None

    seeded = model.projected_drivers
    opening = project.opening_from(acquired.history, model.base_fiscal_year)
    revenue = project._fy_totals(acquired.history, model.base_fiscal_year, "revenue")
    base_eps = model.projected[0].income.get("eps_diluted")
    if not base_eps:
        return None

    base_values = {
        driver: getattr(seeded[0], driver).value
        for driver in material
        if hasattr(seeded[0], driver)
    }

    eps_for: dict[tuple[str, float], float] = {}
    for driver, base_value in base_values.items():
        for direction in (1.0, -1.0):
            value = base_value * (1 + direction * scenario_mod.DEFAULT_MOVE)
            moved = list(seeded)
            moved[0] = replace(
                seeded[0],
                **{driver: project.Driver(value, "forecast", "scenario")},
            )
            try:
                years = project.project(opening, revenue, moved)
            except ValueError:
                continue
            eps = years[0].income.get("eps_diluted")
            if eps is not None:
                eps_for[(driver, value)] = eps

    return scenario_mod.build(
        model.ticker,
        base_eps,
        base_values,
        eps_for,
        material=material,
        immaterial=[s.driver for s in factors.swings if not s.material],
    )


def _mechanical(model, acquired, store) -> LensOutput | None:
    """E1 — the lens with no model in it, finally called.

    174 lines of tested arithmetic that `run.py` had never invoked. It is free,
    it is deterministic, and it is the lens most likely to still be standing at
    18:40 when the API is throttled — which is precisely why the architecture
    claims every stage that can hallucinate is checked by one that cannot.

    Three of its four legs come straight from the model's own ratio base. The
    fourth, FX, needed a geographic revenue split that did not exist until the
    segment extractor was built; `geo_mix` supplies it now.

    `organic_growth` deliberately does NOT come from the Drivers lens. Taking it
    from there would make Mechanical a restatement of Drivers, the two would
    agree by construction, and the judge would read that agreement as
    corroboration.
    """
    if model is None or not model.projected_drivers or not model.projected:
        return None

    drivers = model.projected_drivers[0]
    history = acquired.history
    base = model.base_fiscal_year
    if history is None or base is None:
        return None

    def at(key: str) -> float:
        value = project._fy_totals(history, base, key)
        if value is None:
            closing = project._closing(history, base, key)
            return closing or 0.0
        return value

    revenue_prior = at("revenue")
    if not revenue_prior:
        return None

    shares = project._closing(history, base, "diluted_shares") or 0.0
    if not shares:
        return None

    price = 0.0
    for bar in reversed(acquired.prices or []):
        if bar.complete():
            price = bar.close
            break
    if price <= 0:
        return None

    inputs = mechanical.MechanicalInputs(
        revenue_prior_year=revenue_prior,
        organic_growth=drivers.revenue_growth.value,
        # The geographic revenue split IS the translation exposure. Regions are
        # not currencies, so without a mapping the FX leg contributes zero —
        # which is the right failure: it degrades to no adjustment rather than
        # to a guessed one.
        geo_mix=[
            mechanical.GeoMix(currency=region, share=share)
            for region, share in (acquired.geo_mix or [])
        ],
        rate_start={},
        rate_avg_quarter={},
        gross_margin=drivers.gross_margin.value,
        opex=revenue_prior * drivers.opex_pct_revenue.value,
        tax_rate=drivers.tax_rate.value,
        shares_prior=shares,
        buyback_spend=abs(at("buyback")),
        avg_price=price,
        cash=project._closing(history, base, "cash") or 0.0,
        debt=(project._closing(history, base, "long_term_debt") or 0.0),
        rate_cash=drivers.interest_rate_cash.value,
        rate_debt=drivers.interest_rate_debt.value,
    )

    # Every claim in the store, because the arithmetic rests on the whole ratio
    # base rather than on any one figure. An uncited lens is dropped by V1.
    cited = sorted(store.claims)[:12]
    if not cited:
        return None
    try:
        return mechanical.run(inputs, cited)
    except (ValueError, ZeroDivisionError) as exc:
        log.warning("mechanical_failed", error=f"{type(exc).__name__}: {exc}")
        return None


def _driver_history(history, driver: str) -> list[float]:
    """The quarterly series behind one model driver, for measuring its volatility.

    Each is reconstructed from the line items rather than stored, because the
    drivers are ratios and the history holds the numerator and denominator
    separately — which is also what lets a driver be measured on a company that
    never reports the ratio itself.
    """
    if history is None:
        return []
    periods = history.periods()

    def series(numerator: str, denominator: str) -> list[float]:
        out = []
        for period_label in periods:
            top = history.get(numerator, period_label)
            bottom = history.get(denominator, period_label)
            if top is not None and bottom is not None and bottom.value:
                out.append(top.value / bottom.value)
        return out

    if driver == "gross_margin":
        return series("gross_profit", "revenue")
    if driver == "opex_pct_revenue":
        return series("opex", "revenue")
    if driver == "tax_rate":
        return [r for r in series("tax", "pretax_income") if 0.0 <= r <= 0.6]
    if driver == "revenue_growth":
        out = []
        for i, period_label in enumerate(periods):
            if i < 4:
                continue
            now = history.get("revenue", period_label)
            ago = history.get("revenue", periods[i - 4])
            if now is not None and ago is not None and ago.value:
                out.append(now.value / ago.value - 1)
        return out
    return []


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
