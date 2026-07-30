# forecaster

An earnings-forecasting agent that knows when to disagree with Wall Street — and, more often, when not to.

Built for **Agents vs Wall Street**, London, 16 August 2026.

---

## The thesis

Consensus is not a forecast. It is analysts' good analysis with a thumb on the scale:

- estimates are **walked down 3.0–4.2%** during the quarter, before any results
- **58–63%** of guiding companies guide *negative*
- **78%** of S&P 500 companies then beat the bar that gets set; aggregate surprise **+7.0%**

None of that is analytical error — analysts beat a naive random walk by 245bp of price at exactly this horizon. It's incentive: management access, career risk from a visible miss, herding, reluctance to publish an outlier.

So this system reproduces the analysis and strips the incentives, then adds the one question no individual analyst can ask, because they *are* the consensus:

> **Where is consensus structurally weak, and how far is it worth deviating?**

`forecast = consensus + λ · (own_estimate − consensus)`

Everything upstream of `f_lambda` produces an estimate. λ decides how much to trust it against sixty-one analysts with segment-level models. That separation is the point.

**The corollary that matters:** shrinking hard to consensus on a well-covered mega-cap is the *correct* answer, not a failure to have a view.

---

## Quick start

Everything runs through `uv` and `npm`. **There is no `make` dependency** — the
Makefile is a convenience for machines that have it, and every target has a
direct equivalent below.

```bash
uv sync                                  # python deps
cd ui && npm install && cd ..            # ui deps
cp .env.example .env                     # ANTHROPIC_API_KEY, SEC_IDENTITY, FRED_API_KEY

uv run pytest -q && uv run ruff check .  # tests + lint

uv run forecast sources --ticker NVDA    # smoke test every source FIRST
uv run forecast agents                   # the roster, printed from the prompts
uv run forecast status                   # what is built, what is only asserted

uv run forecast ui --fixture             # build, stage, serve → :4321
uv run forecast run --ticker NVDA --as-of 2026-08-16
```

`forecast ui` **refuses to start on an occupied port and names what is already
there.** Not 3000 by default, because that collides with every other front-end
project on a developer machine — and a collision shows up as "the UI is broken"
rather than as "something else is on that port".

**The home screen is the instrument.** `/` is the live signal-flow schematic,
polling `out/events.ndjson` four times a second: parts light as they run, tokens
and latency print on the part that spent them, and clicking any part says what it
is and whether a test covers it. For a second screen, open `/` in another browser
window — it is the same page and the same poll, so there is nothing to keep in
sync.

There used to be a separate `monitor.html` doing this in its own window: a second
implementation of the same diagram. It diverged the moment the app was
redesigned, and opened a window that looked like a different product. One
implementation now.

**Determinism:**

```bash
uv run python -m forecaster.tools.make_fixture --out out
uv run python -m forecaster.tools.diff_golden out/results.json tests/golden/fixture.json
```

Same command runs in CI on every commit, alongside a check that `ui/lib/types.ts` still matches the pydantic schemas it was generated from. It demonstrates reproducibility, point-in-time correctness and test discipline at once — which matters because OpenStocks' verified tier means *they* execute your agent, in their environment.

---

## Architecture

```
A  ACQUIRE     numbers · filings+text · industry · macro   parallel, hard budgets
B  STRUCTURE   3-statement model · evidence store          deterministic
C  ANALYSE     7 lenses, blind to each other               parallel, shared cached prefix
V1 RECONCILE   arithmetic + citation verification          fail → drop the lens
D  CHALLENGE   argue each case, then argue against it      ×7 parallel
E  JUDGE       impact-weighted, never vote-weighted        one expensive call → a range
V2 COMPARABLE  M&A · accounting change · 53rd week         fires → λ collapses
F  POSITION    λ vs consensus, fitted and conditioned
V3 CALIBRATE   bootstrap our own backtest residuals
G  OUTPUT      forecast + model + trace
```

### Ten agents, and one component on this list that isn't one

`uv run forecast agents` prints this from the prompt files themselves, so it cannot drift from what actually runs.

**An agent here means one thing: a component with a versioned prompt in `llm/prompts/`.** By that definition there are ten of them, and it is checkable — `ls src/forecaster/llm/prompts/*.yaml | wc -l`. The Mechanical lens is on the roster below because it sits in layer C alongside the six that are agents, but it has no prompt and no model in it. It is arithmetic. That is the point of it, and calling it an eleventh agent would blur the only distinction on this page worth making.

The same split is drawn everywhere a part appears, in the hue of what it is: violet for an agent, rose for the one deep-tier call, green for deterministic code, cyan for a data fetcher. Every stage that can hallucinate is checked by one that cannot.

| Agent | Layer | Tier | What makes it different |
|---|---|---|---|
| **Mechanical** | C | **no model** | FX, share count, net interest, calendar. Pure arithmetic that moves *after* consensus is set. Cannot hallucinate. |
| **Guidance** | C | mid | The guide, plus where this company historically lands *inside its own range*. Everyone reads the first; almost nobody builds the second. |
| **Drivers** | C | mid | Units × ASP, subs × ARPU, backlog conversion. Forecasts the drivers and multiplies, rather than extrapolating revenue. |
| **Margins** | C | mid | Revenue → EPS. Mix is the argument; a margin model that ignores mix is wrong in the same direction every quarter. |
| **Forensics** | C | mid | Reads as an auditor. Accruals vs cash, DSO, and **changes in the non-GAAP exclusion mix** — which moves what the number *means*. |
| **Peer read** | C | mid | Who already reported this cycle, and the specific transmission mechanism. Estimates are sticky; that gap is knowable now. |
| **Macro** | C | mid | Sector series against what estimates appear to assume. A Fed paper puts that gap at ~50% of current-quarter analyst error. |
| **Champion** ×7 | D | mid | Argues each case properly, then argues against it — before anything is compared. |
| **Judge** | E | **deep** | One expensive call. Weighs by materiality, never by vote count. Outputs a distribution. |
| **Comparability** | V2 | cheap | Is this quarter comparable at all? When it fires, λ collapses. |
| **Guidance extractor** | B | cheap | 8-K EX-99.1 → structured guide, with every quote verified against the filing. |

Three choices carry the design:

**Lenses are blind to each other.** Diversity is the point. Let them see each other's work and they converge — and converging is how you accidentally rebuild consensus, which scores zero. `run_lens` has no parameter through which one lens could reach another, and [a test asserts it stays that way](tests/test_llm_layer.py).

**The judge weighs by materiality, never by vote count.** Six lenses agreeing on a weak signal loses to one carrying the company's own guidance and a verbatim quote. There is deliberately no averaging, plurality or majority logic anywhere in aggregation — lenses read overlapping documents, so their errors are correlated and five being wrong together is about as likely as one.

**Champion development runs before any comparison.** Comparing raw findings and taking the plurality is a known failure mode; it rewards the finding that is easiest to reach, not the one that matters most.

---

## No number without a source

`Claim` cannot be constructed without a `Source` and a `verbatim_quote`, and model cells refuse an input with neither a claim nor an explicit note. So *"we don't invent figures"* is a validation error, not a code-review comment.

Verification splits by source kind, which is the part that is easy to get wrong:

- **Prose sources** (8-K, 10-Q, 10-K, transcripts) must string-match their document. A quote assembled from two sentences reads perfectly and is not what the company said.
- **Structured sources** (XBRL, sponsor feed, FRED) are verified by construction — the "quote" is the tagged fact, rendered by the adapter from a typed response. A model can only cite ids already in the store, so the *value* came from the adapter, never from the model.

Failed citations are shown in red in the UI, not hidden. "We verify every citation" only means something if the failures are visible.

---

## Point-in-time

Every `DataSource` method takes `as_of` and must not return anything filed after it. `assert_point_in_time` raises loudly, and [tests/test_point_in_time.py](tests/test_point_in_time.py) deliberately tries to leak — including the subtle case, a *restatement* of a historical period published after the lock date.

Two places this is easy to get wrong and is handled:

- **Consensus.** `yfinance.earnings_estimate` is consensus *as of now*; using it for a historical case is look-ahead bias. `earnings_history.epsEstimate` is consensus *as it stood at that quarter's report date* — the bar the company was actually scored against. That is the column the case builder uses.
- **Macro.** FRED series are revised for months. Every request sets `realtime_start` from `as_of`, so the Macro lens sees the numbers that existed at the time rather than the restated ones.

A backtest that cannot fail this way is not enforcing anything, and its numbers mean nothing.

---

## Scoring-rule agnostic

The metric isn't known until the morning of the event. The judge outputs a **distribution**, which is a strict superset of a point forecast, and three λ presets are backtested during prep:

| Preset | For | Behaviour |
|---|---|---|
| `shrink` | MAE · MAPE · MSE | λ = fitted β; emit median (mean under squared error) |
| `barbell` | skill score vs consensus, rank leaderboards | λ high on top-conviction names, 0 elsewhere |
| `calibrated` | CRPS · pinball | full quantiles; optimise calibration, don't hedge with width |

Plus `--tiny-tilt` for a pure win-rate metric, where matching consensus scores exactly zero and direction matters but magnitude doesn't.

Both `eps_gaap` and `eps_non_gaap` are carried — consensus is non-GAAP, XBRL is GAAP, and the median DJIA gap was 31% in one recent quarter. The bridge is an explicit cited object with a `verify()` that refuses to tie if an item is missing; there is no default ratio, because assuming the sector median is how a forecast ends up confidently 31% wrong.

---

## The UI

Five screens, static export, no backend. `make serve`.

| Route | What it is |
|---|---|
| `/` | **The live run.** The architecture diagram *is* the UI — nodes go idle → running → done as the pipeline executes, latency ticking in place. |
| `/forecast` | Hero number, distribution as the primary mark, consensus on the same axis, the gap stated in words. |
| `/reasoning` | Seven lenses, expandable to thesis + counterargument. Failed citations in red. Dropped lenses shown with their reason. |
| `/model` | The three statements, every cell showing whether it traces to a filing. |
| `/eval` | Backtest vs baseline, reliability diagram, leave-one-out ablation, fitted β per regime. |

**No API between the two processes.** Python appends to `out/events.ndjson`; the UI polls it. Nothing to crash mid-demo — and replay mode comes free: `?replay=<name>` streams a recorded log at its original pacing through the identical code path. If the live run dies on stage you change one URL.

---

## Layout

```
src/forecaster/
  schemas.py              the contract — change this first, UI types generate from it
  config.py               model tiering, budgets, the cost ceiling
  data/
    protocol.py           DataSource; every method takes as_of and may return None
    sec_source.py         XBRL + filings + document text
    yfinance_source.py    consensus, point-in-time for history
    fred_source.py        macro, point-in-time via ALFRED realtime_start
    sponsor_source.py     ← the adapter written on the day
    universe.py           prepared peers, value chain, drivers
  llm/
    client.py             schema-forced, cached, cost-ceilinged
    prompt.py             versioned loading; the fingerprint keys the cache
    prompts/*.yaml        ten agents — one file each, never inlined in Python
  model/
    graph.py              dependency-graph evaluator; cells carry provenance
    statements.py         linked IS/BS/CF; the balance check is a hard gate
    bridge.py             GAAP ↔ non-GAAP, cited, with verify()
  pipeline/
    run.py                A→G in one readable function
    a_acquire.py          ranked targets, hard budgets, logs what it skipped
    b_structure.py        the evidence store and the cached corpus
    c_lenses/             seven lenses, blind to each other
    v1_reconcile.py       arithmetic + citations
    d_champion.py         argue for, then against
    e_judge.py            impact-weighted → a distribution
    v2_comparability.py   fires → λ collapses
    f_lambda.py           the thesis
    v3_calibrate.py       our own residuals, by regime
  eval/
    cases.py              point-in-time firm-quarters — Block 1, the gate
    backtest.py           MAE, skill, Wilson CI, ablation
    fit.py                the constrained regression that replaces FITTED_BETA
    baseline.py           consensus × shrunk company tilt
    landing.py            where a company lands inside its own range
tests/                    each test encodes a failure mode, not a happy path
ui/                       Next.js, static export, reads out/*.json
```

---

## Status

**Pipeline complete, 90 tests passing.** Every layer A→G is wired, all ten agents are built, the UI builds clean and `make verify` is green in CI.

One caveat visible on the live screen and the `/system/` sheet, because drawing the agent/not-agent split is what surfaced it: **the guidance extractor is built and tested but `run.py` never calls it**, so the Guidance lens currently reads raw filing text rather than a structured guide. It is drawn as a dashed footprint marked NOT WIRED rather than shown as complete.

**Two things are still asserted rather than measured, and both need one live run to fix:**

1. **`FITTED_BETA` holds three placeholder numbers.** The regression that replaces them is built (`forecast fit`) but needs the ~200 firm-quarter case set to run against. Until then the thesis is asserted, which is precisely the distinction this repo is built around.
2. **The data sources have never been run against the network from the demo machine.** `forecast sources --ticker NVDA` is the first command to run, and it checks the thing most likely to be silently broken: whether filing body text actually arrives, because without it every prose citation fails verification.

Block 1 is the gate: build the cases, verify the GAAP↔non-GAAP bridge by hand on ten companies, and score `consensus × 1.02`. That number is what everything afterwards is measured against.
