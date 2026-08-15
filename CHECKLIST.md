# HACKATHON CHECKLIST — Agents vs Wall Street
**Date: August 16, 2026 | Time: 10:00–17:00 | Location: London**

---

## TONIGHT (Friday, August 15) — 2.5 Hours of Prep

### Environment Setup (30 min)
- [ ] Clone repo: `git clone <url> forecastertrial`
- [ ] Install Python deps: `cd forecastertrial && uv sync`
- [ ] Install Node deps: `cd ui && npm install`
- [ ] Verify build: `npm run build` (should complete without errors)
- [ ] Check Python version: `python --version` (must be 3.11+)
- [ ] Verify all tools installed: `uv`, `npm`, `python`

### Environment Configuration (10 min)
- [ ] Create/verify `.env` file in repo root
- [ ] Set `OPENAI_API_KEY=sk-...` (test key works)
- [ ] Set `OPENAI_MODEL=gpt-4-turbo` (or appropriate model)
- [ ] Optional: Set `LOG_LEVEL=INFO`
- [ ] Verify no secrets in git history

### Smoke Tests (30 min)
- [ ] Run: `uv run forecast sources --ticker NVDA`
  - [ ] No errors in console
  - [ ] Data fetched from all 5 sources (yfinance, sec, exa, fred, lse)
  - [ ] Output files created in `out/` directory
  - [ ] Check `out/acquired/NVDA/` folder exists
- [ ] Verify UI builds: `cd ui && npm run build`
  - [ ] No TypeScript errors
  - [ ] Build completes in <30 seconds
- [ ] Start dev server: `cd ui && npm run dev`
  - [ ] Loads at `http://localhost:3000`
  - [ ] Navigation works
  - [ ] Dashboard loads at `/live`
  - [ ] Narrative page loads at `/narrative`

### Code Review (30 min)
- [ ] Read [src/forecaster/data/protocol.py](src/forecaster/data/protocol.py)
  - [ ] Understand `DataSource` interface (methods + signatures)
  - [ ] Note `as_of` parameter requirement
  - [ ] Review `Estimate`, `Guidance` Pydantic models
- [ ] Read [src/forecaster/data/yfinance_source.py](src/forecaster/data/yfinance_source.py)
  - [ ] Understand error handling pattern
  - [ ] Note point-in-time validation
  - [ ] See how async/await works in adapter
- [ ] Review [src/forecaster/data/template_sponsor_source.py](src/forecaster/data/template_sponsor_source.py)
  - [ ] This is your template tomorrow
  - [ ] Understand TODO markers
  - [ ] Know where to fill in API details
- [ ] Read [src/forecaster/data/loader.py](src/forecaster/data/loader.py)
  - [ ] Find `sources = [...]` list
  - [ ] Know you'll add one line: `YourSponsorDataSource(...)`

### Documentation Review (20 min)
- [ ] Read [MASTER-PLAN.md](docs/MASTER-PLAN.md) — 9 pipeline stages
- [ ] Read [HACKATHON.md](HACKATHON.md) — full timeline + traps
- [ ] Read [QUICKREF.md](QUICKREF.md) — one-page reference
- [ ] Skim [CLAUDE.md](CLAUDE.md) — design principles (keep as reference)
- [ ] Review known traps section below (memorize)

### Budget & Cost Setup (10 min)
- [ ] Verify OpenAI account has $10+ credit
- [ ] Log into OpenAI dashboard
- [ ] Set cost alert at $5 spend (safeguard against runaway)
- [ ] Verify you can access API (small test call)

### Print These Documents
- [ ] Print [QUICKREF.md](QUICKREF.md) (one page, laminate if possible)
- [ ] Print [HACKATHON.md](HACKATHON.md) (timeline section, keep handy)
- [ ] Print this checklist
- [ ] Put all three in a folder you'll bring tomorrow

### Workspace Verification (5 min)
- [ ] `.env` file present and has API key ✓
- [ ] `src/forecaster/data/` folder has 20+ files ✓
- [ ] `ui/app/live/page.tsx` exists ✓
- [ ] `ui/app/narrative/page.tsx` exists ✓
- [ ] `src/forecaster/llm/prompts/narrative_generation.yaml` exists ✓

---

## TOMORROW MORNING — Before 10:00 AM

### System Check (15 min)
- [ ] Internet connection stable (test download speed)
- [ ] API key still valid (test one small API call)
- [ ] Battery charged (or power adapter available)
- [ ] Noise level acceptable (test mic if presenting remotely)
- [ ] Backup: Have laptop ready in case primary fails

### Mental Prep (5 min)
- [ ] Read QUICKREF.md one more time
- [ ] Review known traps (see section below)
- [ ] Know the 3 stages you'll focus on:
  1. Write DataSource adapter (10:30–14:30)
  2. Run full pipeline (14:30–15:30)
  3. Present forecast (16:45–17:00)

### Open Reference Materials (5 min)
- [ ] Print out + have [QUICKREF.md](QUICKREF.md) visible
- [ ] Print out + have [HACKATHON.md](HACKATHON.md) visible
- [ ] Have [protocol.py](src/forecaster/data/protocol.py) open in VS Code
- [ ] Have [template_sponsor_source.py](src/forecaster/data/template_sponsor_source.py) open

---

## 10:00–10:30 — SETUP & READ FEED SPEC

### Briefing Reception (10 min)
- [ ] Write down the company **TICKER**
- [ ] Write down the **DATA FEED URL**
- [ ] Write down **AUTHENTICATION** method (API key / OAuth / username-password)
- [ ] Copy any **API DOCUMENTATION** link or PDF
- [ ] Note if data is **GAAP or NON-GAAP** (CRITICAL)

### Feed Specification Review (20 min)
- [ ] Read the API spec completely (don't skim)
- [ ] Note all available endpoints:
  - [ ] Earnings estimates? (Y/N)
  - [ ] Guidance history? (Y/N)
  - [ ] Historical actuals? (Y/N)
  - [ ] Revisions? (Y/N)
  - [ ] Date estimates were made? (Y/N)
- [ ] Check **Point-in-Time Support:**
  - [ ] Can you query estimates "as of" a past date? (Y/N)
  - [ ] Does API return data filed before `as_of`? (Y/N)
  - [ ] Or does it always return current? (RED FLAG if current-only)
- [ ] Rate limits?
  - [ ] Requests per minute?
  - [ ] Requests per hour?
  - [ ] Any burst limits?
- [ ] Timeout requirements?
  - [ ] Max response time?
  - [ ] Retry strategy?
- [ ] Test authentication:
  - [ ] Can you ping the API with their key?
  - [ ] Do you get a 200 response?
  - [ ] Save the auth method in a comment for later

---

## 10:30–14:30 — WRITE DATASOURCE ADAPTER

### Checkpoint 11:00 (Auth & First Call)
- [ ] API authentication working
- [ ] Can make first successful API call
- [ ] Response JSON looks reasonable
- [ ] No timeout errors
- [ ] Console shows debug output

**If stuck:** Check API key, URL, headers. Test with curl first.

### Checkpoint 12:00 (Schema Parsing)
- [ ] Response JSON parsing into Python objects
- [ ] At least 10 tickers return data successfully
- [ ] Field mapping correct (estimate→EPS, date→filed_date, etc.)
- [ ] No unit mismatches (millions vs. thousands)
- [ ] Data types match expected (float for EPS, int for year/quarter)

**If stuck:** Print one response JSON, manually map fields. Check Estimate Pydantic model.

### Checkpoint 13:00 (Integration & Smoke Test)
- [ ] Adapter file created: `src/forecaster/data/your_source.py`
- [ ] Added to loader.py: One line in `sources = [...]`
- [ ] Run: `uv run forecast sources --ticker NVDA`
  - [ ] Your adapter shows in output
  - [ ] No errors from your adapter
  - [ ] Data flows through pipeline
- [ ] At least 3 tickers tested successfully

**If stuck:** Check loader.py import and list. Verify adapter instantiation.

### Checkpoint 14:00 (Error Handling)
- [ ] API timeouts handled (return empty list, log error)
- [ ] Invalid JSON handled (try/except on parse)
- [ ] Missing fields handled (use .get(), provide defaults)
- [ ] Point-in-time validation in place (check filed_date ≤ as_of)
- [ ] Adapter doesn't crash pipeline on bad data

**If stuck:** Look at yfinance_source.py error handling pattern.

### Code Checklist (Before 14:30)
- [ ] All methods have `as_of` parameter
- [ ] Returns empty list on no data (doesn't raise)
- [ ] Rejects data filed after `as_of`
- [ ] Every EPS has `basis` field (GAAP or NON_GAAP)
- [ ] Logging on entry/exit of each method
- [ ] No hardcoded credentials (uses env vars)
- [ ] Timeout set to 30 seconds max
- [ ] Async/await pattern correct (if async)

---

## 14:30–15:30 — RUN FULL PIPELINE

### Start Pipeline (14:30)
```bash
export TICKER=COMPANY
uv run forecast run --ticker $TICKER --asof 2026-08-16
```
- [ ] Command accepted (no immediate errors)
- [ ] Pipeline starts (Stage 1: ACQUIRE)
- [ ] Real-time events appear in `out/events.ndjson`

### Monitor in Real-Time (14:30–15:30)
- [ ] Open second terminal: `tail -f out/events.ndjson | grep -E "stage|error"`
- [ ] Watch for errors (search for `"error"` in output)
- [ ] Monitor cost:
  - [ ] Should be < $0.50 by stage 5
  - [ ] Should be < $1.50 by completion
  - [ ] If > $2.00, STOP pipeline (Ctrl+C)
- [ ] Check UI dashboard: `http://localhost:3000/live`
  - [ ] Progress bar animates
  - [ ] Stage updates in real-time
  - [ ] Cost counter updates
  - [ ] No 404 errors

### Stages Progression (Watch for These)
```
✓ ACQUIRE (2-3 min) — fetching data
✓ STRUCTURE (1 min) — building evidence
✓ MODEL (1 min) — 3-statement model
✓ ANALYSE (3-4 min) — 9 lenses run in parallel
✓ RECONCILE (1 min) — verify citations
✓ CHALLENGE (1 min) — argue for/against
✓ JUDGE (2-3 min) — expensive LLM call
✓ POSITION (1 min) — blend forecast
✓ OUTPUT (30 sec) — write JSON
```

### If Pipeline Hangs (>5 min at any stage)
- [ ] Check `out/events.ndjson` for last event
- [ ] Stop pipeline: `Ctrl+C`
- [ ] Check error log: last 50 lines
- [ ] Likely causes:
  - [ ] Data source timeout → increase timeout in adapter
  - [ ] LLM call slow → wait (or check API status)
  - [ ] Infinite loop → check lens code (shouldn't happen)
- [ ] Re-run with `--verbose` flag for more details

### If Pipeline Crashes
- [ ] Read error message completely
- [ ] Check `out/events.ndjson` for last successful stage
- [ ] Common fixes:
  - [ ] `PointInTimeViolation` → adapter returning future data
  - [ ] `Schema validation error` → response JSON doesn't match model
  - [ ] `API timeout` → sponsor's API slow or rate-limited
  - [ ] `GAAP/non-GAAP mismatch` → consensus vs estimates units wrong
- [ ] Try `--replay` to use cached data (bypasses adapter)
- [ ] If still broken, escalate to mentor/teammate

---

## 15:30–16:15 — VERIFY & DEBUG

### Output Verification
- [ ] File exists: `out/forecast.json`
- [ ] File is not empty (size > 1 KB)
- [ ] Can parse as JSON: `python -m json.tool out/forecast.json | head -50`

### Forecast Numbers Sanity Check
- [ ] `forecast_eps` present and non-null
- [ ] `consensus_eps` present and non-null
- [ ] EPS values are reasonable for the company (not -999 or 0.01)
- [ ] Forecast differs from consensus by at least ±1% (not identical)
- [ ] `confidence_percent` is 40–85% (not 0, not 100)

### Quality Gates (Run These)
```bash
uv run forecast verify --ticker $TICKER
```
- [ ] Verification completes without error
- [ ] No point-in-time violations found
- [ ] Arithmetic checks pass
- [ ] Output readable as JSON

### Lens Health Check
- [ ] At least 5 lenses returned evidence
- [ ] Max 2 lenses abstained (no findings)
- [ ] Each lens has `claim_ids` non-empty
- [ ] Each claim has a `verbatim_quote`

**Inspect:** `python -c "import json; f=json.load(open('out/forecast.json')); print(f'Lenses: {len(f[\"lenses\"])}, Evidence: {sum(len(l.get(\"claim_ids\", [])) for l in f[\"lenses\"])}')"` 

### Narrative Check
- [ ] Narrative present in `out/forecast.json`
- [ ] `narrative.title` present
- [ ] `narrative.thesis` is one sentence
- [ ] `narrative.our_case` has 3 reasons
- [ ] `narrative.narrative` is 400–500 words
- [ ] `narrative.risks` has 2–3 items

### Baseline Comparison
- [ ] Baseline forecast: `consensus × 1.02` = $X.XX EPS
- [ ] Your forecast: $Y.YY EPS
- [ ] Is your forecast more informative than baseline?
  - [ ] If forecast == baseline exactly, λ ≈ 0 (you added no value — honest, but not impressive)
  - [ ] If forecast ±5%, you found something (good)
  - [ ] If forecast ±15%+, verify you didn't make an error

### If Something Looks Wrong

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Confidence = 95% | Overconfident | Check if all lenses agree (unusual) |
| Confidence = 5% | Underconfident | Lenses disagreed; this is honest but weak |
| EPS = $0.01 | Unit error | Check: millions vs. thousands |
| EPS = -$50 | Model structural error | Verify model reproduced historical quarters |
| Forecast = Consensus exactly | λ = 0 | This is OK; it means data didn't justify deviation |
| Only 2 lenses returned data | Lenses abstained | Check `out/events.ndjson` for lens errors |

---

## 16:15–16:45 — UI TUNING & PRESENTATION PREP

### Live Dashboard (`http://localhost:3000/live`)
- [ ] Loads without 404
- [ ] Stage progress bar visible
- [ ] EPS forecast displays
- [ ] Confidence indicator shows
- [ ] Top drivers list appears
- [ ] Event log updates in real-time
- [ ] Readable on your demo display/projector

**Font size check:** Step back 3 feet — is text readable?

### Narrative Page (`http://localhost:3000/narrative`)
- [ ] Loads without 404
- [ ] Title displays
- [ ] Thesis readable
- [ ] "Why we differ" section clear
- [ ] Risks section has 2–3 bullets
- [ ] Full narrative (400–500 words) visible
- [ ] Page prints without layout issues: `Ctrl+P`

### Optional Polish (If Time)
- [ ] Customize company logo/colors in dashboard (if available)
- [ ] Hide abstained lenses from display
- [ ] Adjust font sizes for projector
- [ ] Test dark mode if presenting in dark room

### Presentation Narrative (Write on Paper)
- [ ] Write a 90-second summary:
  - 20 sec: "What did consensus do?"
  - 40 sec: "What did we find? (top 3 lenses)"
  - 20 sec: "Why are we different? Here's our thesis."
  - 10 sec: "Here's the risk that could prove us wrong"
- [ ] Practice saying it out loud (it should sound natural, not scripted)
- [ ] Rehearse pointing at the dashboard while talking

### Backup Screenshots (In Case Live API Dies)
```bash
# Take screenshots of all key outputs
npx playwright screenshot out/forecast.json screenshot_forecast.png
```
- [ ] Screenshot of live dashboard (mid-run ideal)
- [ ] Screenshot of forecast numbers
- [ ] Screenshot of narrative page
- [ ] Save to USB drive as backup

---

## 16:45–17:00 — PRESENT TO JUDGES

### Setup (5 min before presentation)
- [ ] Dashboard loaded at `http://localhost:3000/live`
- [ ] Narrative page open in second browser tab
- [ ] Printed one-pager ready to hand out
- [ ] Nervous energy converted to enthusiasm ✓

### Presentation Flow (90 seconds)

**"Thank you. Here's our forecast for [TICKER]."**

1. **(20 sec) Context: Why consensus moved**
   - Point to live dashboard
   - "Consensus walked down 3% during the quarter because [specific reason from data]"
   - Show the consensus_eps number

2. **(40 sec) Our case: Top 3 lenses**
   - Show Key Drivers section on dashboard
   - "We found three independent signals that consensus missed:"
   - Lens 1: [Specific evidence + impact]
   - Lens 2: [Specific evidence + impact]
   - Lens 3: [Specific evidence + impact]

3. **(20 sec) The forecast**
   - Point to EPS comparison chart
   - "We forecast $X.XX, which is [+/- %] vs consensus $Y.YY"
   - Point to confidence indicator
   - "We're [X]% confident because [one key reason]"

4. **(10 sec) The risk**
   - "What could prove us wrong?"
   - [One sentence on top risk]

**"Thank you. Any questions?"** [Hand out printed one-pager]

### Do NOT Do
- ❌ Explain the architecture (judges don't care how it works)
- ❌ Recite all 9 lenses (too much detail)
- ❌ Say "we used AI" (they assume you did; focus on the insight)
- ❌ Make excuses if confidence is low (say "low confidence is honest")
- ❌ Claim certainty (say "this is our best estimate given the data we have")

### If Asked Questions

| Question | Answer |
|----------|--------|
| "How confident are you?" | "X%. Here's why we have this level of confidence: [reason]" |
| "What would prove you wrong?" | "[Specific risk]. If that happens, consensus was right." |
| "Why is your forecast different?" | Point to a lens on the dashboard. "This lens found [evidence], which we weighted as material." |
| "What was the hardest part?" | "Getting point-in-time data correct. Here's what we did to validate it." |
| "Can you show me the model?" | "Sure. [Show notebook/code.] The key assumption is: [key assumption]. Here's how it performed historically." |
| "What's your accuracy?" | "On backtest, we beat consensus × 1.02 with MAE of [number]." |

---

## KNOWN TRAPS — Memorize These

### 1. GAAP vs Non-GAAP ⚠️ MOST COMMON
- **Consensus:** Non-GAAP (analysts' adjusted earnings)
- **SEC Filings:** GAAP (regulatory, everything included)
- **Gap:** Can be 20–40% (directional!)
- **Action:** Check every EPS's `basis` field; log mismatches; reconciler will catch and drop mismatched lenses

### 2. Point-in-Time Violation (Silent Killer)
- Your adapter returns data filed **after** `as_of`
- System rejects it, but error is hard to debug
- **Action:** Test adapter with `as_of = 2026-06-30` and verify no September data returns

### 3. Units Mismatch (Millions vs Thousands)
- Revenue in millions, EPS in dollars → breaks silently
- Arithmetic stays internally consistent (only sanity bands catch it)
- **Action:** Print one row from adapter response; manually verify units

### 4. Consensus Too Stale
- Feed data is 5+ days old
- You're forecasting with stale information
- **Action:** Check feed timestamp; warn judges if older than 2 business days

### 5. Prompt Caching Broken by Parallelism
- 9 lenses run in parallel → caching sees different prefixes → no hits
- Cost explodes silently; cache-write huge, cache-hit zero
- **Action:** This is a system-level issue, not your adapter problem; just be aware if cost > $3

### 6. yfinance `earnings_estimate` is Not Point-in-Time
- It returns current consensus, not historical
- Using it for backtesting = look-ahead bias
- **Action:** Already fixed in codebase; don't recreate this bug

### 7. Free-form Dict LLM Output
- Asking LLM for `dict[str, float]` returns empty or prose instead
- **Action:** Already fixed in narrative prompt (asks for named fields); don't recreate

---

## SUCCESS CRITERIA (What Judges Score)

### 1. Accuracy ✓
- Forecast beats baseline (consensus × 1.02)
- Baseline MAE = 0.1868; you need to beat it (or equal it honestly)

### 2. Architecture ✓
- Lenses independently reasoned (not seeing each other)
- Properly weighted by materiality (not averaged)
- Each claim has a source + verbatim quote

### 3. Aesthetics ✓
- Live demo works (dashboard + narrative)
- Judges understand the thesis in 90 seconds
- No crashes or 404 errors during presentation

### Bonus (Nice to Have)
- λ is well-fitted (not just guessed)
- Confidence bands reasonable (not over/under-confident)
- You can explain the forecast in your own words

---

## EMERGENCY CONTACTS / Escalation

| Problem | First Step | Then |
|---------|-------------|------|
| API won't auth | Check `.env` key + URL typo | Test with curl; contact API team |
| Pipeline crashes | Check `events.ndjson` last event | Run with `--verbose`; restart |
| Forecast obviously wrong | Check consensus is current; model MAE | Verify top lens makes sense |
| Cost spiraling | Kill pipeline immediately | Check logs for infinite loop |
| Judges don't understand | Re-read QUICKREF.md; simplify message | Focus on one lens instead of all 9 |

---

## FINAL CHECKLIST — 5 Minutes Before Presentation

- [ ] Dashboard running and responsive
- [ ] Narrative page loaded and readable
- [ ] Printed one-pagers ready (10+ copies)
- [ ] You can explain the forecast in 90 seconds
- [ ] You know the top 3 lenses and their evidence
- [ ] You can articulate one key risk
- [ ] Projector displays dashboard clearly (tested)
- [ ] Backup screenshots saved to USB
- [ ] You are excited and ready ✓

---

**Good luck. You've got this. 🚀**

*Print this checklist. Check off items. Bring it with you. Reference it constantly.*
