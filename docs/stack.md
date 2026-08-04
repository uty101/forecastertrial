# Stack — everything you need to build, front and back

Component inventory before any code. Two processes total: a Python pipeline that writes files, and a static frontend that reads them. Nothing talks over a network on the day.

---

## The shape

```
  pipeline (python)                          frontend (next.js, static)
  ────────────────────                       ──────────────────────────
  reads: sponsor feed, SEC, yfinance
  writes: out/events.ndjson    ──────────▶   polls every 250ms → live run view
          out/results.json     ──────────▶   forecast · reasoning trace · model
          out/backtest.json    ──────────▶   eval screens

  served by: python -m http.server (or next dev)
```

**Why files and not an API.** No server process to crash mid-demo, no ports, no CORS, no async lifecycle bugs at 18:40. The pipeline appends events; the UI polls a file. It also gives you **replay mode for free** — see the fallback note at the end.

---

## Backend — Python

### Core
| Package | Why |
|---|---|
| **Python 3.12** | |
| **uv** | env + lockfile. Faster than poetry and the lockfile is the reproducibility story. |
| **pydantic v2** | Every LLM response, every Claim, every model cell. Fail closed. |
| **pydantic-settings** | Config and secrets from env, typed. |
| **anthropic** | Messages API. Prompt caching for the corpus, Batch API for backtests. |
| **asyncio + httpx** | Fan the 7 lenses out in parallel. Don't thread it. |
| **typer** | CLI: `forecast run --ticker NVDA --as-of 2026-08-16` |
| **structlog** | JSON logs, one line per stage. |
| **tenacity** | Retry with backoff — transient only, fail fast on schema errors. |

### Data
| Package | Why |
|---|---|
| **edgartools** | SEC filings + XBRL. Saves 2–3h of tag-wrangling. `set_identity()` handles the User-Agent rule. |
| **yfinance** ≥1.5.2 | Consensus estimates, `eps_trend`, `eps_revisions`, earnings dates. Your consensus source. |
| **pandas + pyarrow** | Frames and the parquet cache. |
| **duckdb** | Query the SEC bulk Financial Statement Data Sets locally. Makes a 200-quarter backtest fast without hammering any API. |
| **httpx** | FRED, sponsor feed, anything else. |
| **diskcache** *(or a 20-line content-hash cache)* | Per-stage caching. Non-negotiable — you'll re-run the judge forty times. |

### Statistics
| Package | Why |
|---|---|
| **numpy, scipy** | Bootstrap, quantiles, MAD. |
| **statsmodels** | The λ regression (`actual ~ consensus + own`), constrained least squares for lens weights. |

No scikit-learn. You're fitting a two-variable regression and doing a bootstrap; sklearn is scope you don't need.

### The 3-statement model
Plain Python — **pydantic models plus a small dependency-graph evaluator** (topological sort over cells, each cell a value or a function of other cells). Roughly 200 lines. Do not reach for a spreadsheet engine.

Add **openpyxl** only to *export* the finished model to xlsx for the demo. Judges like being handed a real model file.

### Dev + ship
| | |
|---|---|
| **pytest, pytest-asyncio** | Unit tests on all deterministic code; golden-file test for `make verify`. |
| **ruff** | Lint + format, one tool. |
| **Docker** | `python:3.12-slim`, non-root, deps from the lockfile. |
| **GitHub Actions** | Run tests + `make verify` on every commit. This is most of the "production experience" signal. |

---

## Frontend — Next.js

### Core
| Package | Why |
|---|---|
| **Next.js 15**, app router, `output: 'export'` | Static export. No Node server on the day. |
| **TypeScript** | |
| **Tailwind CSS v4** | |
| **shadcn/ui** | Cards, tabs, accordion, tooltip, badge, dialog, scroll-area. Copy-in components, not a dependency you fight. |
| **Recharts** | Distribution, backtest line, calibration diagram, ablation bars. |
| **framer-motion** | Node state transitions on the live view. Nothing decorative. |
| **lucide-react** | Icons. |
| **clsx + tailwind-merge** | Conditional classes without the mess. |

### The live architecture view — build it as hand-authored SVG
**Not React Flow.** You already have the diagram as SVG; wrap each node in a React component that takes `status | tokens | latency` and drives fill, stroke and a pulse. You get exact control over layout, no library layout engine to fight, and a much smaller bundle. React Flow is for user-editable graphs — yours is fixed.

### Screens
| Route | Contents |
|---|---|
| `/` | **Live run.** Animated architecture, per-node tokens and latency, event ticker. |
| `/forecast` | Hero number, distribution, consensus marker, plain-English gap. |
| `/reasoning` | 7 lenses → thesis + counterargument, claims clickable to highlighted verbatim quote. Failed citations in red. |
| `/model` | The 3-statement model, rendered. Every cell shows its source on hover. |
| `/eval` | Backtest vs baseline, calibration reliability diagram, leave-one-out ablation, 5-run error bars. |

### Shared types
Generate TypeScript types from the pydantic models — `pydantic.json_schema()` → `json-schema-to-typescript`. One command in the Makefile. Stops the frontend and pipeline drifting, which they otherwise will.

---

## Repo tree

```
forecaster/
  pyproject.toml  uv.lock  Makefile  Dockerfile  README.md
  .github/workflows/ci.yml
  src/forecaster/
    cli.py
    config.py                 # pydantic-settings
    schemas.py                # Claim, LensOutput, Forecast — the contract
    data/
      protocol.py             # DataSource
      yfinance_source.py
      sec_source.py
      fred_source.py
      sponsor_source.py       # ← written on the day
      cache.py
    model/
      graph.py                # dependency-graph evaluator
      statements.py           # IS / BS / CF definitions
      bridge.py               # revenue → EPS
      export_xlsx.py
    pipeline/
      b_acquire.py
      c_structure.py
      e_lenses/               # mechanical · guidance · drivers · margins
                              # forensics · peer_read · macro
      v1_reconcile.py         # arithmetic + citations
      f_champion.py
      g_judge.py
      v2_comparability.py
      h_lambda.py
      v3_calibrate.py
    llm/
      client.py               # caching, cost ceiling, token accounting
      prompts/                # YAML, versioned — never inline in code
    eval/
      backtest.py  baseline.py  ablation.py  calibration.py
    events.py                 # append to out/events.ndjson
  tests/
    test_bridge.py  test_fx.py  test_shares.py  test_reconciler.py
    test_point_in_time.py     # asserts a post-as_of fetch is refused
    golden/                   # make verify fixtures
  ui/                         # Next.js
    app/{page,forecast,reasoning,model,eval}/
    components/architecture/  # one component per node
    lib/types.ts              # generated from pydantic
  out/                        # events.ndjson · results.json · backtest.json
  data/cache/                 # parquet
```

### Makefile — the whole interface
```
make setup      uv sync && cd ui && npm install
make types      pydantic schema → ui/lib/types.ts
make run        pipeline for one ticker
make backtest   N quarters, k runs
make verify     fixed quarter from cache, diff against golden  ← the one that matters
make ui         next build && serve out/
make test       pytest + ruff
```

---

## Set up in the next two days

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init forecaster && cd forecaster
uv add anthropic pydantic pydantic-settings typer structlog tenacity httpx \
       edgartools yfinance pandas pyarrow duckdb numpy scipy statsmodels \
       openpyxl diskcache
uv add --dev pytest pytest-asyncio ruff

npx create-next-app@latest ui --ts --tailwind --app --no-src-dir
cd ui && npx shadcn@latest init && npm i recharts framer-motion lucide-react
```

**Then, before writing anything:** run a five-line yfinance smoke test **from the machine you'll demo on**. Datacentre IPs get rate-limited far harder than laptops, and you want to find that out now.

---

## Two decisions worth locking now

**Prompts live in versioned YAML, never inline in Python.** You'll iterate on them a hundred times and you need to diff them, and to know which version produced which backtest result.

**The fallback is replay mode, not a video.** The UI already reads `events.ndjson`. Add a `?replay=<file>` param that streams a recorded run at original speed. Same code path, same UI, guaranteed to work with no network and no API keys. Record it on the 15th. If the live run dies on stage you change one URL and nobody notices — and it costs you about twenty minutes to build.
