# Agents vs Wall Street — Master Plan

**Sunday 16 August 2026 · 10:00–19:30 · central London · $10,000 across three awards**

This is the single working document. It supersedes the earlier build/system/map/v2 docs — those are folded in below. `agents-vs-wall-street-strategy.md` remains as the research reference (base rates, sources, the judge dossier); you shouldn't need it day to day.

**Contents**
1. The thesis, in one page
2. What wins — the three prizes and who judges them
3. The system
4. The seven lenses
5. Verification layers
6. Statistics
7. Design
8. Production
9. Prep schedule — 30 Jul to 15 Aug
10. Day-of run sheet
11. The demo
12. Open questions for Alistair

---

## 1. The thesis, in one page

Consensus is not a forecast. It is analysts' good analysis with a thumb on the scale:

- Estimates are **walked down 3.0–4.2% during the quarter**, before any results.
- **58–63% of guiding companies guide negative.**
- **78% of S&P 500 companies then beat** the bar that gets set; aggregate surprise **+7.0%**.

None of that is analytical error. It's incentive — management access, career risk from a visible miss, herding, reluctance to publish an outlier. The analysis underneath is excellent: analysts beat a naive random walk by 245bp of price at exactly the one-month horizon this competition uses.

> **Reproduce the analysis. Strip the incentives. Add the question no individual analyst can ask — *where is consensus structurally weak?*"**
>
> **We didn't build an AI analyst. We built an analyst with no incentives.**

Three layers follow:

| | |
|---|---|
| **COPY** | evidence gathering, the 3-statement model, guidance parsing, driver build-up, the EPS bridge, quality-of-earnings checks |
| **STRIP** | the walk-down, herding, round-number bias, revision stickiness, access caution — *but keep the humility about uncertainty* |
| **ADD** | λ — how far to deviate, given coverage, dispersion, staleness, and internal disagreement |

Formally: `forecast = consensus + λ · (own_estimate − consensus)`, where **λ is fitted on backtest, not guessed**, and conditioned on regime.

---

## 2. What wins — three prizes, different judges

| Prize | Judged | Optimise for |
|---|---|---|
| **Accuracy** | after the event, **mechanically** | anchor tight, tilt for the base rate, calibrate λ. Boring is correct. |
| **Best architecture** | live, by humans who published their views | structure over prompting, adversarial steps, evals as an artifact |
| **Best aesthetics** | live | see §7 — the softest target in the room |

**The organiser is Alistair Smallwood, Head of Applied AI at Primer, and his Substack is effectively a published rubric.** What he has written, and what it demands:

- Direct prompting scored **0/~100** on his forensic task; a three-stage pipeline hit **~92%**. *"Prompts change what models read but not what they conclude."* → **architecture, not prompt-craft.**
- His multi-agent system **failed** when a boss agent picked the most *frequent* finding rather than the most *material*. → **never aggregate by vote.**
- The fix was **champion development**: elaborate each candidate into a full thesis *with counterarguments* before any comparison. → **§3, layer D.**
- *"A single run of a model is a coin flip wearing a suit."* He ran 5 runs per condition. → **report variance.**
- He wrote a whole post showing momentum monkeys beat six of eight AI models. → **beat a dumb baseline, explicitly, or say you didn't.**
- Evals: relative side-by-side scoring, and **validate the reasoning path** — explicit evidence, no invented numbers. → **§5.**
- Named **ex-post verification** as the frontier. OpenStocks is that thesis productised.

⚠️ The event copy says *"beating the Street is the whole game."* His own writing says a leaderboard this small can't distinguish skill from luck. Both are true — **play accuracy to win on the numbers, present with rigour.** Don't let the marketing copy talk you into overclaiming on stage.

---

## 3. The system

```
LAYER A — ACQUIRE (parallel, cheap model, hard budgets)
  B1 Numbers      XBRL / sponsor feed → typed financials, point-in-time
  B2 Filings      8-K EX-99.1 · transcript · 10-Q · post-call 8-Ks
  B3 Industry     peers who already reported · value chain · volume & price
  B4 Macro        FRED series relevant to the sector
        │
LAYER B — STRUCTURE
  B1 3-statement model   IS/BS/CF, linked, deterministic, no LLM
  B2 Evidence store      typed Claims {value, source, verbatim_quote, as_of}
        │
LAYER C — ANALYSE (7 lenses, parallel, blind to each other, shared cached prefix)
        │
LAYER V1 — RECONCILE   arithmetic + citation verification, per lens
        │
LAYER D — CHALLENGE    champion development ×7: argue it, then argue against it
        │
LAYER E — JUDGE        impact-weighted, never vote-weighted → a range
        │
LAYER V2 — COMPARABILITY   is this quarter even comparable?
        │
LAYER F — POSITION     λ vs consensus, fitted and regime-conditioned
        │
LAYER V3 — CALIBRATE   bootstrap own backtest residuals → honest interval
        │
LAYER G — WRITE BACK   into the model · render
```

**Why each structural choice exists:**

| Choice | Reason |
|---|---|
| A1–A4 parallel | No shared inputs. Serialising costs an hour on the day for nothing. |
| B1 deterministic | A model built by an LLM is a model you can't trust. |
| Lenses blind to each other | Diversity is the point. If they see each other they converge — and converging rebuilds consensus, which scores zero. |
| **Layer D** | The step that took his system from failing to 92%. |
| Judge weights by materiality | His documented failure mode. Six agents agreeing on a weak signal loses to one with the company's own guidance. |
| **λ structurally separate** | Everything left of it forecasts; λ decides how much to trust that. Separating them *is* the thesis. |

**Model tiering** (his "tokens as a variable cost to allocate strategically"): cheap for A and B2; mid for C and D; **expensive for E, one call, highest leverage**; F is mostly code.

**Three cost levers that matter:** prompt-cache the corpus once and fan the lenses against it; Batch API for backtests; per-stage caching keyed on input hash so re-running layer E doesn't re-run A–D.

**Escalation rule:** run layer C cheap first. If lenses disagree beyond a threshold *or* the position is far from consensus, re-run those lenses at the expensive tier. Log the decision — it's a good slide.

---

## 4. The seven lenses

| Lens | What it does | Runs on |
|---|---|---|
| **Mechanical** | FX translation, diluted share count from buyback pace, net interest, calendar/53rd-week effects | **pure code, no LLM** |
| **Guidance** | Prior-quarter guide + **where this company historically lands inside its own range** (8-quarter empirical CDF) | cheap LLM + stats |
| **Drivers** | Bottom-up revenue: units × ASP, subs × ARPU, comps × stores, backlog conversion | mid LLM |
| **Margins** | Revenue → EPS: GM mix, opex, headcount trajectory, tax rate | mid LLM |
| **Forensics** | Reads as auditor not forecaster: accruals vs cash conversion, DSO/inventory, **changes in the non-GAAP exclusion mix** | mid LLM |
| **Peer read** | Who in the same value chain already reported *this cycle*? Consensus often hasn't caught up | mid LLM |
| **Macro** | Sector-relevant FRED series. The Fed's own paper finds a macro-vs-analyst gap predicts **~50% of current-quarter analyst error** (R² 0.48–0.51) | stats + cheap LLM |

Separately, **consensus mechanics** (coverage count, dispersion, revision momentum, staleness) is *not* a lens — it produces no estimate. It feeds λ.

**Build Mechanical first.** It's deterministic, testable, will be working while everything else is flaky, and it moves the forecast for a reason nobody can argue with: a 3% currency move on a 60%-international revenue base is a ~1.8% revenue swing that most models never refresh, and EPS is a ratio whose denominator changes with every buyback.

⚠️ **The trap that kills silently:** consensus is **non-GAAP**; XBRL is **GAAP**; the median DJIA gap was **31%** in one recent quarter. Verify the bridge by hand on 10 companies in week one. Get it wrong and every lens is precisely and identically wrong, and it will look like bad modelling.

---

## 5. Verification layers

Nothing in a naive pipeline checks anything. These do, and three of the four are plain code — they add rigour without adding hallucination surface.

**V1a · Arithmetic reconciler** *(deterministic — highest-value single component)*
After every lens and again after the judge, assert:
- `revenue × GM − opex`, taxed, `÷ diluted shares` equals the claimed EPS
- segment revenues sum to total
- **units are consistent** — millions vs thousands is the error that will actually bite you
- implied YoY growth is inside a sane band
- the GAAP↔non-GAAP bridge reconciles

A lens that fails is **dropped and logged**, never silently averaged in.

**V1b · Citation verifier** *(deterministic)*
Every `verbatim_quote` must string-match its source document. Report the failure count in the UI. This turns "we cite sources" into "we verify every citation" — a measured property, not a claim, and the direct answer to *no invented numbers*.

**V2 · Comparability check** *(one cheap LLM call)*
Flag M&A closed mid-quarter, divestitures, accounting-standard changes, withdrawn or restated guidance, 53rd weeks, segment reorganisations, FX regime shifts. **When it fires, λ collapses toward consensus** — historical priors don't apply. This stops the system being most confident exactly where it's least entitled to be.

**V3 · Calibration layer** *(statistics)*
Model-stated confidence is uncalibrated and always will be. Replace it: bootstrap your own backtest residuals, conditioned on regime bucket. The interval then reflects how wrong you *have been*, not how wrong the model *thinks* it might be.

**Provenance as a type constraint** — the strongest single production move:
> No number enters the model without `{value, source_uri, verbatim_quote, as_of_date}`. Make it a validation error, not a code review comment.

---

## 6. Statistics

This is where the accuracy prize is won, and it's mostly not LLM work.

**6.1 It's a forecast combination problem.** You have K lens estimates plus one very good external forecast. Framing it that way is more rigorous *and* more impressive than "our agent predicts."

- **Combining lenses:** never average. Weight by inverse out-of-sample MSE from backtest — each lens earns its weight by historical accuracy on comparable names. Constrained least squares if you have the data.
- **Combining with consensus:** fit `actual = α·consensus + β·own + ε` on backtest. **β is λ.** Expect it small — that's the honest answer, and knowing it empirically beats asserting it. Then fit separately by coverage bucket × dispersion bucket × staleness. That's the thesis as a statistical model rather than a vibe.

**6.2 Shrinkage, because n≈8.** Any per-company statistic (median surprise, guide-landing position) has ~8 observations and will be noise. James-Stein / empirical Bayes: shrink toward the sector median, weight set by within- vs between-company variance. Two lines of code, materially better estimates, proper name on the slide.

**6.3 Robust estimators.** One Alphabet-style outlier destroys mean-based statistics — FactSet's own headline surprise fell from +39.3% to +12.6% on excluding a single company. **Medians and MAD throughout; winsorize at 5th/95th before any mean. Never calibrate on a cap-weighted aggregate.**

**6.4 Output a distribution.** Bootstrap backtest residuals conditioned on regime. Strictly better even under point scoring — it gives you λ, it gives you the UI, and it wins outright if scoring is CRPS or pinball.

**6.5 The eval harness — this is what wins the architecture prize.**
- Reliability diagram: do your 80% intervals cover 80%? They won't at first. Fixing it is cheap and visual.
- **Leave-one-lens-out ablation.** Marginal contribution of each of the seven. **Non-optional.** If two don't earn their tokens, say so on stage — that lands better with this judge than an unfalsifiable win.
- **k=5 runs per config**, variance reported. Also use it as signal: high inter-run variance = low confidence = shrink λ.
- Baseline on every chart: `consensus × (1 + shrunk company surprise)`.
- Point-in-time assertion enforced in code, with a test that deliberately triggers it.
- **Report n and confidence intervals.** Detecting a 2% edge at 80% power needs ~350 resolved forecasts. With 1–5 live companies you cannot distinguish skill from luck. Say it before someone else does.

---

## 7. Design

**The core idea, which collapses two prizes into one artifact:**

> **The architecture diagram is the UI. Nodes light up as the pipeline executes.**

Idle → running → done, per node, with token count and latency ticking in place. Evidence claims streaming into the store. Seven lenses resolving at different speeds. The judge waiting. λ landing last. The demo stops being *"here's our architecture"* then *"here's our output"* — it's one thing, and the room watches the system think.

### Four screens

| | |
|---|---|
| **1 · Live run** | The animated architecture. This is the demo. |
| **2 · Forecast** | Hero number. Distribution as the primary mark. Consensus on the same axis. The gap stated in words: *"$0.11 above the Street, mostly FX."* |
| **3 · Reasoning trace** | Seven lenses, expandable to thesis + counterargument. Every claim clickable → verbatim quote highlighted in source. **Failed citations shown in red, not hidden.** |
| **4 · Method** | Backtest vs baseline · calibration reliability diagram · leave-one-out ablation · error bars from the 5 runs. Plus the 3-statement model rendered as statements. |

Screen 3 wins on substance; screen 1 wins in the room.

### Design system — decide once
- **Next.js + Tailwind + shadcn/ui + Recharts**, static export reading a JSON file. No backend to fail on stage.
- **One accent colour**, used only for *our* forecast. Consensus is always neutral grey.
- **Tabular numerals everywhere.** Financial figures that jitter as they update look amateur.
- **Motion only for state change**, 150–200ms. Decorative animation reads as a template.
- Dense, financial-tool layout. Dark mode deliberately stepped, not an inverted filter.
- **Empty and error states designed.** A dropped lens should look intentional — greyed, with the reason. Something will fail live; make failure look like a feature.

### The fallback, built before you need it
At 17:00 record a full run as video and screenshot every screen. Practise switching to it once.

---

## 8. Production

**Reproducibility** — because OpenStocks' verified tier means *they run your agent*:
- `uv` + committed lockfile, or a pinned Dockerfile
- All LLM calls seeded and content-hash cached; a cached re-run is byte-identical
- No absolute paths, no machine-specific config, secrets from env only
- One command: `docker run … --ticker NVDA --as-of 2026-08-16`

**Observability** — so the token-cost line is earned:
- Structured JSON logs, one per stage: `{stage, model, in_tokens, out_tokens, cost, latency_ms, cache_hit}`
- Run manifest: every source fetched, every claim extracted, every lens dropped and why
- **Cost ceiling with a hard kill switch.** A loop burning credits at 14:00 ends your day.

**Failure handling** — someone will ask:
- Exponential backoff on transient errors; **fail fast on schema errors** (retrying malformed output mostly just costs money)
- Circuit breaker per data source — three failures and it's down for the run
- **Graceful lens dropout**: a lens that errors or fails reconciliation is excluded, the judge is told it's missing, the run continues, the UI shows it
- Every LLM response schema-validated. Fail closed, never silently coerce.

**Testing:**
- Unit tests on all deterministic code — EPS bridge, FX, share count, reconciler, the 3-statement links
- **Point-in-time leak test** that deliberately fetches a post-`as_of` filing and asserts refusal
- Schema round-trip tests on every extraction model

**The one move that proves all of it:**
```
make verify
```
Full pipeline, one fixed historical quarter, from cache, output asserted against a committed golden file. In CI, on every commit. That single command demonstrates determinism, reproducibility, point-in-time correctness and test discipline at once — a better answer to *"is this production-ready?"* than any diagram.

---

## 9. Prep schedule — 30 Jul to 15 Aug

**Budget:** full days available — call it **~130 hours** across 17 days. Scope is ~80. **You are no longer time-constrained, which changes what the constraint actually is.**

Three things follow, and they matter more than the calendar:

1. **Don't spend the surplus on more features.** The temptation with this much runway is to add an eighth lens, a second data source, a nicer model. Resist it. The ablation will already show some of seven don't earn their tokens.
2. **Spend it on backtest iterations instead.** This is the single highest-return use of extra hours and it's what everyone runs out of time for. More historical quarters, more regime buckets, more ablation runs, better-fitted λ. Accuracy comes from here, not from more components.
3. **Build a second dress rehearsal in.** Two full timed dry runs on different companies beats one, by a lot.

Also worth naming: with this much time the repo stops being a hackathon artifact and becomes a **portfolio piece**. Alistair's stated reservation was production experience. A public repo with CI, tests, a golden-file verify and an honest eval writeup answers that question after the 16th as much as on it. Build it to be read.

**Daily shape that works:** ~4h focused build in the morning, ~3h in the afternoon, evening for reading and the eval writeup. Take Wednesdays lighter — you want to arrive on the 16th sharp, not fried.

### Block 0 · Thu 30 – Fri 31 Jul · ~8h
- [ ] **Email Alistair** (§12). Answers take days and change the plan. Do this first.
- [ ] Register on Luma — approval required, spots limited.
- [ ] Read the three Substack posts. Note his vocabulary; you'll reuse it on stage.
- [ ] `pip install edgartools yfinance` — pull one company's XBRL facts and one consensus snapshot from your actual machine. Confirm both work.

- [ ] Skim the withdrawn Kim/Muhn/Nikolaev paper and the Li/Tu/Zhou counter-study. Half the room will cite the first as fact.

### Block 1 · Sat 1 – Sun 2 Aug · ~14h · **The baseline gate**
**No pipeline stages this weekend.**
- [ ] `DataSource` protocol + yfinance implementation + parquet cache
- [ ] Backtest harness with `as_of` enforcement, plus the leak test that deliberately triggers it
- [ ] ~200 historical firm-quarters: consensus, actual (non-GAAP), coverage, dispersion
- [ ] **GAAP↔non-GAAP bridge verified by hand on 10 companies**
- [ ] Compute per-company median absolute surprise; compute what `consensus × 1.02` scores

**🚩 Gate: you have the baseline number. Everything after this is measured against it.**

### Block 2 · Mon 3 – Fri 7 Aug · ~13h
- [ ] Mon: **Mechanical lens** (FX, share count, interest, calendar) + arithmetic reconciler. Deterministic, testable, done.
- [ ] Tue: Evidence store + schemas (every model carries `verbatim_quote`, `as_of_date`) + citation verifier
- [ ] Wed: **Guidance extractor** — 8-K EX-99.1 → structured guide, plus the 8-quarter landing distribution. Highest-signal input; give it a full evening.
- [ ] Thu: **3-statement model** — IS/BS/CF linked, deterministic, with unit tests on the links
- [ ] Fri: Lenses — Drivers, Margins

### Block 3 · Sat 8 – Sun 9 Aug · ~12h
- [ ] Lenses — Forensics, Peer read, Macro (FRED)
- [ ] Champion development layer
- [ ] Impact-weighted judge → range
- [ ] λ module + the regression that fits it
- [ ] **Full backtest, 5 runs per config, vs baseline. Leave-one-out ablation.**

**🚩 Checkpoint, Sunday 9th.** One question now that time isn't the constraint: **do you beat the baseline, and on which kinds of names?** If not, don't add components — go back to the eval and find out why. A week spent understanding a negative result beats a week spent papering over it, and it's the better demo.

### Block 4 · Mon 10 – Thu 13 Aug · ~30h · **Frontend, verification, production**
- [ ] Mon–Tue: **Frontend, including the live-run view.** Longest single item. Claude Code does the heavy lifting; you direct it.
- [ ] Wed: Comparability check + calibration layer + statistics (combination weights, shrinkage, bootstrap residuals)
- [ ] Thu: Docker, pinned deps, structured logging, cost ceiling, graceful dropout, **`make verify` + CI**, README with architecture diagram

### Block 5 · Fri 14 Aug · ~8h · **Rehearsal one, and the surplus**
- [ ] Full timed dry run on **Micron** — highest-variance name in the window, where an agent can actually show something
- [ ] **Fresh-clone test on a different machine.** One command → forecast. Fix what breaks.
- [ ] Then spend the rest on **backtest depth**: more quarters, more regime buckets, refit λ. This is where the accuracy prize actually lives.

### Block 6 · Sat 15 Aug · ~7h · **Rehearsal two, then stop**
- [ ] Second full dry run, different company — **FedEx** (two-sided surprise tails, a genuinely different failure mode)
- [ ] Pre-cache to parquet: yfinance estimates for the likely universe, 1–2 SEC Financial Statement Data Set quarters, the Kaggle transcript dump
- [ ] Record the fallback video, screenshot every screen
- [ ] Write and rehearse the 3-minute demo. Out loud. Timed. Twice.
- [ ] Pack: laptop, charger, **ethernet adapter**, hotspot tested.
- [ ] **Stop by 18:00.** Turning up rested beats turning up with one more lens.

---

## 10. Day-of run sheet — Sun 16 Aug

~6 hours of real build after intro, food and demos. **Integration, not greenfield.**

| Time | What |
|---|---|
| 10:00–10:30 | **Intro.** Listen for: which companies, what data, **the scoring metric — write it down verbatim.** |
| 10:30–11:00 | **Write the adapter.** Their feed → your `DataSource`. The only genuinely new code today. |
| 11:00–11:30 | **Smoke test end to end.** One company, all the way through. Confirm non-GAAP, confirm it matches their "actual." **Not green by 11:30 → grab a mentor, don't debug alone.** |
| 11:30–13:00 | Build block 1 — tune to the real companies. Dead-weight lens → cut and log it. |
| 13:00–13:30 | Lunch. Find a mentor. Ask about scoring edge cases, especially near-zero EPS. |
| 13:30–15:30 | Build block 2 — calibrate λ on comparables. 5 runs, capture spread. |
| **15:30** | **HARD FREEZE.** No more logic changes. Generate final forecasts, write results. |
| 15:30–17:30 | Build block 3 — **presentation only.** Real results into the frontend. Screenshot everything at 17:00. |
| 17:30–18:00 | Rehearse out loud, twice, timed. |
| 18:00–18:30 | Buffer. Something will have broken. |
| 18:30–19:30 | Demos and judging. |

**Three rules:** the 15:30 freeze is real — every hackathon loss is someone still changing code at 18:45. Claude Code for glue and UI, never the core pipeline — you must be able to explain layers C–F under questioning. Screenshot everything at 17:00.

---

## 11. The demo

> "Consensus isn't a forecast. It's a forecast with a thumb on the scale — analysts walk estimates down three to four percent a quarter, sixty percent of company guidance is deliberately conservative, and seventy-eight percent of companies then beat the bar that gets set. The analysis underneath is excellent. The published number is that analysis, shaded.
>
> So we didn't try to out-analyse Wall Street. We mapped what an analyst actually does — the guidance anchor, the driver model, the three statements, the share-count divisor, the quality-of-earnings check — reproduced it, and stripped out the incentives. No management relationship to protect. No career risk from an outlier. No herding.
>
> Then we added the one step no individual analyst can run, because they *are* the consensus: where is it structurally weak? Four analysts and stale estimates is a different problem from sixty-one and fresh segment models. Our agent shrinks to the Street on the second and commits on the first — and here's the eval showing it makes that call correctly.
>
> One of our seven lenses has no language model in it at all. It's FX translation and share count — arithmetic that moves after consensus is set and that most models never refresh. And nothing enters the model without a source, a quote and a date; that's a validation error, not a code review comment.
>
> The honest part: at this sample size nobody in this room can distinguish skill from luck. Detecting a two-percent edge at eighty-percent power needs about three hundred and fifty resolved forecasts. So we're not claiming we beat Wall Street. We're showing you a system whose reasoning you can audit, that runs reproducibly in your environment, and that tells you when it doesn't know."

That last paragraph is the risky one and it's the one most likely to win. It's his own published argument, handed back to him.

---

## 12. Open questions for Alistair

Send now — every one of these changes something.

1. **Sunday 16th, 10:00–19:30?** The Luma details block still says Monday 17th, 9–7.
2. **Which "actual" does OpenStocks score against** — GAAP, company non-GAAP, or a vendor's standardised street number? Whose consensus?
3. **What is the scoring metric?** MAE / MAPE / skill score vs consensus / win-rate / CRPS. *Highest-value question on the list — every rule implies a different agent.*
4. **What exactly is in the provided data and API credits?** Which vendors, which endpoints, does it include forward consensus, can you see the schema in advance?
5. **How many companies?** The copy says "a real company" in one place and "your companies" in another.
6. **Solo or teams?**
7. **Is pre-existing code allowed?** You're planning to arrive with a finished frontend.
8. **Does the Community Verified GitHub tier apply** — will OpenStocks execute your agent themselves?
