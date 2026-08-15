---
name: forecaster-ui
description: Knowledge reference for the earnings-forecaster's UI — a 9-sheet Next.js static export that reads pipeline output off disk, no API layer. Use when building or extending a sheet, or wiring the UI to new pipeline output. Reflects the current sheet index and design-system vocabulary as of the last UI update. No source code included. Companion to forecaster-orchestrator.
---

# The UI — nine sheets, no server

## The contract that shapes everything else

There is **no API between the pipeline and the UI.** The Python side writes
`out/*.json` and an append-only `out/events.ndjson`; the Next.js side polls
and reads those files. No server process, no ports. This is what makes replay
mode free: a recorded event log played back through the identical rendering
code is the demo's fallback if a live run or a live API dies mid-presentation
— not a separate video or a mocked-up screenshot deck. Any new sheet or
component must keep this property: read from the on-disk JSON/NDJSON
contract, never assume a live backend.

Because of this, backend and UI work can genuinely run in parallel: fix the
output JSON shape early, then a UI build only needs fixture data matching
that shape — it does not need a working pipeline behind it to make visible
progress.

## The sheet index — one source of truth

The UI is organized as nine numbered "sheets," each independently routable,
with the numbering and nav order defined in exactly one place so the "N/9"
readout in every title block can't drift from the actual route list. As of
the last update:

1. **System** (`/`) — the architecture diagram and the live run, merged into
   one screen with an overlay switch (build-state / live-state / a third
   overlay) rather than two separate tabs. This used to be two screens; they
   were merged because splitting "is this box tested?" from "is this box
   running right now?" forced switching screens mid-question, which is a
   worse experience than one drawing with a toggle.
2. **Forecast** (`/forecast/`) — the headline number: forecast vs. consensus,
   as a distribution, not a point.
3. **Reasoning** (`/reasoning/`) — the trace that wins on substance: each
   lens's thesis AND its counterargument, expandable, with claims clickable
   through to their source quotes.
4. **Model** (`/model/`, with sub-sheets for income/balance-sheet/cash-flow/
   DCF) — rendered as actual financial statements, not a raw cell/dependency
   dump, because a judge recognizes an income statement on sight and does not
   recognize a dependency graph.
5. **Risk** (`/risk/`) — deviation from consensus and what that implies for
   capital/position sizing, framed the way a trading system's risk sheet
   would be, not as generic model uncertainty.
6. **Method** (`/eval/`) — backtest vs. baseline, calibration diagram,
   ablation — what the "best architecture" judging criterion is actually
   assessed against, so this sheet should be legible to someone who has never
   seen the pipeline before.
7. **Agents** (`/agents/`) — the agent roster, read from a JSON file the CLI
   *generates from the prompt files themselves* rather than hand-maintained.
   Keep this indirection in any rebuild: a roster maintained by hand drifts
   from what actually runs and ends up confidently describing a system that
   no longer exists. Prompt version numbers travel with it, so any backtest
   number can be traced back to the exact prompts that produced it.
8. **Cost** (`/cost/`) — token/cost allocation across the run, per stage.
9. **Integrity** (`/integrity/`) — the two claims the whole system rests on,
   made checkable rather than asserted: no number exists without a source,
   and nothing filed after the lock date was visible. This sheet should make
   both of those verifiable by a skeptical judge in under a minute, not just
   claim them in prose.

## Design-system vocabulary (reuse these concepts, not necessarily these exact names)

A shared set of primitives keeps all nine sheets reading as one system rather
than nine separately-designed pages:

- A **panel/sheet frame** wrapping every screen with a consistent title block
  (including the "N/9" position readout described above).
- A **lede** — one or two sentences at the top of a sheet stating what it's
  for, written for a judge seeing it cold.
- **Stat** tiles for headline numbers, **Pill**s for short status/category
  tags, a **Dimension** component for labeled metric rows.
- A **StatusPanel** and per-stage **StageStrip** for showing pipeline stage
  state (not-started / running / done / failed) inline wherever relevant,
  not just on the system sheet.
- A **Callout** for a single emphasized point, a **Disclaimer** for caveats
  that need to be visible but not loud, an **Empty** state for "this
  hasn't run yet" (which will happen constantly during rehearsal), and a
  **SyntheticBanner** for clearly marking any placeholder/fixture data as
  not-real — never let synthetic and live data look visually identical.
- A **SheetFooter** for consistent per-sheet metadata (timestamps, run ID).

Larger composed components sit on top of these primitives: an org-chart-style
architecture diagram with overlay modes, a live-run visualization reading the
event stream, a "lens constellation" for the reasoning trace, and a
statement-rendering component that lays financial statements out the way an
analyst actually expects to see them (proper line-item hierarchy, not a flat
grid).

## Two routes outside the numbered sheet index

`ui/app/live/` and `ui/app/narrative/` both exist and are real, working
routes, but neither appears in `ui/lib/sheets.ts` — the "one source of
truth" the sheet numbering is built from. That's either intentional
(purpose-built utility screens: a stripped projector-only live view, a
print-friendly takeaway page — both legitimate reasons to sit outside the
numbered flow) or it's the exact kind of drift `sheets.ts`'s own comment
warns about. See `hackathon-ui-presentation-layer` and
`hackathon-narrative-generation` for what each route does, and resolve which
case it is deliberately rather than by accident — the project's most recent
commit before this build session was specifically about two generated files
having drifted from their sources, so this pattern has already bitten once.

## When building fresh (no prior code)

Priority order: get sheets 2 (Forecast), 3 (Reasoning), and 9 (Integrity)
working against fixture JSON first — those three carry the most demo and
judging weight (the number, why it's the number, and proof the number is
real). Sheet 1 (System diagram) is high visual impact but not load-bearing
for either judging criterion directly; build it after the three above are
solid, not before. Keep the "no API, read from disk" contract from the very
first line of code — retrofitting it later means rewriting the data-access
layer of every sheet at once.
