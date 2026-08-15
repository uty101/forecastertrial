# HACKATHON.md — Day-of Playbook

**Event:** Agents vs Wall Street  
**Date:** August 16, 2026  
**Time:** 10:00–17:00 (7 hours)  
**Goal:** Forecast earnings for an unknown company using an unknown data feed, beat consensus by >2%, and present to judges.

---

## Pre-Hackathon Checklist (Do Tonight, Friday August 15)

### Setup (30 min)

- [ ] Clone this repo to your demo machine (not a VM)
- [ ] `uv sync` (install Python dependencies)
- [ ] `cd ui && npm install` (install Node dependencies)
- [ ] `cd ui && npm run build` (verify build succeeds)
- [ ] Verify `python --version` shows 3.11+

### Smoke Tests (30 min)

- [ ] Run `uv run forecast sources --ticker NVDA` — must pass without errors
- [ ] Verify `out/` directory was created
- [ ] Read output structure (JSON shape must match schema)
- [ ] Check that all 5 data sources returned data

### Code Review (30 min)

- [ ] Read [DataSource protocol](src/forecaster/data/protocol.py)
- [ ] Skim [yfinance example implementation](src/forecaster/data/yfinance_source.py)
- [ ] Review [sponsor_source.py template](src/forecaster/data/sponsor_source.py) — this is the shape you'll write tomorrow
- [ ] Verify [loader.py](src/forecaster/data/loader.py) — know how to add a new source

### UI Verification (30 min)

- [ ] Run `cd ui && npm run dev` and verify http://localhost:3000 loads
- [ ] Verify `out/` directory gets polled correctly (use mock JSON if needed)
- [ ] Check live dashboard loads at `/live` route
- [ ] Test responsive layout on your demo display (often a projector)

### Documentation Review (20 min)

- [ ] Skim [MASTER-PLAN.md](docs/MASTER-PLAN.md) — know the 9 stages
- [ ] Review known traps section below (memorize these)
- [ ] Keep [CLAUDE.md](CLAUDE.md) open during the event for reference

### Budget & Cost (10 min)

- [ ] Verify OpenAI API key is set in `.env` or environment
- [ ] Confirm you have $10+ credit (budget is ~$1.50 per full run)
- [ ] Set a cost alert in OpenAI dashboard at $5 to catch runaway spend

**Total prep time: ~2.5 hours.** Do this **tonight**, not tomorrow morning.

---

## Tomorrow: 10:00–17:00 Timeline

### 10:00–10:30 — Setup & Briefing (30 min)

**You receive:**

- Company ticker
- Data feed specification (URL, schema, auth method)
- Expected earnings data format

**Do this:**

1. [ ] Confirm internet connectivity on demo machine
2. [ ] Open this playbook and [DataSource protocol](src/forecaster/data/protocol.py) side by side
3. [ ] Read the data feed spec completely — note:
   - Does it have earnings estimates? guidance? historical actuals?
   - What's the point-in-time requirement? (date field in the data)
   - Authentication: API key, OAuth, username/password?
   - Rate limits? Timeout requirements?
   - Data is GAAP or non-GAAP?

### 10:30–14:30 — Write DataSource Adapter (4 hours)

**Deliverable:** One Python class (`src/forecaster/data/your_source.py`) that implements the `DataSource` protocol.

**Template:**

```python
from datetime import datetime
from forecaster.data.protocol import DataSource, Estimate, Guidance

class YourSponsorDataSource(DataSource):
    """Adapter for the sponsor's earnings data feed."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://sponsor-api.example.com"

    async def earnings_estimates(
        self, ticker: str, as_of: datetime
    ) -> list[Estimate]:
        """Fetch consensus estimates as they stood on as_of date."""
        response = await self.client.get(
            f"{self.base_url}/estimates",
            params={"ticker": ticker, "as_of": as_of.isoformat()}
        )
        return [Estimate.parse_obj(e) for e in response.json()]

    async def guidance_history(
        self, ticker: str, as_of: datetime
    ) -> list[Guidance]:
        """Fetch company guidance issued before as_of."""
        ...
```

**Critical:**

- Respect `as_of` — never return data filed after that date
- Declare whether values are GAAP or non-GAAP in the `basis` field
- Handle errors gracefully (log and return empty list, don't crash)
- Implement timeout handling (30-second max per call)

**Progress checkpoints:**

- 11:00 — API authentication working, can fetch data
- 12:00 — Schema parsing working, 10 tickers return data
- 13:00 — Adapter integrated into loader, smoke test passes
- 14:00 — Timeout/error handling in place, adapter ready

**If stuck:**

- Check [yfinance_source.py](src/forecaster/data/yfinance_source.py) for reference
- Review [protocol.py](src/forecaster/data/protocol.py) for exact field names
- Print response to console and compare against schema

### 14:30–15:30 — Run Full Pipeline (1 hour)

**Do this:**

```bash
export TICKER=YOURCOMPANY
uv run forecast run --ticker $TICKER --asof 2026-08-16
```

**What happens:**

- Stages run sequentially: ACQUIRE → STRUCTURE → MODEL → ANALYSE → RECONCILE → CHALLENGE → JUDGE → POSITION → OUTPUT
- Real-time events written to `out/events.ndjson`
- Final forecast written to `out/forecast.json`
- Live dashboard updates at http://localhost:3000/live

**Monitoring:**

- Watch `out/events.ndjson` for errors (tail it in another terminal)
- If a stage hangs >5 min, check network (data source timeout?)
- If cost exceeds $1.50, stop and debug (likely infinite loop or bad data)

**If pipeline fails:**

1. [ ] Read the error message completely
2. [ ] Check `out/events.ndjson` for the last successful stage
3. [ ] Re-run with `--verbose` flag for detailed logs
4. [ ] Common fixes:
   - Data source timeout → increase timeout in adapter
   - Point-in-time violation → check data feed date handling
   - Schema mismatch → validate response JSON against schema

### 15:30–16:15 — Verify & Debug (45 min)

**Checklist:**

- [ ] Forecast is present in `out/forecast.json`
- [ ] Forecast EPS differs from consensus (by at least +/- 1%)
- [ ] Confidence score is between 40–85% (if outside, model may have issues)
- [ ] At least 5 lenses returned evidence
- [ ] Narrative was generated (should be in `out/forecast.json`)

**Quality gates:**

- Run `uv run forecast verify --ticker $TICKER` to check against golden data
- Verify no point-in-time violations: all data dates ≤ `as_of`
- Spot-check one lens output (does it cite sources? does the math check out?)

**If forecast looks wrong:**

- [ ] Is consensus walkdown too large? Check data feed has current estimates
- [ ] Is confidence too low? Some lenses may have abstained (check `events.ndjson`)
- [ ] Is EPS far from comparables? Check model structural error (`model_mae` in output)

### 16:15–16:45 — UI Tuning (30 min)

**Live dashboard should be running.** If not:

```bash
cd ui && npm run dev
# Opens http://localhost:3000/live
```

**Check:**

- [ ] Stage progress bar animates as pipeline runs
- [ ] EPS forecast displays correctly
- [ ] Confidence indicator shows
- [ ] Top 3 lenses appear with impact
- [ ] Narrative readable on projector (font size OK?)

**Optional tuning:**

- Add company logo if time permits
- Hide lenses that abstained (check `claim_ids` in output)
- Highlight the top driver (usually worth 30–50% of the difference)

### 16:45–17:00 — Present (15 min)

**Judges will ask:**

1. "Why does your forecast differ from consensus?"
2. "How confident are you?"
3. "What would prove you wrong?"
4. "What was the bottleneck?"

**Your answer should be 90 seconds:**

- "Consensus walked down 3% because [reason]. We found [evidence from top lens]. We're 67% confident because [driver 2] still has execution risk."

**Point to:**

- The live dashboard (shows the pipeline actually working)
- The narrative one-pager (available in `out/forecast.json`)
- The comparison chart (forecast vs consensus bars)

**Do NOT:**

- Explain the architecture (judges don't care)
- List all 9 lenses (pick top 3)
- Make excuses if confidence is low (say "low confidence is honest; we prefer humility to false certainty")

---

## Known Traps (Memorize These)

### 1. GAAP vs Non-GAAP (Most Common Cause of Failure)

- **Consensus is non-GAAP** (stripped of one-time items)
- **SEC XBRL is GAAP** (includes everything)
- Typical gap: 31% for DJIA stocks
- **Action:** Check every EPS figure's `basis` field; if mixed, reconciler will catch it and drop the lens

### 2. Point-in-Time Violation

- Your data source returns data filed **after** `as_of`
- This is look-ahead bias; system will reject it
- **Action:** Test your adapter with `as_of = 2026-06-30` and verify no September earnings

### 3. Units Mismatch (Millions vs Thousands)

- Revenue in millions, EPS in dollars → calculation breaks
- System catches this via sanity bands, but silent errors exist
- **Action:** Print one sample row from your adapter and verify units

### 4. Prompt Caching Broken by Parallelism

- Lenses run in parallel → caching sees different prefixes → no cache hits
- Cost explodes silently
- **Action:** Know this exists; if cost > $3 and you only ran once, debug caching

### 5. yfinance `earnings_estimate` is Not Point-in-Time

- It's current consensus, not historical
- For backtesting use `earnings_history.epsEstimate`
- **Action:** This is already fixed in code; just know it exists

### 6. Consensus Estim ates Are Walked Down During Quarter

- Analysts cut EPS 3.2% on average before results
- But 78% of companies beat the new bar
- **Action:** This is the thesis; not a bug

---

## File Structure You'll Use Tomorrow

```
forecastertrial/
├── src/forecaster/
│   ├── data/
│   │   ├── protocol.py          ← Read this for adapter interface
│   │   ├── yfinance_source.py   ← Copy this as template
│   │   ├── your_source.py       ← WRITE THIS
│   │   └── loader.py            ← Add your source here (1 line)
│   ├── cli.py                   ← Already handles `forecast run`
│   └── llm/prompts/
│       └── narrative_generation.yaml  ← Already written
├── ui/
│   ├── app/live/page.tsx        ← Live dashboard (already built)
│   └── components/
│       ├── EventStreamMonitor.tsx
│       ├── ComparisonChart.tsx
│       └── ConfidenceIndicator.tsx
├── out/                         ← Pipeline output (created at runtime)
│   ├── events.ndjson            ← Live event stream
│   ├── forecast.json            ← Final forecast + narrative
│   ├── model.json               ← 3-statement model
│   └── narrative.json           ← One-pager for judges
└── HACKATHON.md                 ← This file
```

---

## Emergency Contacts (During Event)

- **Can't authenticate to data feed?**
  - Check API key in `.env`
  - Verify base URL (typo?)
  - Check rate limiting (you at quota?)

- **Pipeline crashes mid-stage?**
  - Check `out/events.ndjson` for error
  - Re-run with `--verbose`
  - Try `--replay` to use cached data

- **Forecast looks obviously wrong?**
  - Check consensus estimate is current (not stale)
  - Check model structural error (`model_mae` in output)
  - Verify top lens actually makes sense

- **Cost spiraling?**
  - Kill pipeline immediately (Ctrl+C)
  - Check for infinite loop in lens (watch the logs)
  - Restart with smaller ticker for verification

---

## Success Criteria

You win if:

1. ✅ Forecast runs end-to-end without crashing
2. ✅ Forecast differs from consensus by >1% (in either direction)
3. ✅ Confidence is 40–85% (too high = overfit, too low = useless)
4. ✅ At least 5 lenses returned evidence
5. ✅ Narrative explains the thesis in 90 seconds
6. ✅ Judges understand why you differed and what the risks are

You **lose** if:

- ❌ Pipeline crashes before producing forecast
- ❌ Forecast is identical to consensus (λ = 0, which means system learned nothing)
- ❌ Confidence is >95% (system is overconfident)
- ❌ Can't explain the forecast in your own words
- ❌ Narrative is missing or unreadable

---

## Checklist for Demo Day (Print This & Bring)

```
☐ Demo machine has internet connection
☐ API key set in .env
☐ All dependencies installed (uv sync, npm install)
☐ UI builds without error (npm run build)
☐ Smoke test passes (forecast sources --ticker NVDA)
☐ Live dashboard loads (localhost:3000/live)
☐ Backup laptop ready (just in case)
☐ Printed copy of this playbook
☐ Note with company ticker and data feed URL (write these down as you get them)
☐ Pencil + paper to sketch narrative while pipeline runs
☐ Phone ready to photograph final output
☐ Confident smile :)
```

---

## The Thesis You're Defending

> **Consensus is not a forecast. It is analysts' good analysis with a thumb on the scale.**
>
> Analysts walk down estimates 3.2% during quarters but miss where consensus is structurally weak.
> Reproduce the analysis, strip the incentives, then ask: where is consensus weak?
>
> `forecast = consensus + λ · (own_estimate − consensus)`
>
> λ is fitted on backtest, never guessed. Our lenses see what individual analysts cannot.

Your job tomorrow: **prove this thesis works on the day's company.**

Good luck. You've got this. 🚀
