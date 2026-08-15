---
name: forecaster-extractors-scanners
description: Knowledge reference for the earnings-forecaster's extraction and scanning agents — the 4 cheap-tier LLM agents that turn raw filings/calls/coverage into structured evidence BEFORE any lens or model runs. Use when implementing the evidence-population stage. No source code included. Companion to forecaster-lenses and forecaster-data-model-core.
---

# Extractors and scanners

Four cheap-tier agents whose job is turning unstructured source material into
structured, citable claims in the evidence store — nothing downstream should
ever re-read a raw document. All four share one design line: **extraction
only, no forecasting, no opinion.** An extractor that starts interpreting
what a number *means* has quietly become a lens with worse citations than
the real ones.

## Bridge extractor (GAAP ↔ non-GAAP reconciliation)

Pulls the non-GAAP reconciliation table out of an earnings release — the
table (usually near the back, titled something like "Reconciliation of GAAP
to Non-GAAP") that every US company reporting a non-GAAP figure is required
to disclose. This exists because the GAAP/non-GAAP gap can be large (double
digits, percent) and directional: get the basis wrong and every downstream
number misses in the same direction, every time, looking exactly like a
modelling bug rather than a units-of-comparison bug. Every EPS-shaped number
in the system should be traceable to this extraction for its basis tag.

## Guidance extractor (8-K EX-99.1 → structured guidance)

Turns forward-looking statements in a release or call transcript into
structured fields: metric, target period, low/high/point, basis, whether it's
constant-currency, and the verbatim quote it came from. What counts as
guidance is narrow and deliberate: a statement about a *future* period
("we expect Q3 revenue of $44.0B ± 2%"), not a statement about the quarter
just reported. Prior-quarter guidance is one of the strongest single
predictors of the coming print, and it lives in prose — nothing upstream of
this extractor can see it at all.

## Call-sequence scanner (cross-quarter earnings-call diff)

Reads several consecutive quarters of earnings calls *together* and reports
what changed across them — not a summary of the latest one. The signal here
is disclosure withdrawal: a metric management used to volunteer and has quietly
stopped mentioning is informative precisely because it's invisible in any
single call read in isolation. This only works as a sequence-comparison task;
summarizing the most recent call throws the actual signal away.

## Perception scanner (press/analyst coverage stance)

Scores coverage for stance and conviction — not a polarity/sentiment word
count, because publication volume spikes before every print regardless of
which direction it goes, so raw volume or polarity counts measure attention,
not belief. The question this answers is: what does the market currently
believe about this company, and how firmly, so a downstream stage can tell a
contested story (lenses should disagree, uncertainty is real) from a settled
one (lenses agreeing is expected, not informative).

## Where these feed the pipeline

All four populate the evidence store that lenses read from — they run
*before* the lens fan-out, not concurrently with it, since lenses depend on
the claims these produce having citable IDs already assigned. They're all
cheap-tier because the task is extraction, not judgment — spend model quality
on the judge call, not here.

## When building fresh (no prior code)

If time-constrained, the guidance extractor and bridge extractor are the two
that unlock the most downstream value per unit effort — guidance is the
Guidance lens's entire input, and the GAAP/non-GAAP basis tag prevents the
most common silent, directional error in the whole system. The two scanners
are lower priority for a minimal build; skip them before skipping either
extractor.
