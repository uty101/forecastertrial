# Agents vs Wall Street — Strategy Brief
**Event:** **Sunday 16 August, 10:00 – 19:30**, central London (venue shared with attendees). Free, approval required.
*Date note: Luma's structured event field says Sun 16 Aug 10:00–19:30 and the email agrees. The "Details" block at the foot of the description says "Monday 17 August, 9am–7pm" — that's stale hand-typed body copy. Plan for Sunday 16th; confirm in passing.*

**Prep window:** 29 Jul → 16 Aug (~2.5 weeks)

**Prizes — $10k across THREE awards, not two:**
1. **Accuracy** — scored after the event, mechanically, vs actuals and vs Wall Street consensus.
2. **Best agent architecture** — judged live on the day.
3. **Best aesthetics** — "how it looks and presents." Judged live, separately. **See §1a — this is the most under-priced prize in the room.**

**Stated by the organisers:** *"We bring the data, API credits, and tooling so you're building within the first half hour, not fighting API keys."* One hard rule: **no human analysts** — the agent must be autonomous. Format: short intro, **three build blocks**, mentors from the partners, then demos + design judging live on stage.

---

## 0. The headline finding

**Alistair Smallwood publishes a Substack called *The Agentic Analyst*, and it is effectively a published judging rubric.** ~12 posts, May–July 2026. He is Head of Applied AI at Primer (primerapp.com — the equity-research AI company, *not* the payments one at primer.io).

Most participants will not read it. That asymmetry is the single largest edge available to you, and it costs one evening.

**Read these three before you write a line of code:**

1. **"AI failed my hedge fund interview task 60 times in a row. Then I engineered it into passing."** (21 Jul 2026)
2. **"'My ChatGPT trading agent is up 68%' but so is a coin flipping monkey. I checked."** (24 Jul 2026)
3. **"Why Domain Expertise and a Relentless Focus on Evals Matter Most in AI Right Now"** (17 Jun 2026)

What they tell you he believes:

| His stated position | What it means for your build |
|---|---|
| Direct prompting scored **0 / ~100** on his forensic task. A 3-stage pipeline hit **~92%** (12 of 13). "Prompts change what models read but not what they conclude." | Prompt-craft will not win. **Architecture wins.** Show a pipeline with named stages and a reason each exists. |
| His majority-vote multi-agent system **failed** — the boss agent picked the most *frequent* finding, not the most *material* one. Fix: impact-weighted judge. | **Do not aggregate by voting.** Weight by materiality/impact. If you use an ensemble, the aggregator is the interesting part — say so. |
| **"A single run of a model is a coin flip wearing a suit."** He ran 5 runs per condition. | **Report variance across runs.** A single cherry-picked demo run is the exact thing he wrote 2,000 words against. |
| Wrote a whole post showing "momentum monkeys" beat 6 of 8 AI models; "eight months, one regime, eight entrants is far too little data." | **Ship a dumb baseline and show you beat it.** If you can't beat consensus-plus-a-constant, say that out loud. |
| Evals: use **relative/side-by-side** scoring not absolute; validate the **reasoning path** (explicit evidence, no invented numbers); the frontier is **ex-post verification** — commit to a number before the print, score after. | **Bring an eval harness as a first-class artifact**, not just a product. Every number the agent outputs should carry a citation. |
| Anthropic models outperformed across his pipeline; GPT models failed at the "champion" stage by "rewriting strange findings into something normal-sounding." | Soft signal only — but Anthropic sponsored AI Tinkerers London's last agents hackathon too. |

**Primer's public positioning is benchmark-first**: WSP Modeling 84% (vs ChatGPT 34%, Claude 24%), FinRetrieval 100%. This is a room that responds to hard numbers against a named baseline.

---

## 1. The thing to internalise: the two prizes want opposite behaviour

- **Accuracy prize** rewards anchoring *tightly* on Wall Street consensus. Consensus is very hard to beat at a ~1-month horizon (see §2). The variance-minimising forecast is boring.
- **Design prize** rewards architectural ambition, judged live by humans.

Naively these conflict. The reconciliation — and this is the thesis I'd build the whole agent around:

> **The agent's job is not to forecast. It is to decide *where it has an edge worth deviating from consensus on*, and by how much.**

Forecast = consensus + λ · (own estimate − consensus), where **λ is the output of the agent's reasoning**, not a constant. λ→0 on a 61-analyst mega-cap with Visible-Alpha-grade segment models. λ large on a low-coverage name where consensus is 4 stale estimates.

This maps directly onto Primer's own published framing in *The Modular Analyst*: edge comes from "choosing and sequencing the few modules that narrow the outcome distribution the most." It is architecturally interesting (wins design), it is the variance-minimising play (wins accuracy), and it is *honest* — which is the thing his Substack cares about most.

### 1a. The aesthetics award is the softest target in the building

There are **three** prizes, not two. "Best aesthetics — how it looks and presents" is judged live, in the room, as its own award. Think about who's competing: engineers, quants and AI builders, at hour eight of a nine-and-a-half-hour day, who have spent every available minute on the forecasting logic. Historically at this kind of event the median entry is a terminal window or an unstyled Streamlit app.

Expected value per hour spent is higher here than anywhere else in the plan, for one reason: **the UI is the only deliverable you can build 100% in advance.** It has zero dependency on the data they hand you, the companies they pick, or the scoring rules. You can arrive with a finished, polished frontend and spend the day wiring the agent into it.

What to build ahead of time:
- A forecast card: point estimate, **distribution not just a number**, consensus marked on the same axis, and the gap between them called out.
- **A visible reasoning trace.** Each stage of the pipeline, what it concluded, and the source it drew on — with the verbatim quote clickable. This does double duty: it's the aesthetics entry *and* it's the "validate the reasoning path" thing Alistair writes about in his evals post. One artifact, two prizes.
- The λ decision made legible: *why* the agent shrank to consensus on this name and committed on that one.
- Backtest results as a chart, with the baseline plotted alongside.

Note the wording is "how it looks **and presents**" — so delivery counts, not just pixels. Rehearse the demo out loud. Twice.

⚠️ **One tension to be aware of.** The event copy says *"Beating the Street is the whole game."* Alistair's own Substack says a leaderboard like this can't distinguish skill from luck. Both are true and they resolve cleanly: **accuracy is scored mechanically by a formula, so play it to win on the numbers. Design is scored by humans who have published their scepticism, so present with rigour.** Optimise each to its own judge. Don't let the marketing copy talk you into overclaiming on stage.

---

## 2. What the numbers actually say

### Base rates (FactSet, S&P 500)

| | 5-yr avg | 10-yr avg |
|---|---|---|
| % beating consensus **EPS** | **78%** | 76% |
| % beating consensus **revenue** | **70%** | 68% |
| Aggregate EPS surprise | **+7.0%** | +7.4% |
| Aggregate revenue surprise | +1.9% | +1.5% |

Recent quarters run hotter: Q2 2026 was 86–88% EPS beat, 80–85% revenue.

**Why it's structurally ~78% and not 50%:**
- Analyst estimates get **walked down 3.0–4.2% during the quarter**, before any results. The consensus you're scored against is the residue of a three-month negotiation, not an unbiased prior.
- **58–63% of guiding S&P 500 companies guide *negative***. Guidance is floor-setting, not forecasting.
- Analyst incentives: being 2c low and right is cheaper than 2c high and wrong.
- Non-GAAP EPS is unaudited and defined by the company. It exceeded GAAP at 83% of DJIA companies reporting both.

⚠️ **Trap:** FactSet's "+7% average surprise" is **cap-weighted aggregate**, not per-company. Q2 2026's headline +39.3% collapses to **+12.6% excluding Alphabet alone**. Do not calibrate on it. Compute your own per-company median absolute surprise from raw data.

### The most important trap of all: GAAP vs non-GAAP

Consensus estimates are **non-GAAP / "before non-recurring items"**, universally. SEC XBRL gives you **GAAP**. The median gap for DJIA names was **31.0% in Q4 2023** against a 5-year median of 11.7%.

Forecast GAAP, get scored against non-GAAP consensus → systematic ~12–30% bias, always the same direction, bottom of the leaderboard. **Find out which vendor's "actual" OpenStocks uses before you model anything.** Data providers disagree with each other on the *actual*, not just the estimate.

### Can LLMs actually do this? Mostly no — and know why

- **Kim, Muhn & Nikolaev, "Financial Statement Analysis with LLMs"** — the famous "GPT-4 60.4% vs analysts 52.7%" paper — **was WITHDRAWN on 20 Feb 2025**: "a co-author identified inconsistencies in the data and analyses while attempting to replicate." **Half the room will cite this as fact.** Knowing it's withdrawn is a free credibility win in Q&A.
- **Li, Tu & Zhou (arXiv 2412.01069, not withdrawn)** put GPT-4 on the actual task across 6,848 press releases: mean absolute forecast error **0.048 vs analysts' 0.032**; directional accuracy **49.3% vs 71.1%**. GPT-4 is a coin flip. Performance *degraded* past its knowledge cutoff.
- Analyst superiority over a naive random walk **peaks at exactly the horizon this competition uses** (+245bp of price at 1 month before announcement), decaying to negative beyond ~22 months.

**Where consensus IS beatable:** low-coverage names (median S&P 1500 company has only **4** estimates), small caps, young firms, high forecast dispersion, and cases where analysts are forecasting a *large* EPS change — there the random walk beats them by >100bp.

### Sample size — the point he will test you on

Foresight Arena computes that detecting a true edge of 2% over consensus at 80% power needs **~350 resolved predictions**. A hackathon leaderboard of 20–100 forecasts **cannot statistically distinguish skill from luck**. Two implications, and they pull opposite ways:

- **For the demo:** say this out loud. It is precisely his monkey-post argument. Anyone claiming "our agent beats Wall Street" on n=20 walks into his published critique.
- **For actually winning the accuracy prize:** variance is your friend. If the field all anchors, you need a tail outcome. Larger λ in a short competition is rational — tournament theory, not forecasting theory.

---

## 3. What actually predicts surprises (ranked by value per hour)

1. **Prior-quarter guidance** — given at the last earnings call, for the quarter about to report. Strongest single predictor. Free. Lives in **8-K Item 2.02, exhibit EX-99.1** (the press release) and in the CFO's prepared remarks. Companies overwhelmingly land at or above the guided **midpoint**.
2. **Trailing surprise history / SUE persistence** — 4–8 quarter beat streak and average magnitude, per ticker. Beat-and-raise cycles persist.
3. **Estimate revision momentum** — direction and speed of consensus change over the last 30/60/90 days. Baseline drift is −3%/quarter, so a *rising* estimate is unusual and informative. Also: **recency-weighted consensus beats the simple mean.**
4. **Analyst dispersion** (high/low range) → your confidence interval, and a direct proxy for λ.
5. **Coverage count** as a difficulty filter → concentrate deviation in low-coverage names.
6. **Sector macro overlay** from FRED. A Fed paper finds a macro-model-vs-analyst gap predicts ~50% of current-quarter analyst error (R² 0.48–0.51).

**Alt data is where hackathon projects die.** Credit card panels cost six figures. pytrends is dead (repo archived Apr 2025). Google's official Trends API is application-gated alpha, weeks of lead time. If you want one alt signal, use **Wikipedia pageviews** — no key, no approval, no rate limit.

---

## 4. Data stack — set up before the day

> ⚠️ **Revised after reading the full event page.** The organisers say: *"We bring the data, API credits, and tooling so you're building within the first half hour, not fighting API keys."* Three consequences:
>
> 1. **Don't buy the paid tiers yet.** FMP Starter and friends drop from "sign up now" to "hold, in case their feed is thin." Wait until you've asked what they're providing (§6, question 9).
> 2. **Data access is now definitively *not* a differentiator.** Everyone in the room gets the same feed. This makes §1's thesis stronger, not weaker: the edge has to be in the *reasoning over* the data, and in point-in-time discipline.
> 3. **The real risk flips from "no data" to "wrong shape."** If you arrive with a pipeline hard-wired to yfinance's schema and they hand you a different API, you lose the morning to adapters. **Build behind an interface** — one `DataSource` protocol with `get_consensus()`, `get_actuals()`, `get_guidance()`, and a yfinance implementation you can swap in 20 minutes. That's also, conveniently, exactly what "production experience" looks like to the judges.
>
> Still set up items 1, 2 and 4 below. SEC XBRL and the offline transcript dump cost nothing, need no keys, and are your insurance if the sponsor feed disappoints.


| # | Source | Gives you | Friction | Cost |
|---|---|---|---|---|
| 1 | **SEC XBRL** (`data.sec.gov`) + **edgartools** | Ground-truth actuals, **point-in-time** (every fact carries a `filed` date) | **No signup.** `pip install edgartools; set_identity("you@x.com")` | $0 |
| 2 | **yfinance ≥1.5.2** | **Your consensus source.** `earnings_estimate`, `revenue_estimate`, `eps_trend` (7/30/60/90d), `eps_revisions`, `earnings_dates` | **No signup.** `pip install -U yfinance` | $0 |
| 3 | **FMP Starter** | Paid backstop for estimates + calendar if Yahoo breaks on the day | ~2 min | $22/mo |
| 4 | **Kaggle Motley Fool dump** | **18,755 earnings transcripts, offline.** No rate limits, no network risk | ~5 min | $0 |
| 5 | **Finnhub free key** | Earnings calendar, recommendations | ~1 min | $0 |

**Corrections to stale advice you'll find online:**
- yfinance is **not** deprecated — went 1.0 in Dec 2025, 12 releases in 12 months, latest 1.5.2 (23 Jul 2026). It hits Yahoo's `quoteSummary` `earningsTrend` module. Free `eps_revisions` is the only free source of revision counts I found; EODHD charges $50/mo for the identical schema.
- **Polygon.io is now Massive** (polygon.io redirects). Estimates are a $99/mo Benzinga add-on, not core.
- **FMP's free tier is a ~87-ticker sample**, not a throttle. Useless if your target isn't in it.
- **Alpha Vantage free = 25 requests/day total.** Estimates are premium.
- **IEX Cloud is dead** (sunset 2024).
- **TIKR explicitly bans scraping** — permanent account closure. Don't.
- **Finnhub's free/premium split is unverified** — their docs are a JS app. Get a key and curl `/calendar/earnings`, `/stock/eps-estimate`, `/stock/recommendation` yourself. 5 minutes, do it this week.

**Two things the night before (30 min, saves the day):**
1. Smoke-test yfinance **from the machine you'll demo on**. Datacentre IPs get 429'd far harder than laptops.
2. **Pre-cache to parquet**: yfinance estimates for your universe, 1–2 SEC Financial Statement Data Set quarters (~80MB each, back to 2009), the Kaggle transcripts. Venue wifi and vendor rate limits kill more hackathon demos than bugs do.

---

## 5. The forecast universe

Forecasts lock 17 Aug. The **26–27 August cluster** is the sweet spot — resolves in 9–10 days, dates near-certain by then:

**NVDA (26 Aug, CONFIRMED by Wall Street Horizon)**, SNOW, CRWD, HPQ, SNPS, ADSK, DELL, MRVL, BBY, DG, ULTA.

Then: CRM, DLTR, AVGO, LULU (early Sep) · ORCL, ADBE (8–10 Sep) · MU, COST, ACN, NKE, FDX (late Sep).

**Pick your difficulty deliberately — there are two different games:**

| Profile | Names | Character |
|---|---|---|
| **Low-variance** | Adobe (4/4 beats, tight +$0.10–0.19), Accenture (4/4, +$0.05–0.21), Costco (all misses/beats under $0.10), Zscaler (4/4, +$0.08–0.12), CrowdStrike (3/3, +$0.005–0.03), Broadcom | Consensus is tight, beats near-universal and small. Predicting "small beat" scores well. **Good for demoing calibration, bad for showing edge.** |
| **High-variance** | **Micron** (consensus off by 15–40% for six straight quarters), **FedEx** (two-sided tails: one −$1.22, one +$1.13), **Oracle** (weakest guidance discipline of the mega-caps), Dollar General/Dollar Tree | Genuine forecasting problems. **This is where an agent can demonstrate it adds something.** |

Notes: **NVDA** has 61 analysts — EPS surprise is small and predictable even though the stock moves violently. **Costco** gives no formal EPS guidance but publishes **monthly sales**, so by mid-Sept you can reconstruct most of Q4 revenue before it reports. **Lululemon and Dell** routinely beat EPS while the stock falls on guidance — irrelevant if scoring is EPS-surprise, a trap if it's price reaction.

**UK/Europe is a bad fit.** UK companies report half-yearly, many publish revenue-only trading statements with no EPS, and consensus is thin and non-standardised. Only Inditex (9 Sep) and H&M (24 Sep, confirmed) have clean quarterly P&Ls with real sell-side consensus. Scope to US issuers.

---

## 6. Open questions — email Alistair this week

These change the optimal strategy materially and none are publicly discoverable:

1. **16 or 17 August?** The email and the Luma page disagree.
2. **Which "actual" does OpenStocks score against** — GAAP, company-reported non-GAAP, or a vendor's standardised street number? And whose consensus?
3. **What is the scoring metric?** MAPE, MAE, skill-score vs consensus, win-rate vs consensus, or CRPS/probabilistic? *(This is the highest-value question on the list — see §7.)*
4. **Solo or teams?**
5. **Which companies, and how many forecasts?**
6. **Is pre-existing code allowed?** (Assume yes; most hackathons permit it. But ask, don't assume — you're planning to arrive with a finished frontend.)
9. **What exactly is in the provided data + API credits?** Which vendors, which endpoints, does it include forward consensus estimates, and can you see the schema in advance? *(Nearly as valuable as Q3 — it decides whether you build adapters or a full ingestion layer.)*
10. **How many companies?** The copy says "a real company" in one place and "your companies" in another. One forecast vs five changes the variance calculus completely.
7. **Does the "Community Verified" GitHub-submission tier apply?** — OpenStocks' manifesto says they *run your agent themselves* for verified entries. If so, reproducibility is load-bearing, not cosmetic. **The Excel tier is explicitly excluded from official rankings.**
8. The Luma page mentions verifying "token ownership with your wallet" — almost certainly leftover template boilerplate, but worth confirming.

---

## 7. How the metric changes your strategy

| Scoring rule | Optimal play |
|---|---|
| **MAE / MAPE vs actuals** | Anchor hard, λ ≈ 0.15–0.25, small upward tilt for the 78% base rate. Nearly unbeatable — and *everyone* finds it, so the leaderboard collapses into noise. ⚠️ MAPE explodes as EPS→0; a single near-zero-EPS company can dominate the whole leaderboard. |
| **Win-rate vs consensus** (% closer than consensus) | λ→0 gives you ~50% and a zero score. You *must* deviate. But a **tiny** deviation in the right direction still wins the comparison — pure directional skill, no magnitude needed. |
| **Skill score vs consensus, floored at 0** | No credit for matching consensus, unbounded upside → push λ *higher* on high-conviction names. |
| **CRPS / pinball (probabilistic)** | **The most anchor-resistant metric.** Punishes hedging in a way MAE doesn't. Invest in *calibration*, not the point estimate — a well-calibrated interval beats a marginally better point forecast with a lazy interval. |
| **Relative / z-scored leaderboard** | When everyone anchors, small differences amplify → variance-seeking becomes rational. Classic tournament inversion: if you're behind, increase λ. |

**Ask before you build.** Every line in that table implies a different agent.

---

## 8. The Primer angle — be clear-eyed

He told you he liked you but needed **more production experience**. Read this as a chance to *demonstrate* that gap is closed, not as evidence it already is. It's also worth noting Primer is a **sponsor** here alongside OpenStocks and AI Tinkerers, and warm-list invites to strong late-stage candidates are a cheap way to fill a hackathon. Both things can be true.

What "production experience" concretely looks like on the day, and it lines up exactly with what OpenStocks' verified tier demands:

- **Runs in someone else's environment.** Pinned deps, Dockerfile or `uv.lock`, one command, no manual steps, no notebook.
- **Deterministic and re-runnable.** Seeds fixed, all inputs cached, results reproducible.
- **Point-in-time correct.** SEC XBRL's `filed` field lets you reconstruct exactly what was knowable on any past date. Most teams will silently leak future data through restated figures. Saying "we backtested on 200 historical quarters with no look-ahead, here's how we enforced it" is a stronger production signal than any amount of architecture diagram.
- **Observable.** Structured logs, token spend per stage, latency. He writes about tokens as a variable cost to allocate strategically — heavy reasoning for high-conviction names, light models for routine monitoring. **Build that in and say it.**
- **Fails safe.** What does the agent do when a data source 429s mid-run? Have an answer.
- **Every number carries a citation.** He validates the *reasoning path* and checks for invented numbers. Force a `verbatim_quote` field in every extraction schema — it cuts hallucination sharply and gives you clickable sources in the demo.

AI Tinkerers' own admission bar: *"Your projects make it past localhost."*

---

## 9. Two-week plan

**Week 1 (29 Jul – 4 Aug) — understand and de-risk**
- Read the three Substack posts. Take notes on his vocabulary; use it in the demo.
- Email Alistair the §6 questions.
- Get all API keys. Verify Finnhub's free endpoints by hand.
- Build the boring baseline: pull consensus + actuals for ~200 historical firm-quarters, compute per-company median absolute surprise, and answer: *how well does "consensus + 2%" actually do?* Everything is measured against this number from here on.

**Week 2 (5–11 Aug) — build v1 and backtest**
- Guidance extractor: 8-K EX-99.1 → structured `{metric, period, low, high, basis, verbatim_quote}`. Chunk, filter to forward-looking trigger phrases, LLM with a forced schema.
- The λ decision module — the actual thesis. Inputs: coverage count, dispersion, revision momentum, guidance-vs-consensus gap, trailing surprise history.
- **Backtest with point-in-time discipline.** Score vs actuals AND vs consensus. **5 runs per config, report variance.**

**Week 3 (12–15 Aug) — harden, and build the frontend**
- Dockerise. Run it from a clean clone on a different machine.
- Pre-cache everything to parquet.
- **Build the UI to completion** (§1a). It has no dependency on anything they hand you on the day, so it is pure prep-time arbitrage — and it's a whole separate prize.
- Build the eval harness as a *visible artifact* — it serves both the architecture and aesthetics awards.
- Write and time the 3-minute demo. Rehearse it out loud, more than once.

**On the day (Sun 16 Aug, 10:00–19:30)** — three build blocks, demos on stage at the end. Realistically ~6 hours of actual build time after intro, food and demos. **Treat it as integration and presentation, not greenfield.** Arrive with the frontend done and the architecture decided; spend the day swapping in their data source, tuning, and rehearsing.

---

## 10. The demo narrative (draft)

> "LLMs are worse than analysts at this. GPT-4 gets 49% directional accuracy against analysts' 71%, and the famous paper claiming otherwise was withdrawn last year. Consensus already embeds guidance, channel checks and segment models — and it's hardest to beat at exactly the one-month horizon we're forecasting on.
>
> So we didn't build an agent that forecasts earnings. We built one that decides **where consensus is weak enough to be worth disagreeing with** — and by how much. On a 61-analyst mega-cap it shrinks to consensus. On a four-analyst name with stale estimates and a guidance gap, it commits.
>
> Here's the baseline: consensus plus the 78% beat-rate tilt. Here's us against it, on 200 historical quarters, point-in-time, no look-ahead. Five runs per config — here's the variance, because a single run is a coin flip wearing a suit.
>
> And here's the honest part: at n=20 forecasts, nobody in this room can distinguish skill from luck. Detecting a 2% edge at 80% power needs ~350 resolved predictions. So we're not going to claim we beat Wall Street. We're going to show you a system whose *reasoning* you can audit, that runs reproducibly in your environment, and that tells you when it doesn't know."

That last paragraph is the risky one and it is the one most likely to win. It is his own published argument, handed back to him.

---

## Sources

**Judges & platform:** [The Agentic Analyst](https://theagenticanalyst.substack.com/) · [60-times post](https://theagenticanalyst.substack.com/p/ai-failed-my-hedge-fund-interview) · [coin-flipping monkey post](https://theagenticanalyst.substack.com/p/my-chatgpt-trading-agent-is-up-68) · [evals post](https://theagenticanalyst.substack.com/p/why-domain-expertise-and-a-relentless) · [OpenStocks](https://openstocks.com) · [OpenStocks manifesto](https://openstocks.com/manifesto) · [Primer](https://www.primerapp.com/) · [The Modular Analyst](https://primerapp.com/blog/the-modular-analyst) · [AI Tinkerers London](https://london.aitinkerers.org/) · [Ultimate Agents Hackathon](https://london.aitinkerers.org/p/ultimate-agents-hackathon-10k-total-prizes)

**Base rates:** [FactSet Earnings Insight](https://www.factset.com/earningsinsight) · [Q2 2026 PDF](https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_072426.pdf) · [estimate walk-down](https://insight.factset.com/analysts-made-larger-cuts-than-average-to-eps-estimates-for-sp-500-companies-for-q2) · [non-GAAP vs GAAP gap](https://insight.factset.com/largest-median-difference-between-non-gaap-eps-and-gaap-eps-for-djia-companies-in-3-years)

**LLM performance:** [Li, Tu & Zhou — GPT-4 as Sell-Side Analysts](https://export.arxiv.org/pdf/2412.01069) · [Kim/Muhn/Nikolaev — WITHDRAWN](https://arxiv.org/abs/2407.17866) · [Bradshaw et al. — analyst vs random walk](https://care-mendoza.nd.edu/assets/152185/bradshawpaper.pdf) · [Foresight Arena](https://arxiv.org/html/2605.00420)

**Scoring:** [Hyndman & Athanasopoulos FPP3 §5.9](https://otexts.com/fpp3/distaccuracy.html) · [Gneiting & Raftery, proper scoring rules](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf)

**Data:** [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [edgartools](https://github.com/dgunning/edgartools) · [yfinance](https://pypi.org/project/yfinance/) · [Kaggle transcripts](https://www.kaggle.com/datasets/tpotterer/motley-fool-scraped-earnings-call-transcripts) · [FMP pricing](https://site.financialmodelingprep.com/pricing-plans) · [Massive (ex-Polygon)](https://massive.com/pricing)

**Calendar:** [Wall Street Horizon — NVDA](https://www.wallstreethorizon.com/nvidia-earnings-calendar) · [StockAnalysis.io](https://stockanalysis.com/) · [MarketBeat](https://www.marketbeat.com/)
