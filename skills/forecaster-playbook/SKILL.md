---
name: forecaster-playbook
description: Use at the start of "Agents vs Wall Street" or any earnings-forecasting-agent build under time pressure — captures the shrinkage thesis, non-negotiable invariants, pipeline architecture, DataSource adapter contract, and known traps from prior work as knowledge and checklists only (deliberately no source code), so it's usable whether or not the event allows bringing pre-existing code. Triggers on "earnings forecast agent", "consensus shrinkage", "DataSource adapter", "Agents vs Wall Street", "hackathon day-of checklist", "rebuild the forecaster from scratch".
---

# Earnings-forecaster playbook

This is knowledge, not code. It exists so a rebuild — in this repo, a fresh
repo, or an organizer-provided one — can move fast from understanding rather
than from copy-paste. Nothing here is a source-file excerpt; treat it as the
operator's own notes on an architecture they already validated.

## Companion skills

This file is the cross-cutting judgment layer — thesis, invariants, traps,
day-of checklist. Component-level detail lives in sibling skills, all under
`skills/` at the repo root: `forecaster-data-model-core` (sources, model,
V1–V3, lambda), `forecaster-lenses` (the 9 analytical lenses), `forecaster-
extractors-scanners` (the 4 evidence-population agents), `forecaster-
champion-judge` (argue-for-then-against, materiality-weighted aggregation),
`forecaster-ui` (the 9-sheet UI), plus `hackathon-narrative-generation`,
`hackathon-ui-presentation-layer`, and `hackathon-e2e-integration` (the
narrative one-pager stage, the live/narrative UI routes, and the full
integration checklist). **`forecaster-orchestrator` is the actual entry
point tomorrow** — it reads this file plus the others and drives the build
as parallel agents in dependency order. Start there, not here.

## The thesis (this is the whole point — don't lose it under time pressure)

Consensus is not a neutral forecast. It's analysts' real analysis with a
structural thumb on the scale: estimates get walked down ~3–4% during the
quarter before any results, most guiding companies guide low, and the
aggregate then beats that lowered bar by mid-single-digit percent. That's
incentive, not error — analysts already beat a naive random walk.

So the move is: reproduce the analysis, strip the incentive, then ask the one
question no individual sell-side analyst can ask, because they collectively
*are* the consensus — where is consensus structurally weak this quarter?

```
forecast = consensus + λ · (own_estimate − consensus)
```

λ must be **fitted on backtest data, never asserted**, and conditioned on
regime (coverage count, dispersion, staleness, disagreement across internal
lenses, comparability issues). On a heavily-covered mega-cap, λ shrinking to
~0 is the *correct* output, not a failed system — do not chase visible
deviation as a proxy for the system "doing something."

## Non-negotiable invariants

These are correctness properties, not style preferences — violating any of
them invalidates the forecast even if the code runs cleanly.

1. **Point-in-time.** Every data call takes an `as_of` and must never surface
   anything filed/restated after it. This is the single easiest thing to get
   silently wrong, especially with common finance libraries that return the
   *current* consensus/estimate rather than what stood on the date in
   question — see traps below.
2. **No number without provenance.** Every claim traces to a source document
   and a verbatim quote from it. A pointer to a filing index entry is not a
   quote from the filing it points at — treat those as a distinct, weaker
   claim type.
3. **Independent lenses.** Parallel analytical viewpoints (guidance-based,
   driver-based, demand-side, margin-based, peer-comparison, macro, etc.)
   must never see each other's output before forming a view. If they do, they
   converge — and a converged ensemble just rebuilds consensus, which is
   exactly the thing being tested against.
4. **Weight by materiality, never by vote.** Aggregating lens views must never
   average, plurality-vote, or majority-vote. One lens holding the company's
   own guidance with a direct quote should outweigh several lenses agreeing
   on something weaker.
5. **Argue for, then against, before ranking.** Each analytical case gets
   built and then adversarially challenged before anything is compared.
6. **Always chart the baseline** — `consensus × (1 + shrunk company surprise
   tilt)`. It is a strong baseline, not a strawman. If the full pipeline can't
   beat it, the honest output is λ≈0 with that stated plainly, not a forced
   deviation.
7. **Robust statistics only.** Median/MAD, winsorize before any mean. Never
   calibrate against a cap-weighted aggregate — one large constituent can flip
   the sign of an aggregate surprise number entirely.

## Architecture shape (rebuild order if starting from zero)

Conceptual pipeline, roughly in build-priority order — earlier stages carry
most of the value and are cheapest to build; later stages are refinements:

1. **Sources** — adapters over whatever feeds are available (filings/XBRL,
   a market-data vendor, a general search/news API for qualitative context,
   a macro series source). Each adapter obeys the point-in-time contract
   below regardless of what it wraps.
2. **Acquire** — pull numbers, time series, filings, guidance for one
   company/period, in parallel, under a hard cost/time budget. Log what gets
   skipped when a budget is hit — never truncate silently.
3. **Structure** — turn raw pulled material into an evidence store: discrete,
   sourced, quotable claims. Nothing downstream touches raw documents again.
4. **Model** — a deterministic 3-statement model (or whatever minimal
   ratio-based structure fits the time budget) that produces a mechanical
   base case with no LLM involved. This alone, run historically, tells you
   the model's own structural error.
5. **Analyse** — independent lenses per §"Non-negotiable invariants" #3,
   each producing an estimate plus its reasoning trace and citations.
6. **Reconcile** — verify arithmetic and that every citation actually
   string-matches its claimed source. A lens that fails reconciliation gets
   dropped and logged, never silently down-weighted into the average.
7. **Challenge → Judge** — argue each lens's case and the case against it,
   then one expensive, materiality-weighted judgment call collapses lens
   views into a distribution. This is the single highest-leverage LLM call
   in the pipeline — spend model quality here, not everywhere.
8. **Comparability check** — M&A, accounting changes, extra/missing week in
   the period. Any hit here should collapse λ toward 0 for that name; a
   forecast conditioned on a broken YoY comparison is worse than none.
9. **Position (λ)** — blend own estimate with consensus per the formula
   above, regime-conditioned, fitted not guessed.
10. **Calibrate** — bootstrap uncertainty width from your own backtest
    residuals, not an assumed distribution shape.
11. **Output** — forecast + a legible trace of *why*, written to disk for a
    UI (or terminal output) to read. Keep the pipeline and the presentation
    layer decoupled — whatever you build to show results should be able to
    replay a recorded run as well as a live one; that recorded-replay path
    is the demo's insurance policy against a live API dying mid-presentation.

## DataSource adapter contract (the one thing genuinely new on the day)

Whatever the sponsor's feed looks like, wrap it behind a small interface
shape, not ad hoc calls scattered through the pipeline:

- Every method takes an explicit `as_of` date/timestamp parameter.
- Every method is tolerant of "no data yet" (return `None`/empty, don't
  raise) — as-of a date, absence of data is a valid, common answer.
- A method must refuse to return anything filed, published, or restated
  after `as_of`. If the underlying API doesn't support historical
  point-in-time queries at all, that adapter is backtest-unsafe and should
  say so explicitly rather than silently serving current data.
- Keep the adapter itself dumb — parsing/normalizing into the pipeline's
  internal shape happens one layer up, so swapping vendors later doesn't
  ripple through everything downstream.
- Smoke-test each adapter standalone against a known ticker/date before
  wiring it into the full pipeline — cheapest place to catch a wrong field
  mapping or unit mismatch.

## Known traps (each of these has already cost real time once)

- **GAAP vs non-GAAP.** Consensus estimates are typically non-GAAP; official
  filings (XBRL) are GAAP. The gap between them can be large (double-digit
  percent) and *directional* — every EPS-like figure needs its basis tagged,
  or the error looks like a modelling bug when it's actually a units-of-
  comparison bug.
- **A commonly-used finance library's "current estimate" fields are not
  point-in-time.** For any historical backtest, use whatever field represents
  consensus *as it stood at that period's report date*, not today's restated
  estimate — using the wrong one is look-ahead bias baked silently into every
  backtest number.
- **A replay/cached path skips acquisition entirely.** A bug in the live data
  layer can be invisible for a long time if development mostly runs against
  cached/replayed data. Before trusting any change near data acquisition, run
  once cold, without cache/replay.
- **Prompt caching is a prefix match; parallel fan-out defeats it.** If
  multiple parallel calls share a large cached prefix (a corpus, a big
  system block), that shared content must come *before* any per-call unique
  text, and the very first call should complete before the rest fire — a
  parallel burst with no warm cache entry yet all pay full price. Silent
  failure mode: cache-write cost is large and cache-hit cost is zero, which
  reads like caching isn't configured when it actually just fired too late.
- **Free-form dict outputs from an LLM come back empty or wrong-shaped more
  than named fields do.** If you need several numbers back from a model call,
  ask for named fields, not `dict[str, float]` — the model will happily
  write the numbers into prose instead of the structure you asked for.
- **A citation that points at a document is not a quote from that document.**
  An index/pointer-style claim (e.g. "filing X exists, accession Y") will
  fail any string-match verification against the document it merely
  references. Treat "points at a source" and "quotes a source" as two
  different claim types.
- **Units.** Millions vs. thousands is the error most likely to slip through
  silently, because the arithmetic stays internally self-consistent — only a
  sanity check against known YoY growth ranges tends to catch it.
- **Percentile/winsorize indexing.** `int(p * n)` is not a valid percentile
  index into a zero-indexed array of length `n`; it's `int(p * (n - 1))`. Get
  this wrong and winsorizing silently no-ops.
- **Confidence intervals at the edges.** A naive (Wald) CI reports zero width
  when a proportion hits 0 or 1, which is wrong when the sample is small.
  Use a Wilson interval instead.

## Day-of execution checklist (compress to whatever window you're given)

Ordered by risk, not by pipeline stage — do the risky, unknown-until-the-day
things first while there's still time to recover from a surprise:

1. Write down the scoring metric verbatim, first thing. Design every
   downstream decision to be legible against that specific metric.
2. Build the sponsor `DataSource` adapter per the contract above; smoke-test
   it standalone against one real ticker before wiring it in.
3. Run the full chain end-to-end once, even in a degraded/minimal form.
   Not green quickly → escalate (mentor, teammate) rather than debug solo
   for long; a working minimal path beats a broken ambitious one.
4. Spend the middle of the day on the two things with the most leverage per
   minute: (a) getting λ fit on whatever real cases you can afford, (b)
   making sure the baseline (§ invariant 6) is correct and always shown,
   since it's both a safety net and a judging asset.
5. Set a hard freeze time with real margin before the deadline — no logic
   changes after it, presentation/rehearsal only.
6. Before the freeze, confirm the replay/fallback path works cold, and
   screenshot every screen/output you'd want if live data dies mid-demo.
7. Rehearse the presentation at least twice, timed.

## If told existing code can't be used

Everything above this line is safe to use regardless — it's understanding,
not artifact. If starting a genuinely fresh repo:

- Don't try to rebuild the full lens ensemble. The **baseline** (shrunk
  consensus tilt) and a **clean point-in-time data adapter** are the two
  highest-value, lowest-effort pieces and are themselves already a
  legitimate, defensible entry.
- Add at most one or two independent lenses beyond that if time allows,
  rather than attempting the full set — a smaller ensemble built correctly
  beats a large one built carelessly under time pressure.
- Keep the invariants (point-in-time, provenance, lens blindness,
  materiality-weighting) even in a minimal build — they're what makes the
  result defensible to a judge asking "how do you know this number is real,"
  and they cost little extra to hold onto even at small scope.
