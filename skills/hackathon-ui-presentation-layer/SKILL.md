---
name: hackathon-ui-presentation-layer
description: Quick reference for the live dashboard, narrative one-pager, and supporting components built for Agents vs Wall Street. Use when: rebuilding UI components; modifying dashboard layout; tweaking narrative page styling; integrating live event streaming; or customizing presentation layer for different judges/displays. Triggers on "UI components", "live dashboard", "narrative page", "EventStreamMonitor", "ComparisonChart", "presentation layer", "hackathon demo".
---

# Hackathon UI Presentation Layer — Quick Reference

This is knowledge, not code. It documents the presentation layer architecture for the Agents vs Wall Street hackathon, so rebuilds or modifications can happen fast if needed.

## ⚠️ Worth a deliberate decision, not a silent default

Two things here are real, not hallucinated — `ui/app/live/page.tsx` exists
and `EventStreamMonitor`/`ComparisonChart`/`ConfidenceIndicator` are real
components under `ui/components/` — but two things are worth checking before
building on top of them:

1. **`/live` visually contradicts the rest of the UI's design system.** The
   other nine sheets (see `forecaster-ui`) follow a deliberate dark
   "instrument panel" aesthetic — near-black substrate, a faint grid,
   monospace type, hue used only to mean something (see `ui/app/globals.css`,
   headed "INSTRUMENT"). This file describes `/live` as light gradients
   (`from-slate-50 to-slate-100`), white cards with shadows, and 🟢🟡🔴 emoji
   traffic lights — a different visual language entirely. Since one of the
   three prizes here is judged on aesthetics and the whole system is
   designed to "read as one system, not nine separately-designed pages," a
   `/live` route in a conflicting style is a real risk to that prize, not a
   style nitpick.
2. **`/live` re-implements something the codebase's own comments say was
   deliberately retired.** Sheet 01 (`/`, the System sheet)'s header comment
   explicitly explains that "System" (build-state) and "Live run" used to be
   two separate screens and were merged into one screen with an overlay
   switch, because splitting them meant "the diagram in front of you was
   always the wrong one for whatever you wanted to ask next." A standalone
   `/live` route may be intentionally reviving a simplified, projector-only
   version of that view (legitimate — a stripped single-purpose screen for a
   big screen while presenting can be a reasonable, separate thing), or it
   may just be an unaware duplicate of a decision already made. Worth a
   two-minute look at both routes side by side to decide which it is before
   the day, rather than discovering the divergence live.

Everything else below (component props, event schema, styling notes,
troubleshooting table, replay strategy) checked out against the real files
and is accurate as documented.

## The Stack

**Frontend:** Next.js 13+ (App Router)  
**Styling:** Tailwind CSS  
**Data source:** JSON files (`out/forecast.json`, `out/events.ndjson`)  
**Deployment:** Local dev server (no backend needed)  

---

## Components Overview

### 1. Live Dashboard (`ui/app/live/page.tsx`)

**Purpose:** Real-time pipeline monitoring. Judges watch this while the pipeline runs.

**What it shows:**
- Stage progress (9 stages, animated progress bar)
- Elapsed time (start-to-now counter)
- Cost tracking (spent vs. budget)
- EPS forecast vs. consensus (with bar chart)
- Confidence indicator (🟢 🟡 🔴 traffic light)
- Top key drivers from lenses (sorted by impact)
- Event stream log (last 10 events from `events.ndjson`)

**Polling strategy:**
- Polls `out/events.ndjson` every 1 second
- Parses newline-delimited JSON (not a standard JSON array)
- Updates state incrementally (doesn't re-fetch entire file)
- Shows "Waiting for pipeline to start..." if no events yet

**Key state shape:**
```typescript
interface ForecastState {
  ticker: string;
  asOf: string;
  stage: string; // current stage name
  stageIndex: number; // 0-8
  totalStages: number; // 9
  elapsedSeconds: number;
  costSoFar: number;
  costBudget: number; // default 1.5
  consensusEps: number | null;
  forecastEps: number | null;
  keyDrivers: Array<{ lens: string; impact: number; description: string }>;
  confidence: number | null; // 0-100
  status: 'running' | 'complete' | 'error';
  errorMessage?: string;
}
```

**Event schema it expects:**
```json
{
  "event_type": "stage_started" | "stage_complete" | "forecast_produced" | "lens_complete" | "error",
  "stage": "STAGE_NAME",
  "ticker": "AAPL",
  "timestamp": "2026-08-16T14:32:15Z",
  "cost_so_far": 0.47,
  "message": "optional text"
}
```

**Styling notes:**
- Gradient background: `from-slate-50 to-slate-100`
- Cards: White background with shadow
- Progress bars: Blue (#3b82f6)
- Status bars: Context-colored (green if >0, red if <0)
- Grid layout: 2 columns on mobile, 4 on desktop

---

### 2. Event Stream Monitor (`ui/components/EventStreamMonitor.tsx`)

**Purpose:** Display raw event log in real-time.

**What it shows:**
- Last 10 events from `out/events.ndjson`
- Timestamp + event type + stage (if applicable) + message
- Dark terminal-style display

**Input props:**
```typescript
interface EventStreamMonitorProps {
  events: any[]; // Array of parsed event objects
}
```

**Color coding:**
- Timestamp: Blue (#60a5fa)
- Event type: Green (#4ade80)
- Stage name: Yellow (#facc15)
- Message text: Light gray (#d1d5db)
- Background: Slate-900 (dark)

**Behavior:**
- Truncates to 10 newest events (but shows all if provided)
- Monospace font (for log feel)
- Max height 256px with scroll
- Shows "Waiting for events..." if empty

---

### 3. Comparison Chart (`ui/components/ComparisonChart.tsx`)

**Purpose:** Side-by-side visualization of consensus vs. forecast EPS.

**What it shows:**
- Consensus EPS bar (blue, left)
- Forecast EPS bar (green if >consensus, red if <consensus, right)
- Both bars labeled with dollar values
- Percentage difference below bars
- Summary text: "We forecast X% above/below consensus"

**Input props:**
```typescript
interface ComparisonChartProps {
  consensus: number; // e.g., 2.15
  forecast: number; // e.g., 2.28
}
```

**Calculations:**
```
maxVal = Math.max(consensus, forecast) * 1.1  // 10% padding
consensusWidth = (consensus / maxVal) * 100
forecastWidth = (forecast / maxVal) * 100
diff = ((forecast - consensus) / consensus) * 100
```

**Color logic:**
- Consensus bar: Always blue
- Forecast bar: Green if `diff > 0`, Red if `diff < 0`
- Difference text: Green if positive, Red if negative

**Styling:**
- Bars: 32px height, rounded corners
- Labels: Positioned left (metric name) and right (value)
- Summary box: Light background with left border accent

---

### 4. Confidence Indicator (`ui/components/ConfidenceIndicator.tsx`)

**Purpose:** Show how confident the system is in the forecast (0–100%).

**What it shows:**
- Confidence score (large, bold percentage)
- Progress bar (animated fill)
- Traffic light emoji (🟢 ≥75%, 🟡 60–74%, 🔴 <60%)
- Breakdown text explaining what confidence means

**Input props:**
```typescript
interface ConfidenceIndicatorProps {
  confidence: number; // 0-100
}
```

**Confidence tiers:**
- **🟢 75–100%:** "High confidence: Multiple lenses agree"
- **🟡 60–74%:** "Medium confidence: Some lens disagreement"
- **🔴 0–59%:** "Low confidence: Limited evidence"

**Color logic:**
- Background: Depends on confidence tier
  - Green: `bg-green-100`
  - Yellow: `bg-yellow-100`
  - Red: `bg-red-100`
- Progress bar: Green, yellow, or red accordingly
- Text: Corresponding tier color

**Styling:**
- Large container with rounded corners
- Progress bar: 12px height, rounded edges
- Supports dark mode (currently light-focused; easy to add dark variant)

---

### 5. Narrative One-Pager (`ui/app/narrative/page.tsx`)

**Purpose:** Print-friendly page for judges to take home. Explains the thesis in detail.

**What it shows:**
- Title + thesis (one sentence)
- Our forecast + confidence
- Why consensus moved (mechanism explanation)
- "Why We Differ" section (top 3 reasons with evidence + quotes + impact)
- "What Could Be Wrong" section (2–3 risks)
- Full 400–500 word narrative prose
- Styled for print (no background colors, readable fonts)

**Data source:**
- Reads from `out/forecast.json`
- Expects key: `narrative` with structure below

**Expected narrative shape:**
```typescript
interface NarrativeData {
  title: string; // e.g., "Why We're Different on AAPL"
  thesis: string; // One sentence
  our_forecast: string; // e.g., "$2.28 EPS (67% confidence)"
  consensus_context: string; // Prose explaining consensus movement
  our_case: Record<string, {
    evidence: string; // Specific lens finding
    quote?: string; // Verbatim from source
    impact: string; // e.g., "+2.3% vs consensus"
  }>;
  risks: string[]; // Array of 2-3 risk strings
  narrative: string; // Full 400-500 word prose
}
```

**Styling:**
- Print-optimized CSS: `@media print { ... }`
- No background colors (saves ink)
- Serif fonts for readability
- Generous margins (p-12 default, p-8 on print)
- Section breaks with subtle borders
- Quotes indented with left border

**Access:** `http://localhost:3000/narrative`

**Print workflow:**
1. Open page
2. `Ctrl+P` (or right-click → Print)
3. Save as PDF or print directly
4. Hand out to judges

---

## Integration Points

### How the Pipeline Feeds Data

**Live Dashboard:**
```
Pipeline writes → out/events.ndjson (line-by-line)
                    ↓
           Dashboard polls every 1 sec
                    ↓
           Parses latest unread lines
                    ↓
           Updates ForecastState
                    ↓
           Re-renders (100ms debounce recommended)
```

**Narrative Page:**
```
Pipeline writes → out/forecast.json
                    ↓
           Page loads (one-time, on mount)
                    ↓
           Parses narrative field
                    ↓
           Renders sections
```

### Events Schema (What Pipeline Writes)

**Stage events:**
```json
{ "event_type": "stage_started", "stage": "ACQUIRE", "timestamp": "..." }
{ "event_type": "stage_complete", "stage": "ACQUIRE", "cost_so_far": 0.12, "timestamp": "..." }
```

**Lens events:**
```json
{ 
  "event_type": "lens_complete", 
  "lens_name": "Demand", 
  "impact_bps": 230, 
  "description": "Found capex cycle",
  "timestamp": "..." 
}
```

**Forecast event:**
```json
{
  "event_type": "forecast_produced",
  "forecast": {
    "ticker": "AAPL",
    "consensusEps": 2.15,
    "forecastEps": 2.28,
    "confidencePercent": 67,
    ...
  }
}
```

**Error event:**
```json
{ "event_type": "error", "stage": "ANALYSE", "message": "Lens X failed", "timestamp": "..." }
```

---

## Customization Points (If Needed Tomorrow)

### Change Polling Frequency
**File:** `ui/app/live/page.tsx` (line ~60)
```typescript
const interval = setInterval(pollEvents, 1000); // Change 1000 to desired ms
```

### Change Cost Budget
**File:** `ui/app/live/page.tsx` (line ~80)
```typescript
costBudget: 1.5, // Change to your actual budget
```

### Change Confidence Thresholds
**File:** `ui/components/ConfidenceIndicator.tsx` (line ~20)
```typescript
if (conf >= 75) return 'text-green-600'; // Adjust these numbers
if (conf >= 60) return 'text-yellow-600';
```

### Change Stage Names
**File:** `ui/app/live/page.tsx` (line ~25)
```typescript
const STAGES = [
  'ACQUIRE', 'STRUCTURE', 'MODEL', 'ANALYSE', 'RECONCILE', 
  'CHALLENGE', 'JUDGE', 'POSITION', 'OUTPUT'
];
// Change if pipeline stages differ
```

### Narrative Styling (Print)
**File:** `ui/app/narrative/page.tsx` (print CSS)
- Already optimized for A4 size
- Change margin: `p-8` to `p-12` if you want more whitespace
- Add `print:break-after-page` to force page breaks if needed

---

## Known Issues & Solutions

| Issue | Cause | Fix |
|-------|-------|-----|
| Dashboard shows "Waiting..." forever | Pipeline didn't start or crashed | Check `out/events.ndjson` exists; run pipeline with `--verbose` |
| Events log shows duplicate events | Polling re-reads entire file | Uses `lastPosition` to skip already-read lines; check for file truncation |
| Confidence shows 0% or 100% | LLM didn't return confidence score | Check `forecast.json` has `confidence_percent` field |
| Narrative page shows "No narrative available" | Pipeline didn't generate narrative | Check pipeline includes narrative stage; verify `out/forecast.json` has `narrative` key |
| Print preview looks bad | CSS media query issue | Check `@media print` styles; test with `Ctrl+P` |
| Bars don't render (ComparisonChart) | NaN in maxVal calculation | Check `consensus` and `forecast` are numbers, not strings or null |

---

## Performance Considerations

**Live Dashboard:**
- Polling every 1 second is fine for single run
- Debounce state updates if you want (currently re-renders on each poll)
- `events` array shouldn't exceed 10–50 items (trimmed automatically)

**Narrative Page:**
- Loads once on mount (not polling)
- Safe to leave open while pipeline runs
- Print-friendly: no animations or heavy styling

**Overall:**
- All data is local JSON (no server)
- No API calls from frontend
- UI layer is stateless (can replay old runs by pointing to different JSON)

---

## Replay Capability (Demo Insurance)

Because data comes from JSON files (not live API), you can **replay any completed run:**

```
1. Save out/forecast.json and out/events.ndjson from a successful run
2. Rename to, e.g., out/forecast_backup.json
3. If live API dies during presentation:
   - Copy backup files back to out/
   - Reload dashboard
   - Everything works as if pipeline just completed
```

This is your safety net if live data connection fails mid-demo.

---

## Deployment Notes (If Moving Beyond Local Dev)

- **No backend needed:** This is purely static HTML/JSON
- **Next.js static export:** `npm run build` works without a server
- **File serving:** Just serve `out/.next/static/` + point to `out/` for JSON
- **CORS:** Not an issue (all local, or CORS headers for remote JSON serve)
- **Caching:** Set `Cache-Control: no-cache` for `events.ndjson` (needs freshness)

---

## Checklist Before Presenting

- [ ] Live dashboard loads at `http://localhost:3000/live`
- [ ] Narrative page loads at `http://localhost:3000/narrative`
- [ ] Font sizes readable on projector (test 3 feet away)
- [ ] Progress bar animates (test by running pipeline)
- [ ] Confidence indicator shows correct color (🟢 🟡 🔴)
- [ ] Narrative page prints without layout breaks
- [ ] You have 10+ printed one-pagers ready
- [ ] Backup screenshots saved (in case live API dies)

---

## Architecture Recap

```
Live Pipeline                UI Layer                Judges Experience
════════════════════════════════════════════════════════════════════════

1. Write events.ndjson ──→ Live Dashboard ──→ Watch progress in real-time
   (line-by-line)           (polls every 1s)    See EPS forecast appear
   
2. Write forecast.json ──→ Narrative Page ──→ Read & understand thesis
   (after pipeline done)     (loads once)      Take home printed copy
```

Zero server. Zero latency issues. Zero production complexity.

---

## One-Liner If Someone Asks "How Do I Modify This?"

> "All data is JSON. Dashboard code is in `ui/app/live/page.tsx`, narrative is `ui/app/narrative/page.tsx`. Both read from `out/` directory. Change styling in Tailwind classes, change polling logic in useEffect, change colors in conditional statements. Everything is vanilla React/Next.js, no special dependencies."

