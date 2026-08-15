---
name: forecaster-champion-judge
description: Knowledge reference for the earnings-forecaster's champion (argue-for-then-against) and judge (materiality-weighted aggregation) stages — the two agents that turn 9 independent lens views into one forecast distribution. Use when implementing aggregation logic. No source code included. Companion to forecaster-lenses.
---

# Champion and judge

The two stages that turn independent lens views into a single forecast.
Together they exist to prevent the single most common failure mode in
ensemble-of-analysts systems: **picking the most frequent finding instead of
the most material one.**

## Champion — develop each case, then attack it

Runs once per surviving lens (post-reconciliation), and does two passes in
order, and the order matters:

**Pass 1 — thesis.** State the strongest honest version of this lens's
analysis — not necessarily the version it originally wrote, but the version
its own reasoning supports with more scrutiny applied. Make the causal chain
explicit: this evidence → this mechanism → this effect on EPS, quantified.

**Pass 2 — counterargument.** Attack the case just built. What would have to
be true for this thesis to be wrong? Is the evidence stale, thin, or drawn
from a source that itself has an incentive to shade one direction? This pass
is what took a comparable reference system from a weak baseline to a strong
one — comparing raw lens findings and taking whichever is most common, without
this adversarial step, is the known failure mode.

Critically: champion development happens **before any lens is compared to
another.** Each case is built and attacked entirely on its own merits first.
Comparing already lets weaker cases borrow credibility from stronger ones
just by sitting next to them in the same context.

## Judge — one expensive call, weighted by materiality, outputs a distribution

Takes every surviving case (thesis + counterargument for each) and decides
what the evidence actually supports. The rule that matters most, stated
explicitly because it's a documented failure mode, not a stylistic
preference: **weigh by materiality, never by agreement count.**

Why agreement is weak evidence here specifically: lenses read overlapping
source documents, so their errors are correlated. Six lenses independently
"agreeing" on a weak signal is not six independent confirmations — it's one
weak signal seen from six angles that all had access to the same limited
evidence. One lens carrying the company's own guidance with a verbatim quote
should outweigh six lenses agreeing on something inferred. Any aggregation
logic that averages, takes a plurality, or otherwise counts votes is wrong by
construction — this is the one invariant that most directly encodes the
system's actual thesis.

The judge's output is a **distribution, not a point** — named quantiles, a
median, a mean, explicitly not a single number pretending to be precise. It
is also told which lenses were dropped and why (reconciliation failure,
runtime error, budget cut) — an incomplete ensemble should read as
incomplete, never as if the missing lenses simply agreed with the rest.

This is the single highest-leverage LLM call in the pipeline: everything
upstream is inputs to one decision. Spend the best model tier here even if
everything else runs cheap.

## When building fresh (no prior code)

If only building 2-3 lenses (see forecaster-lenses' fallback guidance), keep
both stages anyway, just scaled down — champion-then-attack on 2 lenses and a
materiality judgment between them is still meaningfully better than averaging
2 numbers, and it's cheap to keep even at small scope. Don't drop this pair
to save time; it's higher leverage than adding a 4th or 5th lens.
