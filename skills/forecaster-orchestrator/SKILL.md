---
name: forecaster-orchestrator
description: The build orchestrator for the earnings-forecasting agent under hackathon time pressure. Invoke this FIRST tomorrow. Reads the companion knowledge skills (forecaster-playbook, forecaster-lenses, forecaster-extractors-scanners, forecaster-champion-judge, forecaster-data-model-core, forecaster-ui), determines what's already usable vs. what needs building, and drives parallel subagent builds of each component in dependency order. Use when starting or resuming the day-of build.
---

# Build orchestrator

This skill is the entry point for the day-of build. It does not contain the
domain knowledge itself — that lives in the companion skills below — it
contains the **build plan and the rules for running it as parallel agents.**

## Step 0 — establish the constraint, once, before anything else

Before spawning any subagent, confirm (ask the user if not already
established this session): **is code that pre-dates the event allowed?**
This changes Step 1 below and nothing else — the companion skills are
knowledge documents either way and are always safe to hand to a subagent.

- If prior code is allowed: subagents may read and adapt this repo's actual
  source under `src/forecaster/` and `ui/` as reference alongside the
  relevant companion skill.
- If prior code is not allowed: subagents get **only** the companion skill
  file for their component, explicitly instructed to implement fresh and not
  open `src/forecaster/` or `ui/` at all. Say this explicitly in every
  subagent prompt in that case — don't rely on the subagent inferring it.

## The companion skills (read the ones relevant to what you're building)

| Skill | Owns |
|---|---|
| `forecaster-playbook` | Thesis, invariants, traps, day-of checklist — read this one yourself, don't just hand it to a subagent; it's the judgment layer that should shape every other decision today. |
| `forecaster-data-model-core` | Sources/loader/cache, acquisition, evidence store, 3-statement model, V1/V2/V3, lambda blend. |
| `forecaster-extractors-scanners` | The 4 extraction/scan agents that populate the evidence store. |
| `forecaster-lenses` | The 9 analytical lenses (1 deterministic + 8 LLM), their contracts, and why they must stay blind to each other. |
| `forecaster-champion-judge` | Argue-for-then-against, and the materiality-weighted judge call. |
| `forecaster-ui` | The 9-sheet UI, the no-API/read-from-disk contract, the design-system vocabulary. |
| `hackathon-narrative-generation` | The judge-facing narrative one-pager stage (runs after judge, before output). **Has a corrected known bug noted at the top — read the correction before briefing a subagent on it.** |
| `hackathon-ui-presentation-layer` | The `/live` and `/narrative` UI routes, their component contracts and event schema. **Has a corrected note about a possible design-system/aesthetic mismatch with the 9 main sheets — resolve that before Phase F, not during.** |
| `hackathon-e2e-integration` | Full pipeline+UI integration checklist, troubleshooting table, and the pre-demo/during-demo runbook. **Corrected to this project's actual env vars and Claude/Anthropic-only stack.** |

**This project is Claude/Anthropic only.** Every subagent prompt for an LLM-
calling component should say so explicitly — one of the companion skills
(`hackathon-narrative-generation`) was originally written against a
generic OpenAI stack and has already caused one real bug (`narrative.py`
calling a constructor shape that doesn't exist on this project's
`LLMClient`). Don't let a fresh subagent reintroduce that mistake in a new
component by assuming OpenAI conventions anywhere.

## The dependency graph

```
Phase A (parallel, no dependencies — start immediately)
  A1. Sponsor DataSource adapter          [forecaster-data-model-core]
  A2. Schema / output-JSON contract       [forecaster-data-model-core]
  A3. UI shell, all 9 sheets against      [forecaster-ui]
      fixture data matching A2's shape

Phase B (needs A1 + A2 — the data layer and evidence store)
  B1. Acquisition + evidence store        [forecaster-data-model-core]
  B2. 3-statement model + Mechanical lens [forecaster-data-model-core, forecaster-lenses]
  B3. The 4 extractors/scanners           [forecaster-extractors-scanners]

Phase C (needs B — fan out, MUST stay blind to each other, see below)
  C1..C8. The 8 LLM lenses                [forecaster-lenses]

Phase D (needs ALL of C to have returned, kept + dropped both known)
  D1. V1 reconcile                        [forecaster-data-model-core]
  D2. Champion (per surviving lens)       [forecaster-champion-judge]
  D3. Judge                               [forecaster-champion-judge]

Phase E (needs D3)
  E1. V2 comparability                    [forecaster-data-model-core]
  E2. Lambda blend                        [forecaster-data-model-core]
  E3. V3 calibrate                        [forecaster-data-model-core]
  E4. Narrative one-pager (after judge,   [hackathon-narrative-generation]
      before output — fix the known
      constructor bug first, see above)
  E5. Output writer (out/*.json, ndjson)  [forecaster-data-model-core, forecaster-ui]

Phase F
  F1. Wire real output into the Phase A3 UI shell, replacing fixtures
  F2. Resolve the /live vs. main-sheet design-system question           [hackathon-ui-presentation-layer]
  F3. Run the full integration checklist end to end                     [hackathon-e2e-integration]
  F4. Record a replay log; verify the replay path works cold
```

Phase A3 (UI) runs concurrently with the entire backend build (B through E) —
it only needs the schema from A2, not working data, until F1. This is the
biggest parallelism win available: don't sequence the UI after the backend.

## Running phases as agents

- **Within a phase, launch every independent item as its own Agent call in
  the same message** — that's what makes them run in parallel rather than
  one after another. Sequential Agent calls across a whole phase burns the
  clock for no reason when the items don't depend on each other.
- **Every subagent prompt must be self-contained.** A fresh agent has none of
  this conversation's context. Each prompt should: name the companion skill
  file path to read first, state the specific component to build, state its
  output contract (what fields, what shape — pull this from the skill file),
  state the Step 0 constraint (fresh-only vs. reference-allowed), and state
  what it should NOT do (e.g., a lens agent should never be told what
  another lens concluded).
- **Phase C is the one place blindness is a hard requirement, not a nice-to-
  have.** Launch all 8 lens agents as separate Agent calls with prompts built
  only from `forecaster-lenses` plus the shared evidence store — never
  mention another lens's name, status, or output in any lens's prompt. If a
  later phase needs to know which lenses succeeded, that aggregation happens
  in Phase D (reconcile/judge), never inside a Phase C prompt.
- **Check back in at each phase boundary** rather than launching the entire
  DAG unattended — confirm Phase A produced a usable schema before starting
  B, confirm B's evidence store actually has claims in it before starting C
  (an empty evidence store makes every lens fail the same way, which is a
  waste of 8 parallel calls), confirm D's judge output matches the schema
  before wiring E4's output writer.

## What to do if time runs out mid-DAG

Everything in Phase A plus B2 (deterministic model + baseline) is a complete,
defensible, presentable entry on its own — this is `forecaster-playbook`'s
baseline-first framing applied to the build order itself. If Phase C or D
doesn't finish, ship the baseline with the UI showing exactly that ("full
pipeline incomplete; baseline forecast shown, backtest number attached") —
that is an honest, judged-favorably outcome, not a failure state. Do not
skip Phase F2 (replay recording) to squeeze in more of Phase C; a live demo
with no fallback is a worse risk than a smaller but fully-working scope.
