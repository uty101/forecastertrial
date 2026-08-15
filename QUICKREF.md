# QUICK REFERENCE — Agents vs Wall Street Day-of

**Print this out and bring it with you tomorrow.**

---

## 10:00–10:30 | Setup & Read Spec

**Receive:** Company ticker + data feed URL + schema  
**Do:**

1. Read the feed schema completely
2. Note: Is it GAAP or non-GAAP?
3. Check point-in-time requirement (date field)
4. Test network connectivity

---

## 10:30–14:30 | Write DataSource Adapter

**File:** `src/forecaster/data/your_source.py`

**Template (copy from `yfinance_source.py`):**

```python
class YourDataSource(DataSource):
    async def earnings_estimates(ticker, as_of) -> list[Estimate]:
        """Fetch estimates as of as_of date — no future data!"""

    async def guidance_history(ticker, as_of) -> list[Guidance]:
        """Company guidance issued before as_of"""
```

**Checkpoints:**

- 11:00: API auth working
- 12:00: 10 tickers fetch successfully
- 13:00: Integrated into loader + smoke test passes
- 14:00: Error handling done

**Critical:** Respect `as_of` — never return forward-looking data

---

## 14:30–15:30 | Run Full Pipeline

```bash
export TICKER=COMPANY_NAME
uv run forecast run --ticker $TICKER --asof 2026-08-16
```

**Watch:**

- `out/events.ndjson` for live progress
- `http://localhost:3000/live` for dashboard
- Cost in console (should be <$1.50)

**If it crashes:** Check `events.ndjson` for last successful stage

---

## 15:30–16:15 | Verify Output

**Checklist:**

- [ ] Forecast in `out/forecast.json`
- [ ] EPS differs from consensus (>1%)
- [ ] Confidence 40–85%
- [ ] 5+ lenses returned evidence
- [ ] Narrative generated

**Run:** `uv run forecast verify --ticker $TICKER`

---

## 16:15–16:45 | UI Tuning

**Dashboard:** `http://localhost:3000/live`  
**Narrative:** `http://localhost:3000/narrative`

**Check:**

- Stage progress animates
- EPS displays correctly
- Narrative readable on projector
- Top 3 drivers visible

---

## 16:45–17:00 | Present (90 seconds)

**Point to:**

1. **Live dashboard** → "Our pipeline actually works"
2. **EPS forecast bar chart** → "Here's why we differ"
3. **Narrative one-pager** → "Here's our thesis"

**Say:**

> "Consensus walked down X% because [reason]. We found [evidence]. We're Y% confident because [risk]."

**Do NOT:**

- Explain architecture
- List all 9 lenses
- Make excuses

---

## Known Traps (Memorize)

| Trap                    | Fix                                 |
| ----------------------- | ----------------------------------- |
| GAAP vs non-GAAP        | Check `basis` field in adapter      |
| Point-in-time violation | Test adapter with old `as_of` dates |
| Units mismatch          | Print sample row, verify millions   |
| Consensus too old       | Verify feed has current estimates   |
| Cost spiraling          | Check logs for infinite loops       |

---

## Files You'll Touch

| File                                 | What           | When        |
| ------------------------------------ | -------------- | ----------- |
| `src/forecaster/data/your_source.py` | **WRITE THIS** | 10:30–14:30 |
| `src/forecaster/data/loader.py`      | Add 1 line     | ~13:30      |
| `ui/app/live/page.tsx`               | Already done   | Just use it |
| `http://localhost:3000/live`         | Watch this     | 14:30+      |
| `http://localhost:3000/narrative`    | Print this     | 16:45       |

---

## Emergency Fixes

**API won't authenticate?**

- Check `.env` has `SPONSOR_API_KEY=xxx`
- Check URL typo

**Pipeline stuck?**

- Kill it (Ctrl+C)
- Check `out/events.ndjson` for error
- Re-run with `--verbose`

**Forecast obviously wrong?**

- Check consensus is current (not stale)
- Check model MAE (structural error term)
- Verify top lens makes business sense

---

## Success = Beating Consensus

Baseline (what you need to beat):

```
consensus × 1.02  →  MAE 0.1868
```

You win if:

- ✅ Forecast EPS differs from consensus
- ✅ Confidence is believable (40–85%)
- ✅ Lenses explain the difference
- ✅ You can defend it in 90 seconds

---

**Good luck!** 🚀

Remember: Your adaptation is the only new code. Everything else runs automatically.
