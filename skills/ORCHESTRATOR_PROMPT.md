# Orchestrator kickoff prompt

Copy everything in the fenced block below and paste it as your first message
to Claude Code tomorrow, in the repo you're actually building in (this one,
or a fresh one with this `skills/` folder copied into it). Fill in the
bracketed placeholders once the event gives you the real values — don't
guess at them tonight.

---

```
We're building an earnings-forecasting agent for the "Agents vs Wall Street"
hackathon, right now, under today's time budget. Before writing or editing
anything:

1. Read skills/forecaster-orchestrator/SKILL.md in full — that's the build
   plan for today: the dependency graph, what can run in parallel, and how
   to brief subagents.

2. Read skills/forecaster-playbook/SKILL.md in full — that's the thesis and
   the 7 non-negotiable invariants. Check every decision today against it,
   especially: shrinking to consensus on a well-covered name is a correct
   result, not a failure; the baseline must always be shown; lenses must
   never see each other's output; aggregation is by materiality, never by
   vote or average.

3. Ask me directly, before doing anything else: is code that predates today
   allowed, or does everything need to be written fresh today? Don't assume
   — it changes how you brief every subagent from here on.

4. This project is Claude/Anthropic only — not OpenAI. Some of the
   knowledge files under skills/ were originally written against a generic
   OpenAI-shaped stack and have been corrected; if you read one with a
   "⚠️ Correction" section at the top, follow the correction, not the
   original text below it.

5. Then follow the orchestrator's phase plan (A through F) exactly:
   - Launch every independent component within a phase as its own Agent/Task
     call in the same turn, so they actually run in parallel.
   - Before briefing any subagent, read the specific companion skill file
     under skills/ for that component yourself, and pull the relevant
     contract/constraints into that subagent's prompt directly — a fresh
     subagent has no memory of this conversation, so its prompt needs to be
     self-contained.
   - Phase C (the 8 LLM lenses) must stay genuinely blind to each other:
     separate Agent calls, and no lens's prompt may mention another lens's
     name, status, or findings. If something downstream needs to know which
     lenses succeeded, that happens in Phase D, never inside a Phase C
     prompt.
   - Check in with me at each phase boundary before continuing to the next
     — confirm Phase A's schema is usable before starting B, confirm B's
     evidence store actually has claims before starting the Phase C fan-out,
     etc. Don't run the whole DAG unattended.

6. If time runs out before the full pipeline is done: ship whatever's
   complete through the deterministic backbone (Phase A + B2, the baseline
   forecast) with the UI honestly showing what's implemented and what isn't.
   That is a legitimate, presentable entry on its own — don't sacrifice
   Phase F's replay-recording step to squeeze in more of the ensemble; a live
   demo with no fallback is a worse risk than a smaller but fully-working
   scope.

The company/ticker, the data feed details, and the scoring metric will be
given this morning — treat those as the first real inputs to Phase A, not
something to guess at now. Ticker: [FILL IN]. Data feed: [FILL IN]. Scoring
metric (write it verbatim): [FILL IN].
```
