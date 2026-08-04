"""Acquisition's output as an artifact on disk, not a value in memory.

Stage 2 gathers everything a forecast needs and hands it to stage 3 inside one
process. That works, and it costs three things worth having:

**`CLAUDE.md` asks for it.** "Every stage independently runnable and
independently cached." Acquisition was neither — you could not run it, look at
what came back, and then decide whether to run the expensive part.

**It is the wrong order for the day.** Acquire at 10:05, read the dossier, then
spend model tokens. A corpus with the wrong company's filings in it is cheap to
notice now and expensive to notice after seven lenses and a judge have run on it.

**The UI reads files.** There is no API between the pipeline and the UI by
design, so an artifact on disk is the interface.

Two decisions here are deliberate rather than incidental:

Documents are stored VERBATIM, one file each. `verify_citations` string-matches
every prose quote against its source, so reformatting or truncating on the way to
disk would silently break every citation that depends on it.

Timing is excluded. The budget reports carry `elapsed_s`, which differs on every
run — persisting it would make two dossiers of identical data compare unequal,
and `make verify` exists precisely to compare things byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import structlog

from forecaster.data.history import History, Observation
from forecaster.data.prices import PriceBar
from forecaster.pipeline.b_acquire import Acquired
from forecaster.schemas import Claim, Consensus, Guidance

log = structlog.get_logger()

ROOT = Path("out/acquired")


def slug(ticker: str, period: str, as_of: date) -> str:
    return f"{ticker.upper()}/{period}_{as_of.isoformat()}"


# --------------------------------------------------------------------------- #
# write
# --------------------------------------------------------------------------- #


def write(
    acquired: Acquired,
    ticker: str,
    period: str,
    as_of: date,
    guides: list[Guidance] | None = None,
    rejections: list[str] | None = None,
    provenance: dict | None = None,
    root: Path | str = ROOT,
) -> Path:
    """Write the dossier and return its directory."""
    out = Path(root) / slug(ticker, period, as_of)
    (out / "documents").mkdir(parents=True, exist_ok=True)

    index: dict[str, str] = {}
    for uri, body in sorted(acquired.documents.items()):
        name = hashlib.sha1(uri.encode()).hexdigest()[:16]
        (out / "documents" / f"{name}.txt").write_text(body, encoding="utf-8")
        index[name] = uri
    _dump(out / "documents" / "index.json", index)

    _dump(out / "claims.json", [c.model_dump(mode="json") for c in acquired.claims])
    _dump(
        out / "guidance.json",
        {
            "guides": [g.model_dump(mode="json") for g in (guides or [])],
            # Rejections are not an error list to swallow. A high rate means the
            # extractor is paraphrasing, which is worth knowing BEFORE the
            # forecast rests on it.
            "rejected": list(rejections or []),
        },
    )
    if acquired.history is not None:
        _dump(out / "history.json", _history_to_json(acquired.history))
    if acquired.prices:
        _dump(out / "prices.json", [_bar_to_json(b) for b in acquired.prices])

    consensus = acquired.consensus
    _dump(
        out / "manifest.json",
        {
            "ticker": ticker,
            "period": period,
            "as_of": as_of.isoformat(),
            "sector": acquired.sector,
            "prepared": acquired.prepared,
            "consensus": consensus.model_dump(mode="json")
            if isinstance(consensus, Consensus)
            else None,
            "counts": {
                "claims": len(acquired.claims),
                "documents": len(acquired.documents),
                "guides": len(guides or []),
                "quarters": acquired.history.n_quarters() if acquired.history else 0,
                "price_bars": len(acquired.prices or []),
            },
            # What we did NOT get, as prominently as what we did. Silent
            # truncation reads as "we covered everything".
            "budgets": {k: _strip_timing(v) for k, v in acquired.budgets.items()},
            "provenance": provenance or {},
            "blocks": {
                "prior_year": acquired.prior_year_block,
                "peers": acquired.peer_block,
                "macro": acquired.macro_block,
                "drivers": acquired.driver_block,
            },
        },
    )
    log.info(
        "dossier_written",
        path=str(out),
        claims=len(acquired.claims),
        documents=len(acquired.documents),
        guides=len(guides or []),
    )
    return out


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #


def read(path: Path | str) -> tuple[Acquired, list[Guidance], dict]:
    """Rebuild what acquisition produced. Returns (acquired, guides, manifest)."""
    root = Path(path)
    manifest = _load(root / "manifest.json")

    index = _load(root / "documents" / "index.json")
    documents = {
        uri: (root / "documents" / f"{name}.txt").read_text(encoding="utf-8")
        for name, uri in index.items()
    }

    acquired = Acquired(
        claims=[Claim(**row) for row in _load(root / "claims.json")],
        documents=documents,
        consensus=(
            Consensus(**manifest["consensus"]) if manifest.get("consensus") else None
        ),
        budgets=manifest.get("budgets", {}),
        sector=manifest.get("sector", "unknown"),
        prepared=bool(manifest.get("prepared")),
        prior_year_block=manifest.get("blocks", {}).get("prior_year", ""),
        peer_block=manifest.get("blocks", {}).get("peers", ""),
        macro_block=manifest.get("blocks", {}).get("macro", ""),
        driver_block=manifest.get("blocks", {}).get("drivers", ""),
    )

    history_path = root / "history.json"
    if history_path.exists():
        acquired.history = _history_from_json(_load(history_path))
    prices_path = root / "prices.json"
    if prices_path.exists():
        acquired.prices = [_bar_from_json(r) for r in _load(prices_path)]

    guides = [Guidance(**g) for g in _load(root / "guidance.json").get("guides", [])]
    return acquired, guides, manifest


# --------------------------------------------------------------------------- #


def _dump(path: Path, payload: Any) -> None:
    # sort_keys so two dossiers of the same data are byte-identical.
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_timing(report: dict) -> dict:
    """Everything except wall-clock, which differs on every run."""
    return {k: v for k, v in report.items() if k != "elapsed_s"}


def _history_to_json(history: History) -> dict:
    return {
        "ticker": history.ticker,
        "as_of": history.as_of.isoformat(),
        "cik": history.cik,
        "series": {k: [_obs_to_json(o) for o in v] for k, v in history.series.items()},
        "variants": {
            k: [_obs_to_json(o) for o in v] for k, v in history.variants.items()
        },
        "annual_gaps": {
            item: {str(fy): list(pair) for fy, pair in years.items()}
            for item, years in history.annual_gaps.items()
        },
    }


def _history_from_json(payload: dict) -> History:
    return History(
        ticker=payload["ticker"],
        as_of=date.fromisoformat(payload["as_of"]),
        series={k: [_obs_from_json(o) for o in v]
                for k, v in payload.get("series", {}).items()},
        cik=payload.get("cik", ""),
        variants={k: [_obs_from_json(o) for o in v]
                  for k, v in payload.get("variants", {}).items()},
        annual_gaps={
            item: {int(fy): tuple(pair) for fy, pair in years.items()}
            for item, years in payload.get("annual_gaps", {}).items()
        },
    )


def _obs_to_json(o: Observation) -> dict:
    row = asdict(o)
    row["period_end"] = o.period_end.isoformat()
    row["filed"] = o.filed.isoformat()
    return row


def _obs_from_json(row: dict) -> Observation:
    return Observation(
        **{**row,
           "period_end": date.fromisoformat(row["period_end"]),
           "filed": date.fromisoformat(row["filed"])}
    )


def _bar_to_json(b: PriceBar) -> dict:
    row = asdict(b)
    row["date"] = b.date.isoformat()
    return row


def _bar_from_json(row: dict) -> PriceBar:
    return PriceBar(**{**row, "date": date.fromisoformat(row["date"])})
