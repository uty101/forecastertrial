"""A synthetic run, for building the UI against and for `make verify`.

**This is not a forecast and it is labelled as one that isn't.** The ticker is
`DEMO`, the trace carries a `synthetic` flag, and the UI shows a banner. That
matters more than it sounds: a fabricated result that looks real is exactly the
thing this repo spends its whole design budget preventing, and leaving an
unlabelled fake `results.json` lying around a demo machine is how one ends up on
a projector at 18:40.

The actual demo fallback is a RECORDED REAL RUN replayed through the identical
code path (see `?replay=` in the UI). This is only for developing the frontend
without burning tokens, and for giving `make verify` a deterministic target.

    uv run python -m forecaster.tools.make_fixture --out out
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from forecaster.events import EventLog
from forecaster.schemas import (
    Basis,
    Consensus,
    Distribution,
    EventType,
    Forecast,
    LambdaDecision,
    LambdaPreset,
    LensName,
    LensOutput,
)

app = typer.Typer(add_completion=False)

AS_OF = date(2026, 8, 16)

# Deliberately plausible-but-obviously-synthetic. A round consensus and a DEMO
# ticker so nobody can mistake this for a real print.
CONSENSUS = Consensus(
    eps=2.40,
    revenue=44_000.0,
    basis=Basis.NON_GAAP,
    n_analysts=12,
    eps_high=2.61,
    eps_low=2.22,
    days_since_last_revision=18,
    as_of=AS_OF,
)

# The trailing int is how many claims the lens cited, and it is NOT decorative.
# The schematic sizes each conductor by citation count, so a fixture where every
# lens cites exactly the same three claims draws seven identical wires and hides
# the one thing that view exists to show. These counts are the realistic shape:
# Drivers cites a segment table, Guidance stands on two sentences and is still
# the strongest lens — which is the point, since the judge weighs by materiality
# and not by how many claims a lens managed to pile up.
LENSES: list[tuple[LensName, float | None, float, str, str | None, int]] = [
    (
        LensName.MECHANICAL,
        2.44,
        0.90,
        "FX +1.8% on a 58% international revenue base; calendar flat; share "
        "count 2,480m -> 2,468m from $1.4bn of buyback at $118. No model "
        "judgment — arithmetic only.",
        None,
        6,
    ),
    (
        LensName.GUIDANCE,
        2.52,
        0.78,
        "Guided $2.38-2.46 (midpoint $2.42). This company has landed at a "
        "shrunk position of 1.18 inside its own range over eight quarters — "
        "above the top end more often than not.",
        "The landing distribution is the load-bearing input and it is measured, "
        "not assumed: eight quarters, empirical-Bayes shrunk toward the sector.",
        2,
    ),
    (
        LensName.DRIVERS,
        2.47,
        0.62,
        "Datacentre units 1.72m x ASP $19,400 gives $33.4bn, plus $10.1bn "
        "across the remaining segments. Segments sum to the total.",
        "Unit build is disclosed at segment level, so the decomposition is not "
        "inferred.",
        11,
    ),
    (
        LensName.MARGINS,
        2.38,
        0.55,
        "Gross margin 73.2% against 74.1% prior on an unfavourable product mix "
        "shift; opex +6% sequentially on headcount; tax rate 16.5%.",
        "Mix is the whole argument and mix is the part most easily wrong.",
        8,
    ),
    (
        LensName.FORENSICS,
        2.35,
        0.44,
        "DSO went 46 to 53 days while revenue grew 12% — receivables are "
        "growing faster than sales. Stock-based compensation has been excluded "
        "for eleven consecutive quarters, which makes it a permanent cost "
        "below the line rather than an unusual item.",
        "The recurring exclusion is the stronger of the two findings: it moves "
        "what the reported number means, not just its level.",
        5,
    ),
    (
        LensName.PEER_READ,
        2.49,
        0.51,
        "Two same-quarter-end suppliers have reported. One guided datacentre "
        "content up 34% and supplies roughly 40% of this company's segment "
        "input — the transmission mechanism is specific rather than sectoral.",
        None,
        3,
    ),
]

DROPPED = {
    "macro": (
        "macro: no macro series were acquired for this sector, so the lens "
        "returned null rather than reasoning from general economic conditions"
    )
}

# The evidence store holds this many claims; the lens counts above draw from it.
N_CLAIMS = 24


def _cited(lens_index: int, count: int) -> list[str]:
    """`count` claim ids out of the store, overlapping between lenses.

    Overlap is the realistic shape and it matters: two lenses citing the same
    filed figure is normal, and it is not the same thing as two lenses agreeing
    because one read the other's output. Staggering the start keeps the sets
    distinct without pretending the store is partitioned.
    """
    start = lens_index * 4
    return [f"c{1 + (start + k) % N_CLAIMS}" for k in range(count)]


@app.command()
def main(out: Path = Path("out"), ticker: str = "DEMO") -> None:
    out.mkdir(parents=True, exist_ok=True)

    lenses = [
        LensOutput(
            lens=name,
            eps=eps,
            revenue=44_600.0 if eps else None,
            basis=Basis.NON_GAAP,
            reasoning=reasoning,
            claim_ids=_cited(i, cites),
            confidence=confidence,
            reconciled=True,
            thesis=thesis,
            counterargument=(
                "Most of this is already in the guided range, and the guide is "
                "three months old. Most material weakness: the effect is real "
                "but is likely a third of the claimed size."
                if thesis
                else None
            ),
            model_used=None if name is LensName.MECHANICAL else "claude-sonnet-5",
            input_tokens=0 if name is LensName.MECHANICAL else 18_400,
            output_tokens=0 if name is LensName.MECHANICAL else 720,
            latency_ms=2 if name is LensName.MECHANICAL else 7_800,
        )
        for i, (name, eps, confidence, reasoning, thesis, cites) in enumerate(LENSES)
    ]

    forecast = Forecast(
        ticker=ticker,
        period="2026Q3",
        as_of=AS_OF,
        eps_non_gaap=2.44,
        eps_gaap=None,
        revenue=44_600.0,
        distribution=Distribution(
            median=2.44,
            mean=2.45,
            quantiles={"0.1": 2.26, "0.25": 2.36, "0.5": 2.44, "0.75": 2.53, "0.9": 2.66},
            stdev=0.156,
            calibrated=False,
        ),
        consensus=CONSENSUS,
        lambda_decision=LambdaDecision(
            preset=LambdaPreset.SHRINK,
            value=0.20,
            n_analysts=12,
            dispersion=0.1625,
            consensus_stale=False,
            internal_disagreement=0.0271,
            comparability_flag=None,
            rationale=(
                "preset=shrink, fitted base beta=0.20; wide dispersion (16.3%), "
                "x1.4; lenses agree closely (2.7% CV), no damping applied"
            ),
        ),
        lenses=lenses,
        dropped_lenses=DROPPED,
        baseline_eps=2.4816,
        total_cost_usd=0.2837,
        total_input_tokens=112_800,
        total_output_tokens=5_240,
        wall_clock_ms=31_400,
    )

    (out / "results.json").write_text(
        json.dumps(
            {
                "forecast": forecast.model_dump(mode="json"),
                "trace": {
                    "synthetic": True,
                    "note": (
                        "SYNTHETIC FIXTURE — not a forecast. Generated by "
                        "tools/make_fixture.py for UI development and for a "
                        "deterministic `make verify` target. The real demo "
                        "fallback is a recorded run replayed through the same "
                        "code path."
                    ),
                    "judge_rationale": (
                        "Guidance carried the most weight: it is the company's "
                        "own statement about this quarter, quoted, and its "
                        "landing distribution is measured over eight quarters "
                        "rather than assumed. Forensics is the only case "
                        "arguing the other way and its recurring-exclusion "
                        "finding is real, but it changes what the number means "
                        "more than it changes the level. Four lenses clustering "
                        "near $2.45 earned nothing extra for clustering — they "
                        "read overlapping documents, so their agreement is "
                        "weak evidence. Width is set by the Margins/Forensics "
                        "disagreement on mix, and by the Macro lens being "
                        "absent rather than agreeing."
                    ),
                    "comparability": {
                        "flag": None,
                        "note": "no M&A, calendar or accounting change found",
                    },
                    "calibration": (
                        "NOT CALIBRATED: 0 backtest residuals available (need 25). "
                        "The interval is the judge's own, which is uncalibrated by "
                        "nature — do not read the 80% band as 80% coverage."
                    ),
                    "baseline": (
                        "DEMO median surprise +3.60% over 8 quarters, shrunk 52% "
                        "toward a peer median of +2.10% -> +3.40%"
                    ),
                    "citations": {"verified": 23, "failed": 1},
                    "evidence": {"claims": 24, "deduped": 3},
                },
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )

    # An event log with the same node ids the pipeline emits, so the live view
    # can be developed against it.
    events = EventLog(out / "events.ndjson")
    # kwargs, not payload= — `emit` collects **payload, so a dict named `payload`
    # would nest a second time and consumers would read undefined.
    events.emit(EventType.RUN_START, ticker=ticker, as_of=str(AS_OF))
    for node in ("A1_numbers", "A2_filings", "A3_industry", "A4_macro", "B_structure"):
        events.emit(EventType.NODE_START, node)
        events.emit(EventType.NODE_DONE, node, latency_ms=900)
    events.emit(EventType.CLAIM_ADDED, "B_structure", n=N_CLAIMS)
    for name, _, confidence, _, _, cites in LENSES:
        events.emit(EventType.NODE_START, f"C_{name.value}")
        events.emit(EventType.NODE_DONE, f"C_{name.value}",
                    latency_ms=7800, confidence=confidence, cited=cites)
    events.emit(EventType.NODE_START, "C_macro")
    events.emit(EventType.NODE_FAILED, "C_macro", error=DROPPED["macro"])
    for node in ("V1_reconcile", "D_champion", "E_judge", "V2_comparability",
                 "F_lambda", "V3_calibrate"):
        events.emit(EventType.NODE_START, node)
        events.emit(EventType.NODE_DONE, node, latency_ms=1200)
    events.emit(EventType.RUN_DONE, eps=2.44, cost_usd=0.2837)

    _write_eval(out)
    _write_portfolio(out)

    typer.echo(
        f"wrote {out}/results.json, {out}/events.ndjson, {out}/eval.json "
        f"and {out}/portfolio.json"
    )
    typer.secho(
        "SYNTHETIC — every file carries a synthetic flag and the UI shows a banner.",
        fg=typer.colors.YELLOW,
    )
    typer.secho(
        "For the agent roster, run: forecast agents --json out/agents.json "
        "(that one is real — it reads the prompt files).",
        fg=typer.colors.BLUE,
    )


def _write_eval(out: Path) -> None:
    """A synthetic eval payload for the method sheet.

    Built by running the REAL backtest harness over synthetic cases rather than
    by hand-writing plausible numbers. That matters: the summary, the skill curve
    and the information ratio all come out of `eval.backtest`, so if that code
    changes shape the fixture changes with it and the sheet cannot drift from the
    statistics it claims to display.
    """
    from datetime import timedelta

    from forecaster.eval.backtest import Case, run

    # A modest, deliberately unspectacular edge: mostly small beats with a few
    # misses, which is what the base rates actually look like.
    cases: list[Case] = []
    for i in range(140):
        consensus = 1.00 + (i % 17) * 0.11
        surprise = (0.045 if i % 5 else -0.03) + ((i % 7) - 3) * 0.004
        cases.append(
            Case(
                ticker=f"T{i % 12}",
                period=f"2025Q{(i % 4) + 1}",
                as_of=date(2025, 1, 15) + timedelta(days=i * 6),
                consensus_eps=round(consensus, 4),
                actual_eps=round(consensus * (1 + surprise), 4),
            )
        )

    # A forecaster that lands a little closer than the flat tilt on most names.
    def forecaster(case: Case) -> float:
        tilt = 0.031 if hash(case.period) % 5 else 0.0
        return case.consensus_eps * (1 + tilt)

    result = run(cases, forecaster=forecaster, baseline_tilt=0.02)

    # Reliability: deliberately imperfect. An 80% band covering 68% is the honest
    # first result, and showing it is the point of the diagram.
    calibration = [
        {"nominal": 0.1, "empirical": 0.07, "n": result.n},
        {"nominal": 0.25, "empirical": 0.19, "n": result.n},
        {"nominal": 0.5, "empirical": 0.44, "n": result.n},
        {"nominal": 0.75, "empirical": 0.66, "n": result.n},
        {"nominal": 0.9, "empirical": 0.83, "n": result.n},
    ]

    (out / "eval.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "note": (
                    "Generated by tools/make_fixture.py so the method sheet has "
                    "something to render. The statistics are computed by the real "
                    "eval.backtest harness, but over SYNTHETIC cases — they are "
                    "not a measured result. Replace by running "
                    "`forecast cases` then `forecast backtest`."
                ),
                "backtest": result.summary(),
                "skill_curve": result.skill_curve(),
                "calibration": calibration,
                # Two lenses earning nothing is the realistic outcome, and saying
                # so is worth more than an unfalsifiable win.
                "ablation": {
                    "guidance": 0.0184,
                    "forensics": 0.0071,
                    "mechanical": 0.0052,
                    "drivers": 0.0033,
                    "margins": 0.0009,
                    "peer_read": 0.0,
                    "macro": -0.0004,
                },
                "lambda": {
                    "buckets": {
                        "pooled": {
                            "beta": 0.183,
                            "n": 140,
                            "r_squared": 0.094,
                            "is_measured": True,
                        },
                        "thin/wide": {
                            "beta": 0.311,
                            "n": 38,
                            "r_squared": 0.142,
                            "is_measured": True,
                        },
                        "heavy/tight": {
                            "beta": 0.061,
                            "n": 44,
                            "r_squared": 0.038,
                            "is_measured": True,
                        },
                        "normal/tight": {
                            "beta": 0.183,
                            "n": 21,
                            "r_squared": 0.094,
                            "is_measured": False,
                        },
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


def _write_portfolio(out: Path) -> None:
    """Deviation budget across names, for the risk sheet.

    The shape a multi-company run would write: λ concentrated where consensus is
    structurally weakest and near zero on the heavily-covered names. That
    asymmetry IS the thesis, so it is worth being able to see it.
    """
    (out / "portfolio.json").write_text(
        json.dumps(
            [
                {"ticker": "MU", "lambda": 0.412, "n_analysts": 31,
                 "rationale": "wide dispersion, six quarters of large surprises"},
                {"ticker": "FDX", "lambda": 0.268, "n_analysts": 24,
                 "rationale": "two-sided surprise tails"},
                {"ticker": "DEMO", "lambda": 0.200, "n_analysts": 12,
                 "rationale": "wide dispersion, lenses agree"},
                {"ticker": "ADBE", "lambda": 0.074, "n_analysts": 38,
                 "rationale": "tight consensus, four of four small beats"},
                {"ticker": "NVDA", "lambda": 0.031, "n_analysts": 61,
                 "rationale": "61 analysts with segment models — shrink, and say so"},
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
