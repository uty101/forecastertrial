# Skills — earnings-forecaster build knowledge

Ten knowledge files, no source code, built so tomorrow's build can move fast
from understanding rather than from copy-paste — usable whether or not the
event's rules allow bringing pre-existing code. This whole folder is
self-contained and portable: to use it in a different repo (a fresh one, or
one the organizers hand out), copy the `skills/` folder over as-is.

## How to actually use this tomorrow

These are plain files, not registered Claude Code slash-commands (that
mechanism only auto-discovers `.claude/skills/`, and this folder was
deliberately moved out of there so it's visible and portable). To use it:
**open `ORCHESTRATOR_PROMPT.md` and paste its contents as your first message
to Claude Code**, in whichever repo you're actually working in, once
`skills/` exists in it. That prompt tells Claude to read the orchestrator
skill and go from there — you don't need to explain any of this by hand.

## What's in here

| File | Owns |
|---|---|
| `ORCHESTRATOR_PROMPT.md` | **The literal text to paste to kick off tomorrow's build.** Start here. |
| `forecaster-orchestrator/SKILL.md` | The build plan itself: dependency graph, what runs in parallel, how to brief subagents, what "blind lenses" means operationally. |
| `forecaster-playbook/SKILL.md` | The thesis, the formula, the 7 non-negotiable invariants, known traps, the day-of checklist. Read this one yourself, in full, before anything else. |
| `forecaster-data-model-core/SKILL.md` | Sources/loader/cache, acquisition, evidence store, the 3-statement model, V1 reconcile / V2 comparability / V3 calibrate, the λ blend. |
| `forecaster-lenses/SKILL.md` | The 9 analytical lenses (1 deterministic + 8 LLM), their contracts, and the fan-out mechanics that make blindness actually hold. |
| `forecaster-extractors-scanners/SKILL.md` | The 4 evidence-population agents (GAAP↔non-GAAP bridge, guidance extractor, call-sequence scanner, perception scanner). |
| `forecaster-champion-judge/SKILL.md` | Argue-for-then-against, and the materiality-weighted judge call. |
| `forecaster-ui/SKILL.md` | The 9-sheet UI, the no-API/read-from-disk contract, the design-system vocabulary. |
| `hackathon-narrative-generation/SKILL.md` | The judge-facing narrative one-pager stage. Written by a different session against a generic OpenAI stack — corrected at the top to this project's real Claude/Anthropic interfaces; flags a real bug in `narrative.py` that needs fixing before this stage will run. |
| `hackathon-ui-presentation-layer/SKILL.md` | The `/live` and `/narrative` UI routes. Corrected at the top to flag a possible visual-design mismatch with the rest of the UI, worth resolving deliberately. |
| `hackathon-e2e-integration/SKILL.md` | Full pipeline+UI integration checklist, troubleshooting table, pre-demo/during-demo runbook. Corrected at the top to this project's real env vars and Anthropic-only stack. |

## The one constraint that shapes everything else

**This project is Claude/Anthropic only.** Two of the three `hackathon-*`
files were originally written against a generic OpenAI-shaped stack and
contained real inaccuracies (`OPENAI_API_KEY`, `gpt-4-turbo`, a wrong
`LLMClient` constructor). They've been corrected in place — each has a
`⚠️ Correction` section at the top — but it's worth remembering when reading
the uncorrected bulk of those files: mentally substitute this project's real
`LLMClient`/`Settings`/tier system anywhere they say OpenAI.
