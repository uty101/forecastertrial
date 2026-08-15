---
name: forecaster-data-model-core
description: Knowledge reference for the earnings-forecaster's deterministic backbone — data sources, acquisition, evidence store, the 3-statement model, and the V1/V2/V3 validators (reconcile, comparability, calibrate) plus lambda blending. Use when implementing the non-LLM plumbing the lenses/judge sit on top of. No source code included. Companion to forecaster-playbook, forecaster-lenses, forecaster-champion-judge.
---

# Data, model, and validators — the deterministic backbone

Everything here is plain code, deliberately. Prefer deterministic logic over
an LLM call wherever the task is arithmetic or lookup — the fact that the
Mechanical lens (see forecaster-lenses) has no model in it is a feature, and
the same logic applies to this whole layer.

## Sources → loader → cache

Each data source is an adapter behind one shared interface: every method
takes an explicit `as_of`, tolerates "no data yet" by returning empty/None
rather than raising, and must refuse to return anything filed or restated
after `as_of`. This is the point-in-time contract — see forecaster-playbook
for why it's non-negotiable.

A **loader** sits above the adapters with priority fallback across sources
(try the best source first, degrade gracefully), a circuit breaker (stop
hammering a source that's failing), and a disagreement log (when two sources
give different numbers for the same fact, record it rather than silently
picking one — that disagreement is itself a data-quality signal downstream
stages may want).

A **cache** keyed on content-hash plus `as_of` sits below the loader, with a
read-only mode for replay. Two adjacent failure modes to design around: (1) a
cached/replay path that skips real acquisition entirely, which means any bug
in the acquisition layer is invisible until a cold run — run cold at least
once before trusting any change near this layer; (2) unbounded cache growth
under repeated real-world use, which a demo-day build can ignore but a
production deployment cannot.

## Acquisition

Pulls numbers, filings, guidance, and time series for one company/period, in
parallel, under a hard cost/time budget per run. When a budget is spent,
**log exactly what was skipped** — silent truncation reads to a judge or a
future debugging session as "we covered everything," which is a worse failure
than an honest partial run.

## Evidence store

The landing zone for everything the extractors (see
forecaster-extractors-scanners) produce: discrete, sourced, quotable claims,
each with an ID, a value, a source document reference, and a verbatim quote.
Nothing downstream — no lens, no model, no judge — reads a raw document
again after this stage. A claim that can't cite a real quote from a real
source shouldn't be constructable at all; treat "no claim" as a valid, honest
state and "a claim with no source" as a bug, never the reverse.

One claim-type distinction worth keeping from day one: a claim that merely
*points at* a document (e.g. "this filing exists, here's its accession
number") is not the same as a claim that *quotes* one. String-matching a
pointer-type claim against the document it points at will always fail,
because there's nothing to match — keep these as two distinct claim kinds so
citation verification doesn't wrongly reject legitimate index-level claims.

## The 3-statement model

A deterministic, ratio-based model (income statement / balance sheet / cash
flow, linked) that produces a mechanical base case with **no LLM involved.**
Its real value is diagnostic as much as predictive: run it against past
quarters and measure its own structural error, so later stages know how much
to trust "the model says X" versus "a lens says X." Track provenance per
output cell if at all feasible — when a number looks wrong days later, being
able to trace which inputs produced it is the difference between a five-minute
fix and an afternoon of re-deriving the model by hand.

## V1 — reconcile

Runs after every lens: checks arithmetic and, critically, **string-matches
every citation against the actual source document text it claims to quote.**
A lens that fails this is dropped from the ensemble entirely, logged, and
surfaced — never silently down-weighted, never retried into the same run.
This is the gate that keeps "no number without provenance" from being a
slogan instead of an enforced property.

## V2 — comparability

Checks whether this quarter can even be compared to the company's own
history: M&A that changed what's being measured, an accounting-policy change,
a 53rd week or other calendar irregularity. When this fires, it should
collapse λ toward zero for the affected case — everything upstream leans on
historical patterns holding, and when they don't, the system should become
*less* confident, not proceed as if nothing changed.

## H — lambda (the blend)

```
forecast = consensus + λ · (own_estimate − consensus)
```

λ is regime-conditioned (coverage count, dispersion, staleness, internal
lens disagreement, the V2 comparability flag) and **must be fitted on
backtest data, not asserted** — a placeholder λ should be labeled as such
everywhere it's used, not treated as a tuned parameter. On a heavily-covered,
low-dispersion name, λ shrinking toward zero is the system working correctly,
not a null result to be embarrassed about.

## V3 — calibrate

Bootstraps the forecast's uncertainty width from the system's *own* backtest
residuals rather than assuming a distribution shape (e.g. a fixed-width
normal band). A band that's never been checked against how wrong this exact
pipeline actually tends to be is decoration, not a confidence interval.

Two statistics traps worth holding onto anywhere probabilities or intervals
get computed: (1) a percentile index into a zero-indexed array of length `n`
is `int(p * (n-1))`, not `int(p * n)` — the off-by-one silently makes
winsorization a no-op; (2) a naive (Wald) confidence interval reports zero
width at a proportion of exactly 0 or 1, which is wrong for small samples —
use a Wilson interval instead.

## When building fresh (no prior code)

This layer — sources/loader, evidence store, the 3-statement model, and V1
reconcile — is the highest-leverage thing to build well even under severe
time pressure, because the baseline (`consensus × shrunk company tilt`) is
computable from it alone, without a single lens or LLM call. A correct
deterministic backbone plus the baseline is a complete, legitimate,
defensible entry on its own; a flashy lens ensemble sitting on a shaky data
layer is not.
