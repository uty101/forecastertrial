"""CLI. One command per thing you do on the day.

    forecast run      --ticker NVDA --as-of 2026-08-16 --preset shrink
    forecast backtest --quarters 200 --runs 5
    forecast sources  --ticker NVDA          # smoke test before anything else
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import structlog
import typer

from forecaster.config import settings
from forecaster.data.cache import Cache
from forecaster.data.loader import Loader
from forecaster.data.sec_source import SECSource
from forecaster.data.yfinance_source import YFinanceSource
from forecaster.events import EventLog
from forecaster.pipeline.a_acquire import acquire
from forecaster.schemas import EventType, LambdaPreset

app = typer.Typer(add_completion=False, help="Earnings forecasting agent")
log = structlog.get_logger()


def build_loader(read_only: bool = False) -> Loader:
    cache = Cache(settings.cache_dir, read_only=read_only)
    sources = [YFinanceSource(cache)]
    if settings.sec_identity:
        sources.append(SECSource(settings.sec_identity, cache))
    else:
        log.warning("sec_disabled", why="SEC_IDENTITY unset — you will get 403s")
    return Loader(sources)


@app.command()
def sources(ticker: str = "NVDA") -> None:
    """Smoke test every source from THIS machine. Run before anything else.

    Datacentre IPs get rate-limited far harder than laptops — find that out now,
    not on the 16th.
    """
    loader = build_loader()
    today = date.today()
    consensus = loader.consensus(ticker, today)
    typer.echo(f"consensus: {consensus}")
    typer.echo(f"actuals:   {bool(loader.actuals(ticker, '2026Q1', today))}")
    typer.echo(f"filings:   {bool(loader.filings(ticker, today, ['8-K', '10-Q']))}")
    typer.echo(json.dumps(loader.report(), indent=2, default=str))


@app.command()
def run(
    ticker: str = typer.Option(...),
    as_of: str = typer.Option(..., "--as-of"),
    period: str = "2026Q3",
    preset: LambdaPreset = LambdaPreset.SHRINK,
    from_cache: bool = typer.Option(False, help="fail rather than hit the network"),
    seed: int = 0,
    out: Path = Path("out/results.json"),
) -> None:
    """One forecast. Layers C-G are stubbed; A and B are live."""
    lock = date.fromisoformat(as_of)
    events = EventLog(settings.out_dir / "events.ndjson")
    events.emit(EventType.RUN_START, payload={"ticker": ticker, "as_of": as_of})

    loader = build_loader(read_only=from_cache)
    acquired = acquire(ticker, period, lock, loader, events)

    payload = {
        "ticker": ticker,
        "period": period,
        "as_of": as_of,
        "preset": preset.value,
        "seed": seed,
        "n_claims": len(acquired.claims),
        "consensus": acquired.consensus.model_dump(mode="json")
        if acquired.consensus
        else None,
        "budgets": acquired.budgets,
        "sources": loader.report(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True))
    events.emit(EventType.RUN_DONE, payload={"claims": len(acquired.claims)})
    typer.echo(f"wrote {out} — {len(acquired.claims)} claims")


@app.command()
def backtest(quarters: int = 200, runs: int = 5) -> None:
    """The gate. Everything is measured against the baseline this produces."""
    typer.echo(
        f"backtest over {quarters} firm-quarters, {runs} runs each — "
        "wire the case builder in Block 1"
    )


if __name__ == "__main__":
    app()
