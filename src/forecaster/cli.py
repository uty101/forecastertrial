"""CLI. One command per thing you do on the day.

    forecast sources  --ticker NVDA              # smoke test before anything else
    forecast agents                              # the roster, and what tier each runs on
    forecast run      --ticker NVDA --as-of 2026-08-16 --preset shrink
    forecast cases    --out out/cases.json       # Block 1: build the firm-quarters
    forecast backtest --runs 5                   # the gate
    forecast fit      --out out/lambda.json      # replaces FITTED_BETA with measurement
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import structlog
import typer

from forecaster.config import settings
from forecaster.data.cache import Cache
from forecaster.data.loader import Loader
from forecaster.data.sec_source import SECSource
from forecaster.data.universe import UNIVERSE, profile
from forecaster.data.yfinance_source import YFinanceSource
from forecaster.eval import backtest as backtest_mod
from forecaster.eval import cases as cases_mod
from forecaster.eval import fit as fit_mod
from forecaster.events import EventLog
from forecaster.llm.client import LLMClient
from forecaster.llm.prompt import load_all
from forecaster.model import grid
from forecaster.pipeline import b_acquire, d_model, dossier
from forecaster.pipeline import run as pipeline
from forecaster.schemas import LambdaPreset

app = typer.Typer(add_completion=False, help="Earnings forecasting agent")
log = structlog.get_logger()

# A Windows console defaults to cp1252, which has no λ — and λ is the name of the
# central quantity in this system, so it appears in almost every status line.
# `forecast status` crashed on it with a UnicodeEncodeError traceback. The demo
# runs from a terminal; a stage that works but cannot print its own output is
# indistinguishable from one that failed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def build_loader(read_only: bool = False) -> Loader:
    cache = Cache(settings.cache_dir, read_only=read_only)
    sources = [YFinanceSource(cache)]
    if settings.sec_identity:
        sources.append(SECSource(settings.sec_identity, cache))
    else:
        log.warning("sec_disabled", why="SEC_IDENTITY unset — you will get 403s")
    if settings.exa_api_key:
        from forecaster.data.exa_source import ExaSource

        sources.append(ExaSource(settings.exa_api_key, cache))
    if settings.lse_api_key and settings.lse_base_url:
        from forecaster.data.lse_source import LSESource

        sources.append(
            LSESource(settings.lse_api_key, settings.lse_base_url, cache)
        )
    else:
        log.info("news_disabled", why="EXA_API_KEY unset — no industry or company news")
    return Loader(sources)


def build_macro_source(read_only: bool = False):
    if not settings.fred_api_key:
        return None
    from forecaster.data.fred_source import FREDSource

    return FREDSource(settings.fred_api_key, Cache(settings.cache_dir, read_only))


# --------------------------------------------------------------------------- #


@app.command()
def sources(ticker: str = "NVDA") -> None:
    """Smoke test every source from THIS machine. Run before anything else.

    Datacentre IPs get rate-limited far harder than laptops — find that out now,
    not on the 16th.
    """
    loader = build_loader()
    today = date.today()

    consensus = loader.consensus(ticker, today)
    typer.echo(f"consensus:  {consensus}")
    typer.echo(f"actuals:    {bool(loader.actuals(ticker, '2026Q1', today))}")

    filings = loader.filings(ticker, today, ["8-K", "10-Q"])
    typer.echo(f"filings:    {len(filings) if filings else 0}")

    # The one most likely to be silently broken, and the one citation
    # verification depends on entirely.
    body = None
    if filings:
        for source in loader.sources:
            fetch = getattr(source, "get_document", None)
            if fetch:
                body = fetch(filings[0].source.uri)
                if body:
                    break
    typer.echo(f"doc text:   {len(body) if body else 0} chars")
    if not body:
        typer.secho(
            "  ^ no document text. Every prose citation will fail verification "
            "and every lens citing one will be dropped.",
            fg=typer.colors.RED,
        )

    macro = build_macro_source()
    typer.echo(f"macro:      {'FRED configured' if macro else 'FRED_API_KEY unset'}")
    typer.echo(f"llm:        {'key set' if settings.anthropic_api_key else 'NO API KEY'}")
    typer.echo(json.dumps(loader.report(), indent=2, default=str))


AGENT_LAYERS = {
    "extract_guidance": "B  acquire",
    "lens_guidance": "E  analyse",
    "lens_drivers": "E  analyse",
    "lens_margins": "E  analyse",
    "lens_forensics": "E  analyse",
    "lens_peer_read": "E  analyse",
    "lens_macro": "E  analyse",
    "lens_market": "E  analyse",
    "lens_demand": "E  analyse",
    "champion": "F  challenge",
    "judge": "G  judge",
    "comparability": "V2 comparability",
}

# The Mechanical lens has no prompt file, because it has no model. It still
# belongs on the roster — it is the agent the whole determinism argument rests on.
MECHANICAL = {
    "id": "mechanical",
    "layer": "E  analyse",
    "tier": "none",
    "version": None,
    "model": "pure code — cannot hallucinate",
    "description": (
        "FX translation, diluted share count, net interest and calendar effects. "
        "Four things that move a quarterly EPS number, are fully disclosed, are "
        "pure arithmetic, and change after consensus is set."
    ),
}


@app.command()
def agents(
    json_out: Path | None = typer.Option(
        None, "--json", help="also write the roster as JSON for the UI"
    ),
) -> None:
    """The roster: every agent, the layer it sits in, and the tier it runs on.

    Read from the prompt files rather than a hand-kept list, so it cannot drift
    from what actually runs. Model tiering is a cost decision — cheap for
    extraction, mid for the lenses and the advocate, one expensive call for the
    judge — and printing it from source keeps that claim honest.
    """
    prompts = load_all()
    tier_model = {
        "cheap": settings.model_cheap,
        "mid": settings.model_mid,
        "deep": settings.model_deep,
    }

    typer.echo(f"{'agent':20} {'layer':18} {'tier':6} {'v':>3}  model")
    typer.echo("-" * 86)
    typer.echo(
        f"{'mechanical':20} {'E  analyse':18} {'none':6} {'-':>3}  "
        "pure code — cannot hallucinate"
    )
    for name in sorted(prompts, key=lambda n: (AGENT_LAYERS.get(n, "Z"), n)):
        prompt = prompts[name]
        typer.echo(
            f"{name:20} {AGENT_LAYERS.get(name, '?'):18} {prompt.model_tier:6} "
            f"{prompt.version:>3}  {tier_model[prompt.model_tier]}"
        )
    typer.echo("-" * 86)
    # `len(prompts)`, not `len(prompts) + 1`. The mechanical row is printed above
    # because it sits in layer C alongside the six lenses that are agents, but it
    # has no prompt and no model in it and counting it as an agent destroys the
    # only distinction this table exists to make. See
    # test_agent_count_matches_every_surface_that_states_it.
    typer.echo(
        f"{len(prompts)} agents — one prompt file each. "
        f"1 row above is not an agent (mechanical: pure code). "
        f"Prepared companies: {len(UNIVERSE)}"
    )

    if json_out is not None:
        rows = [MECHANICAL] + [
            {
                "id": name,
                "layer": AGENT_LAYERS.get(name, "?"),
                "tier": prompts[name].model_tier,
                "version": prompts[name].version,
                "model": tier_model[prompts[name].model_tier],
                # The prompt's own description, so the roster sheet and the prompt
                # cannot disagree about what an agent is for.
                "description": " ".join(prompts[name].description.split()),
            }
            for name in sorted(prompts, key=lambda n: (AGENT_LAYERS.get(n, "Z"), n))
        ]
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(
                {
                    "agents": rows,
                    "tiers": tier_model,
                    "prepared_companies": len(UNIVERSE),
                },
                indent=2,
                sort_keys=True,
            )
        )
        typer.echo(f"wrote {json_out}")


@app.command()
def ui(
    port: int = typer.Option(4321, help="deliberately not 3000 — that collides"),
    build: bool = typer.Option(True, help="run the Next static export first"),
    fixture: bool = typer.Option(
        False, help="generate the labelled synthetic run before serving"
    ),
) -> None:
    """Build, stage and serve the UI. Refuses an occupied port and says who has it.

    One command because `make` is not installed everywhere, and a flow that only
    works on a machine with GNU make is a flow that fails on the day.
    """
    from forecaster.tools import serve as serve_mod

    if fixture:
        from forecaster.tools import make_fixture
        from forecaster.tools import status as status_mod

        make_fixture.main(Path("out"))
        agents(json_out=Path("out/agents.json"))
        status_mod.main(Path("out/build.json"))

    serve_mod.serve(port=port, build=build)


@app.command()
def status(
    json_out: Path | None = typer.Option(
        None, "--json", help="write the status board as JSON for the UI"
    ),
) -> None:
    """What is built, what is measured, and what is still asserted.

    Derived from the repo — module imports, test coverage, the golden file, the
    case set, and whether `FITTED_BETA_MEASURED` is still False. A checklist in a
    markdown file rots the moment someone lands a change without editing it.

    The distinction that matters is BUILT versus MEASURED. A board where every
    component is green and every gate is red is a system that has been built and
    never tested against reality.
    """
    from forecaster.tools import status as status_mod

    result = status_mod.main(json_out)
    totals = result.totals

    typer.echo(
        f"components  {totals['built']} built · {totals['partial']} partial · "
        f"{totals['missing']} missing   ({totals['components']} total)"
    )
    typer.echo(f"tests       {totals['tests']}")
    typer.echo(
        f"gates       {totals['gates_passed']} of {totals['gates_total']} passed"
    )
    typer.echo("")

    for gate in result.gates:
        mark = "PASS" if gate["passed"] else "FAIL"
        colour = typer.colors.GREEN if gate["passed"] else typer.colors.YELLOW
        typer.secho(f"  [{mark}] {gate['label']}", fg=colour)
        typer.echo(f"         {gate['detail']}")

    partial = [c for c in result.components if c.state == status_mod.PARTIAL]
    if partial:
        typer.echo("")
        typer.secho(
            f"  {len(partial)} component(s) have no test encoding their failure "
            "modes:",
            fg=typer.colors.YELLOW,
        )
        for component in partial:
            typer.echo(f"         {component.label}")

    if json_out is not None:
        typer.echo(f"\nwrote {json_out}")


@app.command()
def acquire(
    ticker: str = typer.Option(...),
    as_of: str = typer.Option(..., "--as-of"),
    period: str = "2026Q3",
    extract_guidance: bool = typer.Option(
        True, help="run the guidance extractor (the only step that costs money)"
    ),
    from_cache: bool = typer.Option(False, help="fail rather than hit the network"),
    root: Path = Path("out/acquired"),
) -> None:
    """Stage 2 only — gather everything and write it to a dossier.

    Stops at the boundary on purpose. On the day this runs first, you read what
    came back, and only then spend model tokens on seven lenses and a judge. A
    corpus holding the wrong company's filings is cheap to notice here and
    expensive to notice after the analysis has run on it.
    """
    lock = date.fromisoformat(as_of)
    events = EventLog(settings.out_dir / "events.ndjson")
    cache = Cache(settings.cache_dir, read_only=from_cache)
    loader = build_loader(read_only=from_cache)

    acquired = b_acquire.acquire(
        ticker, period, lock, loader, events,
        macro_source=build_macro_source(read_only=from_cache),
    )

    guides: list = []
    rejections: list[str] = []
    if extract_guidance:
        guides, guide_claims, rejections = pipeline._extract_guidance(
            LLMClient(cache=cache, settings=settings), ticker, acquired, events
        )
        acquired.claims.extend(guide_claims)

    path = dossier.write(
        acquired, ticker, period, lock,
        guides=guides, rejections=rejections,
        provenance=loader.report(), root=root,
    )

    counts = {
        "claims": len(acquired.claims),
        "documents": len(acquired.documents),
        "guides": len(guides),
        "rejected": len(rejections),
        "quarters": acquired.history.n_quarters() if acquired.history else 0,
        "price_bars": len(acquired.prices or []),
    }
    typer.echo(f"wrote {path}")
    for key, value in counts.items():
        typer.echo(f"  {key:12s} {value}")
    skipped = [s for b in acquired.budgets.values() for s in b.get("skipped", [])]
    if skipped:
        # Never silent: a budget that ran out has to be visible here, not only
        # in a log line that scrolled past.
        typer.echo(f"  skipped      {len(skipped)}")
        for item in skipped[:8]:
            typer.echo(f"    - {item[:96]}")


@app.command()
def model(
    dossier_path: Path = typer.Option(..., "--dossier", help="a dossier directory"),
    out: Path = Path("out/model.json"),
    shares: float | None = typer.Option(
        None, help="diluted share count, for multi-class issuers XBRL omits"
    ),
) -> None:
    """Stage 4 only — build the three-statement model from a dossier.

    Independently runnable and free: no network, no API key, no model call. Run
    it against a dossier and read the statements before spending anything on
    seven lenses and a judge.

    The number worth reading is the reproduction error. Each past quarter is
    modelled from its OWN reported revenue — the one input a forecast would have
    had to supply — so what comes back is the model's structural error rather
    than any lens's forecasting error. A model that cannot reproduce a quarter
    whose revenue it was handed cannot project one.
    """
    acquired, _, manifest = dossier.read(dossier_path)
    if acquired.history is None:
        typer.secho("this dossier carries no history", fg=typer.colors.RED)
        raise typer.Exit(1)

    # The 10-year Treasury is the risk-free leg of the DCF's discount rate, and
    # it is the one input in that build-up that can be measured rather than
    # assumed. Without FRED the model says so instead of quietly standing one in.
    risk_free = None
    macro = build_macro_source()
    if macro is not None:
        lock = date.fromisoformat(manifest["as_of"])
        series = macro.get_macro(["DGS10"], lock)
        points = (series or {}).get("DGS10") or []
        if points:
            risk_free = points[-1].value / 100.0

    result = d_model.build(
        acquired.history, prices=acquired.prices, shares_open=shares,
        risk_free=risk_free,
    )

    payload = d_model.to_json(result)
    payload["ticker"] = manifest.get("ticker", result.ticker)
    # The reported history laid out as three statements — quarterly back to the
    # first filing, and the same data rolled into fiscal years. Both, because
    # commingling them in one table is how the SUM(Q1:Q4) rule gets applied to a
    # balance sheet.
    payload["grids"] = {
        "quarter": grid.to_json(grid.build(acquired.history, "quarter")),
        "annual": grid.to_json(
            grid.build(acquired.history, "annual", projected=result.projected)
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    # Compact, not indented. The UI fetches this whole file on page load and
    # indentation doubled it to a megabyte;  already prints the
    # human-readable version to the terminal.
    out.write_text(
        json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8"
    )

    typer.echo(d_model.to_block(result))
    typer.echo(f"\nwrote {out}")


@app.command()
def run(
    ticker: str = typer.Option(...),
    as_of: str = typer.Option(..., "--as-of"),
    period: str = "2026Q3",
    preset: LambdaPreset = LambdaPreset.SHRINK,
    tiny_tilt: bool = typer.Option(False, help="pure win-rate metric: direction only"),
    from_cache: bool = typer.Option(False, help="fail rather than hit the network"),
    run_index: int = 0,
    dossier_path: Path | None = typer.Option(
        None, "--dossier",
        help="start from a recorded acquisition instead of re-fetching",
    ),
    out: Path = Path("out/results.json"),
) -> None:
    """One forecast, A through G.

    With --dossier the run starts from a recorded acquisition: no network, no
    extraction call, the same evidence byte for byte. That is what makes prompt
    iteration affordable and what makes a comparison between two prompt
    versions measure the prompt rather than a corpus that moved underneath it.
    """
    lock = date.fromisoformat(as_of)
    events = EventLog(settings.out_dir / "events.ndjson")
    cache = Cache(settings.cache_dir, read_only=from_cache)

    result = pipeline.forecast(
        pipeline.RunConfig(
            ticker=ticker,
            period=period,
            as_of=lock,
            preset=preset,
            tiny_tilt=tiny_tilt,
            run_index=run_index,
            sector=profile(ticker).sector,
        ),
        loader=build_loader(read_only=from_cache),
        client=LLMClient(cache=cache, settings=settings),
        events=events,
        dossier_path=dossier_path,
    )

    payload = {
        "forecast": result.forecast.model_dump(mode="json"),
        "trace": result.trace,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True))

    forecast = result.forecast
    typer.echo(f"\n{ticker} {period}   as of {as_of}   preset={preset.value}")
    typer.echo(f"  forecast   {forecast.eps_non_gaap:.4f}")
    typer.echo(f"  consensus  {forecast.consensus.eps:.4f}")
    typer.echo(f"  baseline   {forecast.baseline_eps:.4f}")
    typer.echo(f"  lambda     {forecast.lambda_decision.value:.3f}")
    typer.echo(f"  vs Street  {forecast.surprise_vs_consensus:+.2%}")
    typer.echo(
        f"  lenses     {len(forecast.lenses)} kept, "
        f"{len(forecast.droppee_lenses)} dropped"
    )
    typer.echo(f"  cost       ${forecast.total_cost_usd:.4f}")
    typer.echo(f"\nwrote {out}")


@app.command()
def cases(
    tickers: str = typer.Option("", help="comma-separated; defaults to the universe"),
    quarters: int = 8,
    out: Path = Path("out/cases.json"),
) -> None:
    """Block 1: build the firm-quarter cases everything else is measured against.

    Nothing downstream means anything until this exists and `consensus × 1.02`
    has been scored against it.
    """
    universe = [t.strip().upper() for t in tickers.split(",") if t.strip()] or list(
        UNIVERSE
    )
    built = cases_mod.build(universe, Cache(settings.cache_dir), quarters)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "summary": built.summary(),
                "cases": [
                    {
                        "ticker": c.ticker,
                        "period": c.period,
                        "as_of": c.as_of.isoformat(),
                        "consensus_eps": c.consensus_eps,
                        "actual_eps": c.actual_eps,
                    }
                    for c in built.cases
                ],
                "rejected": built.rejected,
            },
            indent=2,
            sort_keys=True,
        )
    )
    typer.echo(json.dumps(built.summary(), indent=2))
    typer.echo(f"\nwrote {out}")


@app.command()
def backtest(
    cases_file: Path = Path("out/cases.json"),
    tilt: float = typer.Option(0.02, help="the baseline's flat tilt"),
    runs: int = 1,
) -> None:
    """THE GATE. Score the baseline. Every later number is measured against this.

    Deliberately scores `consensus` and `consensus × (1 + tilt)` only — no
    pipeline, no model calls. If the baseline number does not exist first, a
    pipeline result has nothing to be compared to and cannot be interpreted.
    """
    if not cases_file.exists():
        typer.secho(
            f"{cases_file} not found — run `forecast cases` first. "
            "There is no point scoring a pipeline before the baseline exists.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    payload = json.loads(cases_file.read_text())
    loaded = [
        backtest_mod.Case(
            ticker=row["ticker"],
            period=row["period"],
            as_of=date.fromisoformat(row["as_of"]),
            consensus_eps=row["consensus_eps"],
            actual_eps=row["actual_eps"],
        )
        for row in payload["cases"]
    ]

    result = backtest_mod.run(
        loaded,
        forecaster=lambda c: c.consensus_eps,
        baseline_tilt=tilt,
        runs_per_case=runs,
    )
    summary = result.summary()
    typer.echo(json.dumps(summary, indent=2))
    typer.echo(
        f"\nTHE NUMBER TO BEAT: consensus x {1 + tilt:.2f} scores "
        f"MAE {summary['mae_baseline']:.4f} on n={summary['n']}."
    )
    typer.echo(f"Naive consensus scores MAE {summary['mae_consensus']:.4f}.")
    if summary["underpowered"]:
        typer.secho(f"\n{summary['power_note']}", fg=typer.colors.YELLOW)


@app.command()
def fit(
    observations_file: Path = Path("out/observations.json"),
    out: Path = Path("out/lambda.json"),
) -> None:
    """Fit β on the backtest and replace the FITTED_BETA placeholders.

    Until this runs, the thesis is asserted rather than measured — which is
    precisely the distinction this repo is built around.
    """
    if not observations_file.exists():
        typer.secho(
            f"{observations_file} not found. Produce it by running the pipeline "
            "across the case set and recording (consensus, own, actual) per "
            "firm-quarter. Fitting β on anything less is guessing with a "
            "regression attached.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    rows = json.loads(observations_file.read_text())
    observations = [
        fit_mod.Observation(
            ticker=r["ticker"], period=r["period"], consensus=r["consensus"],
            own=r["own"], actual=r["actual"],
        )
        for r in rows
    ]
    report = fit_mod.report(fit_mod.fit_by_regime(observations))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    typer.echo(json.dumps(report, indent=2))
    typer.echo(f"\nwrote {out} — copy these into h_lambda.FITTED_BETA")


if __name__ == "__main__":
    app()
