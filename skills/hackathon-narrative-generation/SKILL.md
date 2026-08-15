---
name: hackathon-narrative-generation
description: Knowledge for the narrative generation stage of the earnings forecaster pipeline. Use when: integrating narrative generation into pipeline orchestration; modifying the narrative LLM prompt; tuning narrative output format; testing narrative generation standalone; or debugging narrative failures. Triggers on "narrative generation", "one-pager", "narrative stage", "narrative prompt", "generate_narrative", "NarrativeOutput".
---

# Narrative Generation Stage — Quick Reference

This is knowledge, not code. It documents how the narrative generation stage works, how to integrate it, and how to modify prompts if needed during the hackathon.

---

## ⚠️ Correction — verified against the actual codebase (2026-08-15)

This file was written against a generic OpenAI-shaped stack that does not
match this project. Confirmed: **this project is Claude/Anthropic only** —
`src/forecaster/llm/client.py`'s `LLMClient` is a dataclass constructed from
`(cache, settings)`, internally calls the `anthropic` SDK, and resolves a
model from three tiers (`cheap` / `mid` / `deep`) via `settings.model_cheap`
/ `model_mid` / `model_deep` — there is no `api_key=`/`model=` constructor
signature and no `gpt-4-turbo`. `Config` (`src/forecaster/config.py`) has
`anthropic_api_key` (env var `ANTHROPIC_API_KEY`); it has **no**
`openai_api_key` or `llm_model` field.

As currently written, `src/forecaster/pipeline/narrative.py` line ~124 calls
`LLMClient(api_key=config.openai_api_key, model=config.llm_model)` — both
attributes are missing from `Config` and the constructor shape is wrong. This
**will raise at runtime** and needs fixing before the narrative stage can
actually run: construct `LLMClient` the way the rest of the pipeline does
(via `cache` + `settings`), and load the prompt the way every other stage
does — from `src/forecaster/llm/prompts/narrative_generation.yaml` through
the same versioned-prompt loader (`llm/prompt.py`), assigning it a
`model_tier` (`cheap` is almost certainly right for a synthesis-of-existing-
findings task) rather than hardcoding `model: gpt-4-turbo` /
`temperature: 0.7` inline in the YAML the way this file describes.

Everything below this point (prompt structure, JSON schema, validation
rules, debugging table, checklist) is still useful *as a design reference*
— just mentally substitute "the project's LLMClient/Settings tier system"
everywhere this file says OpenAI/`gpt-4-turbo`/`openai_api_key`.

---

## What the Narrative Stage Does

**Input:** Completed forecast data (9 lenses, judge output, model diagnostics)  
**Output:** Structured one-pager explaining the forecast to judges  
**When it runs:** After judge produces forecast, before final output  
**Cost:** ~0.05 API calls (~$0.10 per run)  
**Time:** ~5 seconds (LLM call only)

**Why it exists:** Judges need a legible, printable narrative explaining why the forecast differs from consensus and where consensus is weak. This stage generates that automatically.

---

## Architecture

### Files

| File | Purpose |
|------|---------|
| `src/forecaster/llm/prompts/narrative_generation.yaml` | LLM prompt (versioned, easy to iterate) |
| `src/forecaster/pipeline/narrative.py` | Orchestrator (loads prompt, calls LLM, validates output) |
| `ui/app/narrative/page.tsx` | UI that renders output (reads from `forecast.json`) |

### Data Flow

```
judge() produces forecast.json
        ↓
run_narrative_stage(forecast.json)
        ↓
load narrative_generation.yaml
        ↓
extract: lenses, forecast_eps, consensus_eps, confidence
        ↓
render prompt template (fill in variables)
        ↓
call LLM (Claude/GPT-4) with JSON schema validation
        ↓
validate output (word count, schema, citations)
        ↓
write to forecast.json["narrative"]
        ↓
UI reads and displays
```

---

## The Prompt (`narrative_generation.yaml`)

### Structure

```yaml
---
name: narrative_generation
version: "1.0"
model: gpt-4-turbo
temperature: 0.7
max_tokens: 1200
system_prompt: |
  You are an investment analyst writing for institutional judges...
prompt_template: |
  You have a forecast for {ticker}'s earnings...
  [variables filled in at runtime]
post_processing: |
  - Validate JSON schema
  - Check word count (400-500)
  - Verify citations present
error_handling: |
  - If forecast missing, return error
  - If no lenses returned evidence, return error
  - If consensus stale, warn in narrative
```

### Key Variables (Filled at Runtime)

```python
{ticker}              # e.g., "AAPL"
{fiscal_period}       # e.g., "Q3 2026"
{as_of}               # e.g., "2026-08-15"
{consensus_eps}       # e.g., 2.15
{forecast_eps}        # e.g., 2.28
{confidence_percent}  # e.g., 67.0
{consensus_history}   # Recent walkdown narrative
{lens_rankings}       # Top 9 lenses formatted as markdown
{model_mae}           # Historical model error
{comp_min}, {comp_max} # Comparable company range
{regime}              # Description of current regime
{pct_walkdown}        # How much consensus walked down
```

### Expected Output (JSON Schema)

```json
{
  "title": "Why We're Different on AAPL",
  "thesis": "One-sentence core insight",
  "our_forecast": "$2.28 EPS (67% confidence)",
  "consensus_context": "Prose explaining why consensus moved",
  "our_case": {
    "reason_1": {
      "evidence": "Specific finding from Demand lens",
      "quote": "Verbatim from source filing if available",
      "impact": "+2.3% vs consensus"
    },
    "reason_2": {...},
    "reason_3": {...}
  },
  "risks": [
    "Risk A: If X happens, consensus was right",
    "Risk B: If Y happens, we over-adjusted",
    "Risk C: Model or data risk"
  ],
  "narrative": "400-500 word prose narrative for judges. Start with thesis, then evidence from top 3 lenses, then risks, then confidence statement."
}
```

### Prompt Requirements (Non-Negotiable)

1. **Every claim must cite a source** (lens name or data point)
2. **Narrative is prose, not bullet points** (readability for judges)
3. **Word count 400–500** (long enough to be convincing, short enough to read in 2 min)
4. **Three reasons we differ** (from `our_case` dict)
5. **Two to three risks** (what could prove us wrong)
6. **Confidence statement at end** (how much we trust this forecast)

---

## Integration into Pipeline

### How to Add to Orchestration

**File:** `src/forecaster/cli.py` (or equivalent pipeline orchestrator)

**After judge stage completes:**
```python
# Judge produces forecast
forecast_json = await run_judge_stage(...)

# Generate narrative
narrative_result = await run_narrative_stage(
    ticker=ticker,
    dossier_path=dossier_path,
    forecast_json=forecast_json,
    config=config
)

# Merge back into forecast
forecast_json["narrative"] = narrative_result["narrative"]

# Write combined output
json.dump(forecast_json, open("out/forecast.json", "w"))
```

### Expected Inputs to `run_narrative_stage()`

```python
async def run_narrative_stage(
    ticker: str,                    # "AAPL"
    dossier_path: Path,             # Path to dossier/ folder
    forecast_json: dict[str, Any],  # Output from judge (has forecast_eps, lenses, etc.)
    config: Config,                 # Config with API key, model choice
) -> dict[str, Any]:
    """
    Returns:
    {
      "success": True,
      "ticker": "AAPL",
      "narrative": {
        "title": "...",
        "thesis": "...",
        ...
      }
    }
    """
```

### Event Logging (Optional)

```python
# After narrative completes, emit event
events.append({
    "event_type": "narrative_generated",
    "ticker": ticker,
    "timestamp": datetime.now().isoformat(),
    "word_count": len(narrative["narrative"].split()),
    "themes": narrative.get("title", ""),
})
```

---

## Customizing the Prompt (If Needed Tomorrow)

### Common Tweaks

#### 1. Change Confidence Interpretation
**In `system_prompt`:**
```yaml
You are an investment analyst writing for institutional judges...

CONFIDENCE INTERPRETATION:
- 75%+: We found multiple independent signals that move the needle
- 60-74%: We found something, but execution risks remain
- <60%: Data was limited; this is our best estimate
```

#### 2. Emphasize Different Types of Evidence
**In `prompt_template`, section "Constraints":**
```
Cite specific lens findings (e.g., "Demand lens found capex cycle in customer guidance filed Aug 15")
Prioritize company's own guidance over analyst estimates
Distinguish between GAAP vs non-GAAP if they differ materially
```

#### 3. Change Output Format
**In the JSON schema section:**
Add fields or restructure if judges prefer different layout:
```json
{
  "executive_summary": "Two sentence version",
  "detailed_thesis": "Full narrative",
  ...
}
```

#### 4. Restrict to Specific Word Count
**In `post_processing`:**
```yaml
post_processing: |
  - Check narrative is 350-600 words (was 400-500)
  - Warn if outside range but don't reject
```

---

## Prompt Versions (How to Iterate)

**File naming:** `narrative_generation_v1.yaml`, `narrative_generation_v2.yaml`, etc.

**Why versions?** You want to know which prompt produced which backtest result.

**How to switch:**
```python
prompt_template = load_prompt("narrative_generation", version="1.1")
# or
prompt_template = load_prompt("narrative_generation", version="2.0")
```

**Changelog example:**
```
v1.0: Initial release
v1.1: Increased word count from 300 to 400-500
v1.2: Added confidence interpretation section
v2.0: Restructured to emphasize three reasons we differ
```

---

## Validation & Error Handling

### What Gets Validated

1. **JSON schema:** All required fields present, correct types
2. **Word count:** 400–500 words in narrative field
3. **Citation presence:** At least one lens cited in `our_case`
4. **Risk count:** 2–3 risks listed (not 0, not 10)

### Error Responses

| Condition | Action |
|-----------|--------|
| Forecast EPS missing | Raise ValueError, don't try narrative |
| No lenses returned evidence | Raise ValueError: "Insufficient lens evidence" |
| Confidence > 95% | Warn in narrative: "Very high confidence; verify not overfit" |
| Confidence < 20% | Warn in narrative: "Low confidence; prefer to abstain" |
| Consensus > 5 days old | Warn in narrative: "Consensus data is stale" |
| JSON parse fails | Log error, return empty `narrative` field |

### Graceful Degradation

If narrative generation fails:
```python
forecast_json["narrative"] = {
    "title": "Analysis for " + ticker,
    "thesis": "Unable to generate automated narrative",
    "our_forecast": f"${forecast_eps:.2f} EPS ({confidence:.0f}% confidence)",
    "narrative": "Please refer to lens outputs for detailed reasoning."
}
```

(UI still displays something; presentation doesn't crash)

---

## Output Format (What UI Expects)

### Rendered in `ui/app/narrative/page.tsx`

```typescript
interface NarrativeData {
  title: string;
  thesis: string;
  our_forecast: string;
  consensus_context: string;
  our_case: Record<string, {
    evidence: string;
    quote?: string;
    impact: string;
  }>;
  risks: string[];
  narrative: string;
}
```

### CSS Styling

- **Title:** 4xl font, bold
- **Thesis:** xl, italic, blue
- **Section headers:** xl, bold
- **Quotes:** Indented with left border, italicized
- **Print:** No background colors, readable serif fonts

---

## Testing the Narrative Stage Standalone

### 1. Minimal Test

```python
from forecaster.pipeline.narrative import generate_narrative
from forecaster.config import Config

config = Config(openai_api_key="sk-...", llm_model="gpt-4-turbo")

narrative = await generate_narrative(
    ticker="AAPL",
    forecast_eps=2.28,
    consensus_eps=2.15,
    confidence_percent=67,
    lenses=[
        {"name": "Demand", "impact_bps": 230, "key_finding": "Capex cycle"},
        {"name": "Market", "impact_bps": 130, "key_finding": "Share buyback"},
    ],
    consensus_history="Walked down 3.2% in last 30 days",
    model_mae=0.0450,
    comp_range=(2.08, 2.22),
    regime="Medium coverage, low dispersion",
    as_of="2026-08-15",
    fiscal_period="Q3 2026",
    config=config,
)

print(narrative.dict())
```

### 2. Check Output Quality

```python
# Word count
word_count = len(narrative.narrative.split())
assert 400 <= word_count <= 500, f"Narrative is {word_count} words"

# Citations
assert len(narrative.our_case) == 3, "Should have 3 reasons"
assert all(r["evidence"] for r in narrative.our_case.values()), "All reasons need evidence"

# Risks
assert 2 <= len(narrative.risks) <= 3, "Should have 2-3 risks"

print("✓ Narrative passes validation")
```

### 3. Print the Narrative

```python
print(f"Title: {narrative.title}")
print(f"Thesis: {narrative.thesis}")
print(f"---")
print(narrative.narrative)
```

---

## Debugging Common Narrative Issues

| Problem | Diagnosis | Fix |
|---------|-----------|-----|
| Narrative is empty | LLM returned malformed JSON | Check API response in logs; retry with `--verbose` |
| Narrative doesn't cite lenses | Prompt template missing `{lens_rankings}` | Verify YAML has all variables; compare to template |
| Word count way off (e.g., 50 words) | Model took shortcut | Increase `max_tokens` in YAML; tweak temperature |
| Confidence interpretation wrong | Model misunderstood `confidence_percent` range | Add explicit instruction: "confidence is 0-100, where 75+ is high" |
| Narrative contradicts forecast | Prompt didn't get forecast data | Check `forecast_json` is being passed correctly to `run_narrative_stage()` |
| Cost spike (>$1 for narrative alone) | LLM called multiple times | Check retry logic; shouldn't retry more than 1–2 times |

---

## Performance & Cost

### Expected Metrics

| Metric | Value |
|--------|-------|
| API calls | 1 per run |
| Tokens (input) | ~800–1200 (mainly lens descriptions) |
| Tokens (output) | ~400–500 (narrative prose) |
| Total cost | ~$0.10 per run |
| Latency | 3–7 seconds |

### Cost Optimization

1. **Reuse cached lenses** — Don't re-fetch lens output if you re-run narrative
2. **Batch narratives** — If running multiple tickers, don't parallelize (CPU-bound parsing, not GPU)
3. **Fallback** — If LLM fails, use template narrative (save cost, still presentable)

---

## Replay & Determinism

### Deterministic Inputs

- Forecast numbers (deterministic from judge)
- Lens rankings (deterministic, sorted by impact)
- Model diagnostics (deterministic)

### Non-Deterministic Output

- Narrative prose (LLM output always slightly varies)
- Exact wording of recommendations (even with temp=0.7, not guaranteed identical)

### Replay Strategy

```python
# Save original run
forecast_1 = json.load(open("out/forecast.json"))

# If live demo crashes, you can replay:
# Option A: Re-render existing narrative (deterministic)
def render_narrative_html(narrative: NarrativeOutput) -> str:
    return f"""
    <h1>{narrative.title}</h1>
    <p>{narrative.thesis}</p>
    ...
    """

# Option B: Generate new narrative with same inputs (slightly different wording, but similar message)
narrative_2 = await generate_narrative(...)
```

---

## Checklist Before Presenting

- [ ] Narrative stage integrated into pipeline (runs after judge)
- [ ] Prompt template has all required variables
- [ ] LLM validation enforces JSON schema
- [ ] Output is written to `forecast.json["narrative"]`
- [ ] UI loads narrative from `forecast.json`
- [ ] Narrative page prints without layout issues
- [ ] You have 10+ printed narratives ready
- [ ] You tested narrative generation standalone (one run)

---

## One-Liner If Someone Asks "How Does Narrative Work?"

> "After the pipeline forecasts EPS, we call Claude to generate a one-pager explaining why we differ from consensus. The prompt feeds in the forecast data, top lenses, and risk factors. Claude returns structured JSON with title, thesis, three reasons we differ, and a 400-word narrative. UI renders it. Judges read it. Takes 5 seconds, costs $0.10."

