# forecaster

An earnings-forecasting agent that knows when to disagree with Wall Street — and, more often, when not to.

Built for **Agents vs Wall Street**, London, 16 August 2026.

---

## The thesis

Consensus is not a forecast. It is analysts' good analysis with a thumb on the scale:

- estimates are **walked down 3.0–4.2%** during the quarter, before any results
- **58–63%** of guiding companies guide *negative*
- **78%** of S&P 500 companies then beat the bar that gets set; aggregate surprise **+7.0%**

None of that is analytical error — analysts beat a naive random walk by 245bp of price at exactly this horizon. It's incentive: management access, career risk from a visible miss, herding, reluctance to publish an outlier.

So this system reproduces the analysis and strips the incentives, then adds the one question no individual analyst can ask, because they *are* the consensus:

> **Where is consensus structurally weak, and how far is it worth deviating?**

Everything upstream of `f_lambda` produces an estimate. λ decides how much to trust it against sixty-one analysts with segment-level models. That separation is the point.

---

## Quick start

```bash
make setup
cp .env.example .env          # ANTHROPIC_API_KEY, SEC_IDENTITY
make test
make run TICKER=NVDA ASOF=2026-08-16
make ui                       # http://localhost:3000
```

**Determinism:**

```bash
make verify    # fixed quarter, from cache, seed 0, diffed against a golden file
```

Same command runs in CI on every commit. It demonstrates reproducibility, point-in-time correctness and test discipline at once — which matters because OpenStocks' verified tier means *they* execute your agent, in their environment.

---

## Architecture

```
A  ACQUIRE     numbers · filings · industry · macro      parallel, hard budgets
B  STRUCTURE   3-statement model · evidence store        deterministic
C  ANALYSE     7 lenses, blind to each other             parallel, shared cached prefix
V1 RECONCILE   arithmetic + citation verification        fail → drop the lens
D  CHALLENGE   argue each case, then argue against it    ×7 parallel
E  JUDGE       impact-weighted, never vote-weighted      one expensive call → a range
V2 COMPARABLE  M&A · accounting change · 53rd week       fires → λ collapses
F  POSITION    λ vs consensus, fitted and conditioned
V3 CALIBRATE   bootstrap our own backtest residuals
G  OUTPUT      forecast + model + trace
```

Three choices carry the design:

**Lenses are blind to each other.** Diversity is the point. Let them see each other's work and they converge — and converging is how you accidentally rebuild consensus, which scores zero.

**The judge weighs by materiality, never by vote count.** Six lenses agreeing on a weak signal loses to one carrying the company's own guidance and a verbatim quote.

**Champion development runs before any comparison.** Each lens's case is argued properly *and argued against* before anything is ranked. Comparing raw findings and taking the plurality is a known failure mode.

---

## No number without a source

`Claim` cannot be constructed without a `Source` and a `verbatim_quote`, and `v1_reconcile.verify_citations` string-matches every quote against its document. Model cells refuse an input with no claim.

So *"we don't invent figures"* is a validation error, not a code-review comment — and the UI gets clickable citations for free. Failed citations are shown in red, not hidden.

---

## Point-in-time

Every `DataSource` method takes `as_of` and must not return anything filed after it. `assert_point_in_time` raises loudly, and `tests/test_point_in_time.py` deliberately tries to leak — including the subtle case, a *restatement* of a historical period published after the lock date.

A backtest that cannot fail this way is not enforcing anything, and its numbers mean nothing.

---

## Scoring-rule agnostic

The metric isn't known until the morning of the event. The judge outputs a **distribution**, which is a strict superset of a point forecast, and three λ presets are backtested during prep:

| Preset | For | Behaviour |
|---|---|---|
| `shrink` | MAE · MAPE · MSE | λ = fitted β; emit median (mean under squared error) |
| `barbell` | skill score vs consensus, rank leaderboards | λ high on top-conviction names, 0 elsewhere |
| `calibrated` | CRPS · pinball | full quantiles; optimise calibration, don't hedge with width |

Plus `--tiny-tilt` for a pure win-rate metric, where matching consensus scores exactly zero and direction matters but magnitude doesn't.

Both `eps_gaap` and `eps_non_gaap` are always carried, with the bridge between them as an explicit cited object — consensus is non-GAAP, XBRL is GAAP, and the median DJIA gap was 31% in one recent quarter.

---

## Layout

```
src/forecaster/
  schemas.py            the contract — change this first, UI types generate from it
  data/protocol.py      DataSource; every method takes as_of and may return None
  model/graph.py        dependency-graph evaluator; cells carry provenance
  pipeline/
    c_lenses/mechanical.py   FX · share count · net interest · calendar — no LLM
    v1_reconcile.py          arithmetic + citations
    f_lambda.py              the thesis
  llm/prompts/          versioned YAML, never inline
tests/
  test_point_in_time.py  deliberately tries to leak
  test_reconciler.py     each test is a real failure mode
ui/                     Next.js, static export, reads out/*.json
```

**No API between the two processes.** The pipeline appends to `out/events.ndjson`; the UI polls it. Nothing to crash mid-demo — and replay mode comes free, since a recorded run replays through the identical code path.

---

## Status

Scaffold. Working: schemas, data protocol, model graph, mechanical lens, reconciler, λ, event log, tests. Stubbed: acquisition, LLM lenses, champion, judge, calibration, UI.
