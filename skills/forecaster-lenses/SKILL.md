---
name: forecaster-lenses
description: Knowledge reference for building the earnings-forecaster's analytical lenses — the 9 independent viewpoints (1 deterministic, 8 LLM-driven) that each produce an EPS/revenue view before anything is compared. Use when implementing, prompting, or reviewing a lens agent. No source code included — contracts and reasoning only. Companion to forecaster-playbook and forecaster-orchestrator.
---

# The lenses

Nine independent analytical viewpoints on the same quarter. One is pure code
(Mechanical); eight are LLM-driven. Every lens shares the same evidence corpus
and the same output contract, and **must never see another lens's output**
before forming its own view — that's what makes disagreement between them
meaningful signal rather than noise.

## Why blindness matters more than any individual lens's cleverness

If lens B can read lens A's conclusion, B's estimate stops being independent
evidence and starts being A's estimate with B's confidence stapled on. Run
them so that's structurally impossible: separate calls/contexts, one shared
read-only evidence store as the only common input, nothing else crossing
between them. A judge stage downstream is where their views get compared —
never earlier.

## The shared output contract

Every lens returns **named fields**, not a free-form dict — a model asked for
`quantiles: dict[str, float]` will write the numbers into prose instead of the
structure half the time; five explicit named fields come back filled every
time. At minimum, a lens output needs:

- a point estimate (EPS and/or revenue) with its accounting basis tagged
  (GAAP vs non-GAAP — never leave this implicit)
- a confidence score
- the reasoning text
- the list of claim IDs it actually cited — an empty list here is either an
  honest abstention (no evidence found) or a prompt-adherence failure, and
  those look identical unless you check whether evidence existed
- a thesis and a counterargument slot, filled by the champion stage, not the
  lens itself — the lens states its case; attacking it is a separate step

A lens that raises an error, or whose citations fail reconciliation, is
**dropped and logged with its reason** — never retried into the ensemble,
never silently omitted. The judge needs to know a lens is missing, because an
ensemble that quietly shrinks changes what its weights mean.

## Fan-out mechanics (this is a correctness issue, not a performance detail)

Run one lens **alone first**, let it complete, then fan the rest out in
parallel behind it. If all lenses fire simultaneously against a shared cached
prefix (the evidence corpus), every one of them misses the cache — the entry
only exists once a request that wrote it has returned — so all pay full
price and none benefit from caching at all. Serializing the first call costs
some wall clock and saves most of the run's cost. Symptom if this is wrong:
cache-write cost is large on every lens and cache-read cost is zero on all of
them, which looks like caching isn't configured when it actually just fired
too late.

Results must be sorted into a deterministic order before returning, independent
of which thread finished first — otherwise identical inputs can produce
byte-different output ordering, which breaks any golden-file/replay comparison
for a reason that has nothing to do with the actual pipeline logic.

## The 9 lenses

**Mechanical** (deterministic, no LLM, runs in microseconds) — FX translation,
share count roll-forward (buybacks/issuance), net interest expense, and
calendar effects (quarter length, fiscal calendar shifts). This is the one
lens with no model in it, and that's intentional: pure arithmetic gets pure
arithmetic, not a language model guessing at arithmetic. It has a different
input shape than the other eight and is called directly rather than fanned
out with them, but joins the same ensemble downstream.

**Guidance** — anchors on what management explicitly guided for *this*
quarter on the last earnings call, then adjusts for how this specific company
historically lands inside its own guided range (some companies sandbag
consistently, some don't). Usually the single highest-signal input in the
whole system — a direct company statement beats any inferred view.

**Drivers** — bottom-up revenue build from operating metrics rather than
extrapolating the revenue line itself: units × ASP, subscribers × ARPU,
comps × store count, backlog conversion rate — whatever the company's actual
unit economics are.

**Demand** — reads one link up and one link down the value chain. A major
customer's disclosed capex budget IS this company's revenue, just reported on
a different calendar; a key supplier's order book leads this company's
shipments. This is evidence consensus often hasn't fully priced in because
it requires reading a *different* company's filings.

**Market** — separates market growth from share change, which consensus
almost never splits out as two numbers. A company growing 60% in a market
growing 55% is riding a wave; one growing 60% in a market growing 8% is
taking share — very different implications for durability.

**Margins** — takes the top line as given from elsewhere and argues about
what falls through it to EPS: gross margin mix shift, opex trajectory,
headcount, tax rate, below-the-line items.

**Forensics** — reads as an auditor, not a forecaster: accruals vs. cash
conversion, DSO and inventory trend, and changes in what management excludes
from non-GAAP figures (an expanding exclusion list is itself a signal). The
lens most likely to disagree with the rest — which is why it's included, not
despite it.

**Peer read** — who else in the same value chain has already reported this
cycle, and what did they say? Consensus frequently hasn't caught up to a
peer's print yet; that lag is the entire edge this lens is exploiting.

**Macro** — sector-relevant macro series compared against what analyst
estimates appear to implicitly assume. There's real evidence the gap between
macro conditions and analyst assumptions predicts a meaningful share of
same-quarter analyst error.

## When building fresh (no prior code)

Priority order if time-constrained: Mechanical (cheap, deterministic, always
build it) → Guidance (highest single-lens signal) → Margins or Drivers
(whichever fits the company type — margins for a mature/profitable name,
drivers for a unit-economics-driven one) → stop there if time is short. A
3-lens ensemble built correctly, with real blindness and real citations,
beats a 9-lens ensemble where half silently abstain or secretly share context.
