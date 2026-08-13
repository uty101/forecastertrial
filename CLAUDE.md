# CLAUDE.md

Context for Claude Code. Read this before proposing changes.

---

## What this is

An autonomous earnings-forecasting agent, built for **Agents vs Wall Street** — a hackathon in London on **Sunday 16 August 2026, 10:00–19:30**. $10,000 across three awards: accuracy (scored after companies report), best agent architecture, and best aesthetics (both judged live in the room).

On the day we're handed a company and a data feed at 10am and have ~6 hours. **Almost everything must already exist.** The only genuinely new code written on the day is one `DataSource` adapter for the sponsor's feed. Everything else is tuning and presentation.

Full background is in `docs/`. `docs/MASTER-PLAN.md` is the entry point.

---

## The thesis — do not propose a design that contradicts this

Consensus is not a forecast. It is analysts' good analysis with a thumb on the scale:

- estimates are **walked down 3.0–4.2%** during the quarter, before any results
- **58–63%** of guiding companies guide *negative*
- **78%** of S&P 500 companies then beat that bar; aggregate surprise **+7.0%**

That's incentive, not analytical error — analysts beat a naive random walk by 245bp of price at exactly this horizon. So:

> **Reproduce the analysis. Strip the incentives. Then ask the one question no individual analyst can, because they *are* the consensus: where is consensus structurally weak?**

`forecast = consensus + λ · (own_estimate − consensus)`

**λ is fitted on backtest, never guessed**, and conditioned on regime (coverage count, dispersion, staleness, internal lens disagreement, comparability).

Corollary that matters: **shrinking to consensus on a 61-analyst mega-cap is the correct answer, not a failure.** Do not "improve" the system by making it deviate more.

---

## Invariants — breaking any of these is a bug, not a tradeoff

1. **Point-in-time.** Every `DataSource` method takes `as_of` and must not return anything *filed* after it. This includes restatements of historical periods. `assert_point_in_time()` raises; `Loader` never routes around a `PointInTimeViolation`. See `tests/test_point_in_time.py`.

2. **No number without provenance.** `Claim` cannot be constructed without a `Source` and a non-empty `verbatim_quote`. Model input cells refuse to exist without a claim (or an explicit note). `v1_reconcile.verify_citations` string-matches every quote against its source document. Never relax these to make something pass.

3. **Lenses are blind to each other.** They never share context. If they see each other's output they converge, and converging rebuilds consensus, which scores zero.

4. **The judge weighs by materiality, never by vote count.** Do not add averaging, plurality, or majority logic anywhere in aggregation. Six lenses agreeing on a weak signal must lose to one carrying the company's own guidance with a quote.

5. **Champion development runs before any comparison.** Each lens's case is argued *and argued against* before anything is ranked.

6. **The baseline appears on every chart.** `consensus × (1 + shrunk company surprise)`. It is not a strawman — it beats naive consensus comfortably. If the pipeline can't beat it, λ should be 0 and we say so.

7. **Robust statistics only.** Medians and MAD, winsorize before any mean. Never calibrate on a cap-weighted aggregate — FactSet's headline surprise went +39.3% → +12.6% on excluding one company.

8. **No API between the pipeline and the UI.** Python writes `out/*.json` and `out/events.ndjson`; Next.js polls them. No server, no ports. This also gives replay mode free — the demo fallback is a recorded event log through the identical code path, not a video.

---

## Architecture

```
A  SOURCES     SEC · yfinance · Exa · LSE · FRED · universe   adapters, point-in-time
B  ACQUIRE     numbers · series · filings · industry · macro · guidance
                                                           parallel, hard budgets
   dossier     out/acquired/<ticker>/<period>_<as_of>      the handover, on disk
C  STRUCTURE   evidence store                             deterministic
D  MODEL       3-statement model · ratio base             deterministic; reproduces
                                                          past quarters to measure
                                                          its own structural error
E  ANALYSE     7 lenses, blind to each other               parallel, shared cached prefix
V1 RECONCILE   arithmetic + citation verification          fail → drop the lens
F  CHALLENGE   argue each case, then argue against it      ×7 parallel
G  JUDGE       impact-weighted → a distribution            one expensive call
V2 COMPARABLE  M&A · accounting change · 53rd week         fires → λ collapses
H  POSITION    λ vs consensus, fitted, regime-conditioned
V3 CALIBRATE   bootstrap our own backtest residuals
I  OUTPUT      forecast + model + trace
```

**The nine lenses:** Mechanical (no LLM — FX, share count, net interest, calendar), Guidance, Drivers, Demand, Market, Margins, Forensics, Peer read, Macro.

Demand reads the value chain — a customer's capex budget IS this company's revenue, disclosed on a different calendar. Market splits growth into market growth and share change, which consensus forecasts as one number and almost never separates.

Model tiering: cheap for acquisition and extraction, mid for lenses and champion, **expensive for the judge — one call, highest leverage**. λ is mostly plain code.

---

## Current status

**End to end and running live. 427 tests, 15 agents.**

The whole chain executes: acquire → extract → structure → model → 9 lenses →
reconcile → champion → judge → comparability → λ → output, with the UI reading
`out/*.json`. A full live run on NVDA costs **$1.24** and takes ~9 minutes.

**THE GATE NUMBER EXISTS.** `forecast cases` on 122 tickers gives n=487
firm-quarters (adequately powered; the target is 350). Scored:

| | MAE |
|---|---|
| naive consensus | 0.2216 |
| **consensus × 1.02 — the baseline to beat** | **0.1868** |

Everything the pipeline produces is measured against 0.1868. Reproduce with
`forecast cases --tickers ... && forecast backtest`.

### What is still asserted rather than measured

- **λ.** `FITTED_BETA` still holds three placeholder numbers and
  `FITTED_BETA_MEASURED = False`. Fitting it needs `(consensus, own, actual)`
  triples, and `own` is the judge's output — so it needs a pipeline run per case.
  At $1.24 a run that is ~$600 for the full n=487 and ~$50 for a 40-case subset.
  This is a spend decision, not a technical one; the harness (`forecast fit`)
  is written and tested.
- **The lens abstention rate.** On the last live run 5 of 8 lenses returned no
  EPS or cited nothing. Some of that is honest — a lens with no evidence should
  abstain — but three lenses returning empty `claim_ids` is a prompt-adherence
  problem, not an evidence problem.

`docs/TASKS.md` is the live board. Update it as things land.

---

## Traps — these have already cost time, or will

**GAAP vs non-GAAP.** Consensus is non-GAAP. SEC XBRL is GAAP. The median DJIA gap was **31%** in one recent quarter. Every EPS figure must declare its `Basis`. Getting this wrong produces a systematic one-directional error that looks like bad modelling. `Forecast` carries both.

**`FITTED_BETA` in `h_lambda.py` holds three placeholder numbers.** They are meant to be the output of the Block 1 regression (`actual ~ α·consensus + β·own`). Until that runs, the thesis is asserted rather than measured. Do not treat them as tuned.

**Replay is not the pipeline.** `--dossier` skips acquisition entirely, so any bug in stage B is invisible to it. `industry` went unimported in `b_acquire` for as long as it did because every run during that period was a replay, and the crash only appears on a cold run. Before trusting a change to acquisition, run it once WITHOUT `--dossier`.

**Prompt caching is a prefix match, and a parallel fan-out defeats it.** Two separate bugs, both silent. The corpus must come BEFORE the per-prompt system text (otherwise every lens presents a different prefix), and the first lens must COMPLETE before the others start (otherwise there is no entry to read yet). Symptom of both: `cache_write` large, `cached_in` zero. Log them together — on the read alone it looks like caching was never configured.

**A free-form dict is the wrong shape to ask a model for.** `quantiles: dict[str, float]` came back empty on two consecutive live runs, with the numbers written into the rationale prose instead. Five named float fields, filled every time. Ask for named things.

**A pointer to a document is not a quote from it.** `SourceKind.FILING_INDEX` exists because SEC submissions-index claims ("8-K filed 2026-05-20, accession ...") were being string-matched against the document they point at, which fails by construction and dropped the one lens with no model in it.

**The Dockerfile base image digest is literally `PINME`.** Pin it.

**Units.** Millions vs thousands is the error that will actually bite. The reconciler's YoY sanity band is the only thing that catches it, because the arithmetic stays internally consistent.

**`int(p * n)` is not a percentile index.** It was, and `winsorize` silently did nothing. Correct is `int(p * (n - 1))`.

**Wald confidence intervals report zero width at p=1.0.** Use Wilson. Already fixed in `backtest.py`; don't reintroduce.

**yfinance `earnings_estimate` is not point-in-time.** For historical backtests use `earnings_history.epsEstimate`, which is consensus as it stood at that quarter's report date. Using the former for backtesting is look-ahead bias.

---

## Conventions

- **Prompts live in `llm/prompts/*.yaml`, versioned. Never inline in Python.** You will iterate a hundred times and need to know which version produced which backtest number.
- Every LLM response validated against a pydantic schema. **Fail closed** — never silently coerce.
- Retry with backoff on transient errors only; **fail fast on schema errors** (retrying malformed output mostly just costs money).
- Every stage independently runnable and independently cached, keyed on input hash.
- A lens that errors or fails reconciliation is **dropped, logged, and surfaced in the UI** — the judge is told it's missing. Never silently shrink the ensemble.
- Acquisition has hard budgets. When one is spent, **log what was skipped.** Silent truncation reads as "we covered everything."
- `make types` regenerates `ui/lib/types.ts` from the pydantic models. Run it after touching `schemas.py`.

---

## Commands

```bash
make setup                          # uv sync + npm install
make test                           # pytest + ruff
make run TICKER=NVDA ASOF=2026-08-16
make backtest                       # 200 quarters, 5 runs each
make verify                         # fixed quarter from cache, diffed vs golden — in CI
make ui                             # next build + serve
uv run forecast sources --ticker NVDA   # smoke test every data source
```

---

## Do this first

```bash
uv run forecast sources --ticker NVDA
```

Both data sources were written from documentation and have never touched the network. Everything downstream assumes a data shape that was inferred, not observed. Datacentre IPs get rate-limited far harder than laptops, so run it from the machine you'll demo on.

Then **Block 1, the gate**: build ~200 firm-quarter cases, verify the GAAP↔non-GAAP bridge by hand on 10 companies, and score `consensus × 1.02`. That number is what everything afterwards is measured against.

**Do not build LLM lenses before that number exists.**

---

## Working style for this repo

- Prefer deterministic code over an LLM call wherever the task is arithmetic. The Mechanical lens has no model in it and that is a feature.
- New behaviour needs a test that encodes the *failure mode*, not just the happy path. See `tests/test_reconciler.py`.
- Two bugs so far were caught by smoke tests rather than unit tests. After a change, run it on real-ish numbers and read the output.
- If the ablation shows a lens adds nothing, **say so and drop it.** An honest negative result is worth more here than a component that looks impressive.
