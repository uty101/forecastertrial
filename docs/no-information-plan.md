# Planning with no answers

Assume you learn nothing before 10:00 on the 16th. Six unknowns. Two you can resolve by reasoning; four you engineer around. None of them should cost you more than sixty seconds on the day.

---

## First — two you can answer yourself

**"Which actual do they score against?"** — almost certainly **non-GAAP / street.** They've said publicly they compare agent forecasts to *both* the reported result *and* Wall Street consensus. Consensus is universally non-GAAP. A scoring system that compared a non-GAAP consensus to a GAAP actual would show every company missing by ~12% every quarter and would be visibly broken. So: **default to non-GAAP, and carry the GAAP figure alongside** (below).

**"How many companies?"** — the invite says *"companies reporting shortly afterwards,"* plural, and the event page says *"your companies report."* Plan for **N ≥ 1, design for N**. If they hand you one, run deeper on it; if five, the token allocator ranks them.

That leaves four genuine unknowns.

---

## The four, and how you engineer around each

### 1 · The scoring metric — the big one

**Solution: produce a distribution, and precompute a λ preset per metric family.** Then the metric stops being a design input and becomes a config value you set at 10:30.

A distribution is a strict superset. From it you can emit a median, a mean, quantiles, or a directional call. Build that once and every metric is downstream of it.

Backtest **three λ presets** during prep, so all three have known performance before you arrive:

| Preset | For | Behaviour |
|---|---|---|
| **`shrink`** | MAE · MAPE · MSE · anything absolute-error | λ = fitted β (expect 0.1–0.25). Emit median (or mean under squared error). Small positive base-rate tilt. |
| **`barbell`** | skill score vs consensus, especially floored at 0 · rank-based leaderboards | λ high on the top-confidence names, λ = 0 everywhere else. No credit for matching consensus means matching it is pure downside. |
| **`calibrated`** | CRPS · pinball · anything probabilistic | Emit full quantiles. Optimise interval calibration, not the point. Do **not** hedge with wide intervals — CRPS punishes that specifically. |

Plus one behaviour that isn't a preset: **if the metric is win-rate vs consensus** (% of names where you were closer than the Street), λ→0 scores exactly zero. You *must* deviate — but only by a hair, and only in the right direction. Magnitude is irrelevant; direction is everything. Flag `--tiny-tilt`: deviate by the minimum meaningful increment, direction set by the single highest-confidence lens.

**Also ask at 10:30 what happens near zero EPS.** If they use MAPE, one company reporting $0.01 against your $0.03 is a 200% error that can dominate the entire leaderboard. If that's the rule, your risk management is about that one name, not the other four.

### 2 · What data they provide

**Solution: your stack is the baseline; theirs is an override.**

Everything behind the `DataSource` protocol, with a complete working yfinance + SEC implementation. On the day the only new code is `sponsor_source.py`, and it only has to implement the methods their feed actually improves. If their feed is thin, you shrug and use yours. If it's rich — particularly if it includes consensus you couldn't otherwise get — you swap it in for those methods only.

**Design the protocol so partial implementation is normal:** each method returns `None` for "I don't have this" and the loader falls back to the next source in priority order. Then a half-working adapter written in twenty minutes is still useful, and you're never blocked on making theirs complete.

### 3 · Which companies

**Solution: nothing is ticker-specific.** Everything keys off the ticker → CIK → filings. Prep against the 26–27 August cluster (NVDA, SNOW, CRWD, DELL, MRVL, HPQ, ADSK, BBY, DG, ULTA) plus MU and FDX as the high-variance cases, and if they assign something else it's the same code path.

**One thing to prepare that is company-specific:** a small YAML of driver definitions for ~20 likely names (what units × what price, which segments matter). If your company is in it, the Drivers lens starts warm. If not, it derives them from the 10-K — slower, still works.

### 4 · Pre-existing code allowed?

**Low risk, but hedge cheaply.** OpenStocks' verified tier requires submission via GitHub with them executing your agent — that only makes sense if pre-built repos are expected. And the event copy says *"we bring the data, API credits and tooling so you're building within the first half hour"*, which is an organiser expecting you to arrive ready.

The hedge costs nothing: **keep the repo public with clean, timestamped commits.** Then "here's what existed at 10am, here's what we built today" is a `git log`, not a claim. That's a better position than most teams will be in, and it converts a possible awkward question into a credibility moment.

---

## The decision card — carry this

One page, printed or on your phone. At 10:30 you make four choices in under a minute.

| Heard | Do |
|---|---|
| **MAE / MAPE / absolute error** | `--preset shrink` · emit median · check the near-zero-EPS rule |
| **MSE / squared error** | `--preset shrink --lambda-scale 0.7` · emit mean |
| **Skill score vs consensus** | `--preset barbell` · λ high on top-2 confidence names only |
| **% closer than consensus (win rate)** | `--preset barbell --tiny-tilt` · direction over magnitude |
| **CRPS / pinball / "submit a range"** | `--preset calibrated` · full quantiles · don't widen to hedge |
| **They won't say** | `--preset shrink` · emit median **and** quantiles · submit both if the form allows |

| Heard | Do |
|---|---|
| **"Actual" is non-GAAP / street / adjusted** | default — no change |
| **"Actual" is GAAP** | `--basis gaap` · the bridge is already modelled, flip the flag |
| **They won't say** | non-GAAP, and say so explicitly in the submission |

| Heard | Do |
|---|---|
| **1 company** | full depth · all 7 lenses · expensive tier throughout · k=5 runs |
| **2–5 companies** | token allocator ranks by consensus weakness · deep on the 2 weakest |
| **6+** | drop to 4 lenses · `shrink` preset regardless · this is now a throughput problem |

| Heard | Do |
|---|---|
| **Their feed has consensus** | swap `get_consensus()` only · keep yours as the cross-check and **flag any disagreement** |
| **Their feed is thin / broken** | ignore it, run on yours, mention it in the demo as designed-for failure |

---

## What this changes in prep

Four additions, roughly a day total:

- [ ] **Model both bases.** Every forecast carries `eps_gaap` and `eps_nongaap` with the bridge between them as an explicit, cited object. This is the highest-value item here — it turns your biggest unknown into a flag.
- [ ] **Backtest all three λ presets**, not one. You want a known number for each before you arrive, so the 10:30 decision is informed rather than a guess.
- [ ] **`--companies` takes a list.** Test N=1 and N=5 paths in the dress rehearsals — one each.
- [ ] **`DataSource` methods return `None` gracefully** and the loader falls back in priority order. Write the fallback test.

---

## The thing this actually buys you

Every other team spends the first hour of the day arguing about what the metric implies and rewriting their aggregation logic. You spend sixty seconds setting flags and go straight to the adapter.

It's also worth a line in the demo, because it *is* an architecture point: **"we didn't know the scoring rule until this morning, so we built the system to be agnostic to it — here's the same pipeline optimised three different ways, and here's how each performs on the backtest."** That's a stronger answer than having guessed right.
