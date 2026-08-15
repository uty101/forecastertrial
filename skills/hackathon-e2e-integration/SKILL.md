---
name: hackathon-e2e-integration
description: End-to-end integration checklist for the presentation layer and narrative generation. Use when: testing full pipeline with UI; preparing for live demo; verifying all components work together; troubleshooting integration issues; or validating output during the event. Triggers on "end-to-end", "e2e", "full run", "integration test", "demo preparation", "presentation layer", "live event", "forecast run".
---

# End-to-End Integration Guide — Quick Reference

This is knowledge, not code. It documents how to verify the entire presentation layer works with the forecast pipeline, and how to diagnose integration failures.

---

## ⚠️ Correction — verified against the actual codebase (2026-08-15)

This project is **Claude/Anthropic only** — wherever this file says
`OPENAI_API_KEY=sk-...`, the real `.env` var is `ANTHROPIC_API_KEY` (plus
`SEC_IDENTITY`, `FRED_API_KEY`, `LSE_API_KEY`/`LSE_BASE_URL`,
`EXA_API_KEY`/`TAVILY_API_KEY`, `POLYGON_API_KEY`, `FMP_API_KEY` for the
other data sources — see `.env.example`). The real cost-ceiling env var is
`FORECASTER_COST_CEILING_USD`, not `COST_BUDGET`. The real smoke-test/run
commands are `uv run forecast sources --ticker NVDA` and
`make run TICKER=NVDA ASOF=2026-08-16` (see the Makefile) — verify the exact
`forecast run` flag names against `src/forecaster/cli.py` before relying on
the invocation shown below.

Also: `src/forecaster/pipeline/narrative.py` currently has a constructor bug
(see `hackathon-narrative-generation`'s correction note) that will make the
NARRATIVE stage in the timeline below fail until fixed — don't assume it
runs cleanly without checking.

Everything else here (the integration architecture, the checklist structure,
the troubleshooting table, the demo rollback scenarios) is still a solid
reference shape.

---

## Integration Architecture

```
Pipeline (Python)          Output Files            UI Layer (Next.js)
═════════════════════════════════════════════════════════════════════════

Stage A-I runs
├─ Emits events ────────→ out/events.ndjson ────→ Live Dashboard polls
│                           (every 1-2 sec)        (every 1 sec)
│
├─ Produces forecast ───→ out/forecast.json ────→ Narrative Page loads
│                           (at end)                (one-time on mount)
│
└─ Pipeline completes

No API server. No server communication. Just JSON files.
```

---

## Full Integration Checklist

### Before Starting a Run

#### Environment
- [ ] `out/` directory exists (create if needed: `mkdir out`)
- [ ] `.env` file has `OPENAI_API_KEY=sk-...`
- [ ] All Python dependencies installed: `uv sync`
- [ ] All Node dependencies installed: `cd ui && npm install`
- [ ] Next.js dev server running: `cd ui && npm run dev` (in separate terminal)

#### Data Source
- [ ] Data source adapter exists in `src/forecaster/data/your_source.py`
- [ ] Adapter is registered in `src/forecaster/data/loader.py`
- [ ] Adapter tested standalone: `uv run forecast sources --ticker NVDA`
- [ ] No authentication errors

### Start a Full Pipeline Run

```bash
export TICKER=COMPANY_NAME
export ASOF=2026-08-16
uv run forecast run --ticker $TICKER --asof $ASOF --verbose
```

**Expected output (console):**
```
[INFO] Starting forecast pipeline for TICKER=COMPANY_NAME as_of=2026-08-16
[INFO] Stage A (ACQUIRE): Fetching data...
[INFO] Stage B (STRUCTURE): Building evidence store...
...
[INFO] Forecast complete. Output written to out/forecast.json
```

### Monitor in Real-Time (3 Terminals)

#### Terminal 1: Pipeline
```bash
uv run forecast run --ticker $TICKER --asof $ASOF --verbose
```

#### Terminal 2: Event Stream (Optional, for Debugging)
```bash
tail -f out/events.ndjson | grep -E "stage|lens_complete|error"
```

#### Terminal 3: UI Server
```bash
cd ui && npm run dev
```

### Watch the Live Dashboard

**URL:** `http://localhost:3000/live`

**Expected sequence:**
1. Page loads with "Waiting for pipeline..." (if pipeline hasn't started)
2. ACQUIRE stage starts → progress bar appears
3. Cost counter starts incrementing
4. "Top Drivers" section populates as lenses complete
5. EPS bars appear mid-pipeline (when forecast is computed)
6. Confidence indicator fills in
7. Final event log shows all stages complete

**Timing reference:**
```
0:00 - ACQUIRE starts
2:00 - STRUCTURE
3:00 - MODEL
4:00 - ANALYSE (9 lenses parallel, takes 3-4 min)
7:00 - RECONCILE
8:00 - CHALLENGE
10:00 - JUDGE (2-3 min, expensive LLM call)
12:00 - POSITION
12:30 - OUTPUT
12:45 - NARRATIVE (5 sec, if integrated)
13:00 - COMPLETE
```

### Verify Output Files

After pipeline completes:

```bash
# Check forecast file exists and has data
ls -lh out/forecast.json
wc -l out/forecast.json  # Should be >100 lines

# Parse key fields
python -c "
import json
f = json.load(open('out/forecast.json'))
print(f'Forecast EPS: {f.get(\"forecast_eps\"):.2f}')
print(f'Consensus EPS: {f.get(\"consensus_eps\"):.2f}')
print(f'Confidence: {f.get(\"confidence_percent\"):.0f}%')
print(f'Lenses: {len(f.get(\"lenses\", []))}')
print(f'Narrative present: {\"narrative\" in f}')
"

# Check event stream
tail -20 out/events.ndjson  # Should show completion event
```

### Load Narrative Page

**URL:** `http://localhost:3000/narrative`

**Expected:**
- Title loads
- Thesis displays
- "Why we differ" section shows 3 reasons with evidence
- "What could be wrong" risks section
- Full 400-500 word narrative prose
- Print button works: `Ctrl+P` → PDF or print

### Test Print Output

1. Navigate to `http://localhost:3000/narrative`
2. `Ctrl+P` (or right-click → Print)
3. **Preview checklist:**
   - [ ] Title readable
   - [ ] All text visible (not cut off)
   - [ ] No awkward page breaks
   - [ ] No background colors (or minimal)
   - [ ] Margins reasonable (not too tight)
4. Save as PDF or print
5. Check output is readable on judge display

---

## Integration Troubleshooting

### Problem: Dashboard Shows "Waiting for pipeline..." Forever

**Likely causes:**
1. Pipeline didn't start
2. Pipeline crashed silently
3. `out/events.ndjson` wasn't created

**Debug:**
```bash
# Check pipeline process
ps aux | grep "forecast run"

# Check if events file exists
ls -la out/events.ndjson

# Check if events file has content
wc -l out/events.ndjson

# If 0 lines, pipeline hasn't written any events
# If >0, run something like:
tail -5 out/events.ndjson | jq .
```

**Fix:**
```bash
# Stop any running pipeline
pkill -f "forecast run"

# Clear old output
rm -f out/events.ndjson out/forecast.json

# Re-run with verbose logging
uv run forecast run --ticker $TICKER --asof $ASOF --verbose 2>&1 | tee pipeline.log

# Check logs
grep -i error pipeline.log
```

---

### Problem: Events Stream Shows Events, But Dashboard Doesn't Update

**Likely causes:**
1. Polling interval too long (try 500ms instead of 1000ms)
2. Events file is being truncated between reads
3. Browser cache issue

**Debug:**
```bash
# Check if events are being written
watch -n 0.5 'wc -l out/events.ndjson'  # Should increment every few sec

# Check event content
tail -10 out/events.ndjson | python -m json.tool
```

**Fix:**
- Refresh browser: `Ctrl+Shift+R` (hard refresh)
- Check browser console for errors: `F12` → Console
- Increase polling frequency in `ui/app/live/page.tsx` (line ~60):
  ```typescript
  const interval = setInterval(pollEvents, 500); // Was 1000
  ```

---

### Problem: EPS Bars Don't Render (ComparisonChart Blank)

**Likely causes:**
1. `forecast_eps` or `consensus_eps` is null/undefined
2. `forecast_eps` or `consensus_eps` is a string instead of number

**Debug:**
```bash
python -c "
import json
f = json.load(open('out/forecast.json'))
print(f'forecast_eps: {f.get(\"forecast_eps\")} (type: {type(f.get(\"forecast_eps\")).__name__})')
print(f'consensus_eps: {f.get(\"consensus_eps\")} (type: {type(f.get(\"consensus_eps\")).__name__})')
"
```

**Fix:**
- If null: Forecast stage didn't complete. Check pipeline logs.
- If string: Data type issue in `judge` stage. Verify `forecast.json` is valid JSON with numeric types.

---

### Problem: Narrative Page Shows "No narrative available yet"

**Likely causes:**
1. Pipeline hasn't run or didn't include narrative stage
2. `out/forecast.json` doesn't have `narrative` field
3. Narrative generation failed and wasn't logged

**Debug:**
```bash
python -c "
import json
f = json.load(open('out/forecast.json'))
print('Narrative field present:', 'narrative' in f)
if 'narrative' in f:
    print('Narrative keys:', list(f['narrative'].keys()))
"
```

**Fix:**
- If narrative not present: Pipeline needs narrative stage integration in `cli.py`
- If present but still not showing: Refresh browser (`Ctrl+Shift+R`)
- Check browser console for errors: `F12` → Console

---

### Problem: Print Preview Looks Bad (Text Overlapping, Colors Wrong)

**Likely causes:**
1. CSS media query not working
2. Browser zoom level wrong
3. Print settings need adjustment

**Debug:**
```bash
# In browser DevTools (F12):
# 1. Go to Elements tab
# 2. Find narrative page container
# 3. Check if @media print styles are applied
```

**Fix:**
- Zoom to 100% (Ctrl+0)
- Try Chrome → Print Settings:
  - Margins: Minimum
  - Background graphics: On
  - Scale: 100%
- Or adjust CSS in `ui/app/narrative/page.tsx`:
  ```typescript
  // Change padding for print
  <div className="p-12 print:p-8">  // <- adjust these values
  ```

---

### Problem: Cost Exploding (>$2 for Single Run)

**Likely causes:**
1. Lenses running in parallel instead of sequentially
2. Retrying failed LLM calls too many times
3. Narrative generation not working and falling back to retry logic

**Debug:**
```bash
# Check if lenses ran in parallel
grep "lens_complete" out/events.ndjson | wc -l  # Should show 9 (or fewer if some abstained)
grep "ANALYSE" out/events.ndjson | head -3  # Check if stage shows all lenses running once

# Check cost in events
grep "cost_so_far" out/events.ndjson | tail -1 | python -m json.tool
```

**Fix:**
- If >3 lenses, they may be running in parallel (intended, but expensive)
- If cost is >$3 and you only ran once, check:
  - Is narrative generation being called twice?
  - Are lenses retrying on validation failure?
- See cost budget in pipeline orchestrator (usually `COST_BUDGET=1.50`)

---

## Event Stream Schema Reference

### Stage Events
```json
{"event_type": "stage_started", "stage": "ACQUIRE", "timestamp": "2026-08-16T14:00:00Z"}
{"event_type": "stage_complete", "stage": "ACQUIRE", "cost_so_far": 0.12, "timestamp": "2026-08-16T14:02:15Z"}
```

### Lens Events
```json
{"event_type": "lens_complete", "lens_name": "Demand", "impact_bps": 230, "description": "Capex cycle", "timestamp": "..."}
```

### Forecast Event
```json
{"event_type": "forecast_produced", "forecast": {"forecast_eps": 2.28, "consensus_eps": 2.15, "confidence_percent": 67, ...}, "timestamp": "..."}
```

### Error Event
```json
{"event_type": "error", "stage": "ANALYSE", "message": "Lens X failed reconciliation", "timestamp": "..."}
```

### Narrative Event (Optional)
```json
{"event_type": "narrative_generated", "word_count": 450, "themes": "Capex, buyback, macro", "timestamp": "..."}
```

---

## Pre-Demo Verification Checklist

### 1 Hour Before Event

- [ ] Run complete pipeline on test company: `uv run forecast run --ticker TSLA --asof 2026-08-15`
- [ ] Check all output files created:
  - [ ] `out/forecast.json` (>100 lines)
  - [ ] `out/events.ndjson` (>50 lines)
  - [ ] `out/model.json` (present)
- [ ] Verify live dashboard loads: `http://localhost:3000/live`
- [ ] Verify narrative page loads: `http://localhost:3000/narrative`
- [ ] Test print: Print narrative to PDF
- [ ] Take screenshots of all screens (backup for live API failure)
- [ ] Verify projector/display shows text clearly (step back 3 feet)
- [ ] Have printed narratives ready (10+ copies)
- [ ] Git status clean (no uncommitted UI changes that might fail to load)

### 5 Minutes Before Presentation

- [ ] Pipeline NOT running (clean output files from test run)
- [ ] Terminal ready for `uv run forecast run --ticker $COMPANY --asof $DATE`
- [ ] Live dashboard URL copied: `localhost:3000/live`
- [ ] Narrative page URL copied: `localhost:3000/narrative`
- [ ] Printed one-pagers in hand
- [ ] Presentation script memorized (90 seconds)
- [ ] Backup screenshots on USB in case API dies

### During Presentation

- [ ] Run command: `uv run forecast run --ticker [COMPANY] --asof 2026-08-16`
- [ ] Open live dashboard in browser
- [ ] Point to stage progress (shows work in progress)
- [ ] Show EPS forecast bars as they appear
- [ ] Highlight confidence indicator
- [ ] Show key drivers as lenses complete
- [ ] At end, show narrative page
- [ ] Hand out printed one-pagers
- [ ] Answer questions (point to dashboard for evidence)

---

## Rollback & Emergency Scenarios

### Scenario 1: Live API Fails Mid-Presentation

**Fallback:**
1. Stop pipeline (Ctrl+C)
2. Load saved `forecast.json` from previous successful run
3. Reload dashboard: `http://localhost:3000/live` (will show final state)
4. Switch to narrative page (shows output)
5. Say: "We're using cached results from our test run to show you the output format."

**Prevention:**
- Save successful run to USB: `cp out/forecast.json out/forecast_backup.json`
- Screenshot dashboard mid-run
- Have printed output ready

### Scenario 2: Dashboard Stops Updating

**Cause:** Polling stalled  
**Fix:**
1. Refresh browser: `Ctrl+Shift+R`
2. Check terminal 2 for pipeline still running: `ps aux | grep forecast`
3. If pipeline crashed, manually show `out/events.ndjson` in terminal

### Scenario 3: Narrative Page Doesn't Load

**Cause:** Missing `narrative` field in JSON  
**Fix:**
1. Show narrative from `out/forecast.json` in terminal: `cat out/forecast.json | jq '.narrative'`
2. Print it to screen
3. Or use backup narrative from test run

### Scenario 4: Presentation Overruns

**Cut to:**
1. EPS forecast bars (most important)
2. Confidence indicator
3. One key driver
4. Hand out printed narrative

**Skip:**
- Event log details
- All 9 lenses (pick top 3)
- Model diagnostics

---

## Performance Reference

### Typical Full Run Metrics

| Metric | Value |
|--------|-------|
| Total time | 10–15 minutes |
| ACQUIRE | 2–3 min |
| STRUCTURE | 1 min |
| MODEL | 1 min |
| ANALYSE | 3–4 min (9 parallel lenses) |
| RECONCILE | 1 min |
| CHALLENGE | 1 min |
| JUDGE | 2–3 min (expensive LLM call) |
| POSITION | 1 min |
| NARRATIVE | 5 sec |
| Total cost | $1.20–$1.50 |
| Event count | 50–100 |

### Bottlenecks
- **JUDGE stage** (2–3 min) — This is normal; judges calls a multi-lens LLM reasoning
- **ANALYSE stage** (3–4 min) — 9 lenses in parallel; each takes 20–30 sec
- **API timeouts** (if >15 min) — Check internet, data source rate limits

---

## Success Criteria (What Judges See)

1. **Live Demo** ✓
   - Dashboard loads and animates
   - Progress bar fills from 0 to 100%
   - EPS forecast appears and is sensible
   - Confidence indicator shows believable level
   - No crashes or error messages

2. **Narrative** ✓
   - Page loads and is readable
   - Explains why forecast differs from consensus
   - Cites specific lens evidence
   - Lists 2–3 honest risks
   - Is printable (judges take home)

3. **Presentation** ✓
   - Judges understand the forecast in 90 seconds
   - You can articulate why consensus is different
   - You can defend the confidence level
   - You acknowledge risks honestly

---

## Checklist for Code Handoff

If someone else is presenting tomorrow, they need:

- [ ] This guide (e-2-e integration guide)
- [ ] `QUICKREF.md` (one-pager)
- [ ] `HACKATHON.md` (timeline)
- [ ] `CHECKLIST.md` (checkboxes)
- [ ] Repo with all UI code committed
- [ ] `.env` file with API keys (not in git)
- [ ] Screenshots of successful test run saved to USB
- [ ] Printed backup narratives from test run
- [ ] Presentation script (90-second version)

---

## One-Liner If Someone Asks "Does It All Work Together?"

> "Run the pipeline in one terminal (`uv run forecast run`), open the live dashboard in browser (`localhost:3000/live`), watch it populate in real-time, then show the narrative page (`localhost:3000/narrative`) when it's done. All data flows through JSON files; no server needed. Tested and working."

