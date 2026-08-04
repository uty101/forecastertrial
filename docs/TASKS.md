# Task board

Live status. Update as things land, and keep the counts at the top honest —
`docs/build-status.html` is generated from this.

Legend: `[x]` done & tested · `[~]` written, never run against live data ·
`[s]` stubbed, right shape no logic · `[ ]` not started

---

## Stage 1 · Foundations — 14/16

- [x] `schemas.py` — the contract; UI types generate from it
- [x] `data/protocol.py` — DataSource, `as_of` on every method, None-tolerant
- [x] `data/cache.py` — content-hash, `as_of` in the key, read-only mode
- [x] `data/loader.py` — priority fallback, circuit breaker, disagreement log
- [~] `data/sec_source.py` — XBRL + filings, point-in-time filter — **UNVERIFIED**
- [~] `data/yfinance_source.py` — consensus, trend, revisions — **UNVERIFIED**
- [x] `model/graph.py` — topological evaluator, per-cell provenance
- [x] `pipeline/e_lenses/mechanical.py` — FX, share count, interest, calendar
- [x] `pipeline/v1_reconcile.py` — arithmetic + citation verification
- [x] `pipeline/h_lambda.py` — three presets, regime conditioning
- [x] `eval/shrinkage.py` — James-Stein, winsorize, MAD, guide landing
- [x] `eval/baseline.py` — consensus × shrunk company tilt
- [x] `eval/backtest.py` — MAE, skill, Wilson CI, run spread, ablation
- [x] `events.py` — append-only NDJSON, the UI's only interface
- [x] `cli.py`, `tools/`, `Makefile`, `Dockerfile`, CI, `README.md`
- [x] 50 tests

## Block 1 · The gate — Sat 1 – Sun 2 Aug — 0/8

**Nothing downstream means anything until the baseline number exists.**

- [ ] **Run `forecast sources --ticker NVDA` from the demo machine** ← do this first
- [ ] GAAP↔non-GAAP bridge verified **by hand** on 10 companies (spreadsheet, no code)
- [ ] Build ~200 firm-quarter cases with point-in-time consensus + actuals
- [ ] **Score `consensus × 1.02` — this is THE number**
- [ ] Fit `actual ~ α·consensus + β·own`; replace `FITTED_BETA` placeholders
- [ ] Guide-landing distributions, 8 quarters × ~20 names
- [ ] Golden file + `make verify` green in CI
- [ ] Pin the Dockerfile base digest (currently `PINME`)

## Block 2 · Evidence & first lenses — Mon 3 – Fri 7 Aug — 0/6

- [ ] `llm/client.py` — prompt caching, cost ceiling, token accounting, seeding
- [ ] `pipeline/c_structure.py` — evidence store assembly from acquired claims
- [ ] Guidance extractor — 8-K EX-99.1 → `{metric, period, low, high, basis, quote}`
- [ ] 3-statement model — IS/BS/CF linked on `model/graph.py`, unit-tested
- [ ] Lens: Guidance (prompt exists at `llm/prompts/lens_guidance.yaml`)
- [ ] Lens: Drivers

## Block 3 · Rest of the pipeline — Sat 8 – Sun 9 Aug — 0/7

- [ ] Lens: Margins
- [ ] Lens: Forensics
- [ ] Lens: Peer read
- [ ] Lens: Macro + `data/fred_source.py`
- [ ] `pipeline/f_champion.py` — argue for, then against
- [ ] `pipeline/g_judge.py` — impact-weighted, outputs a distribution
- [ ] **Full backtest, 5 runs per config, leave-one-out ablation**

> **Checkpoint Sun 9 Aug:** do we beat `consensus × 1.02`, and on which kinds of
> names? If not, go back to the eval and find out why. Do not add components.

## Block 4 · UI & production — Mon 10 – Thu 13 Aug — 0/9

- [ ] `pipeline/v2_comparability.py` — M&A, accounting change, 53rd week
- [ ] `pipeline/v3_calibrate.py` — bootstrap backtest residuals by regime
- [ ] Statistics: lens combination weights (inverse out-of-sample MSE)
- [ ] UI: live architecture view (hand-authored SVG, not React Flow)
- [ ] UI: forecast + distribution + consensus marker
- [ ] UI: reasoning trace, claims clickable to quotes, failed citations in red
- [ ] UI: model view with per-cell provenance on hover
- [ ] UI: eval — backtest vs baseline, calibration diagram, ablation
- [ ] Replay mode (`?replay=`) — the demo fallback

## Blocks 5–6 · Rehearse — Fri 14 – Sat 15 Aug — 0/6

- [ ] Fresh-clone test on a different machine, one command → forecast
- [ ] Pre-cache to parquet: yfinance universe, SEC bulk quarters, transcripts
- [ ] Rehearsal 1 — Micron (highest-variance name in the window)
- [ ] Record the fallback event log + screenshot every screen
- [ ] Rehearsal 2 — FedEx (two-sided surprise tails)
- [ ] Write and rehearse the 3-minute demo, timed, twice. **Stop by 18:00.**

## Day-of · Sun 16 Aug

- [ ] 10:00–10:30 intro — **write the scoring metric down verbatim**
- [ ] 10:30–11:00 write `data/sponsor_source.py`
- [ ] 11:00–11:30 smoke test end to end — not green by 11:30, grab a mentor
- [ ] 11:30–13:00 tune to the real companies
- [ ] 13:30–15:30 calibrate λ, 5 runs
- [ ] **15:30 HARD FREEZE** — no more logic changes
- [ ] 15:30–17:30 presentation only. Screenshot everything at 17:00
- [ ] 17:30–18:00 rehearse twice
