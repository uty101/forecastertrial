"use client";

import { useEffect, useState } from "react";

import {
  Callout,
  Dimension,
  Disclaimer,
  Empty,
  Lede,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import { eps, pct, signedPct, useResult } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 05 — risk.
 *
 * A trading system's risk sheet is about capital: position size, stop losses,
 * drawdown, exposure. This system does not take positions, so copying that
 * vocabulary would produce a screen full of numbers that mean nothing.
 *
 * The translation is exact, though, because the scarce resource here is the same
 * shape as capital — it is DEVIATION. Every basis point of disagreement with
 * sixty-one analysts is risk taken, and the honest analogues are:
 *
 *   position size    → λ. How much deviation this name earns.
 *   stop loss        → the comparability flag. Historical priors stop applying,
 *                      λ collapses, and the system gets least confident exactly
 *                      where it would otherwise be most.
 *   daily loss limit → the cost ceiling. A loop burning credits at 14:00 ends
 *                      the day; this raises before the call, not after.
 *   portfolio risk   → deviation budget across N companies. Concentrate it where
 *                      consensus is weakest, not evenly.
 *   capital          → tokens, allocated by leverage rather than spread flat.
 *
 * Every figure on this sheet comes from results.json. Nothing is modelled here.
 */

function Shield({ protected: ok }: { protected: boolean }) {
  return (
    <svg viewBox="0 0 120 140" className="h-auto w-full max-w-[150px]" aria-hidden>
      <path
        d="M60 6 L110 26 V72 C110 104 88 124 60 134 C32 124 10 104 10 72 V26 Z"
        fill="none"
        stroke={ok ? "var(--color-structure)" : "var(--color-accent)"}
        strokeWidth="2"
      />
      <path
        d="M60 6 L110 26 V72 C110 104 88 124 60 134 Z"
        fill={ok ? "var(--color-structure)" : "var(--color-accent)"}
        opacity="0.1"
      />
      <path
        d="M60 6 V134"
        stroke={ok ? "var(--color-structure)" : "var(--color-accent)"}
        strokeWidth="0.8"
        opacity="0.5"
      />
      <path
        d="M10 60 H110"
        stroke={ok ? "var(--color-structure)" : "var(--color-accent)"}
        strokeWidth="0.8"
        opacity="0.5"
      />
      {[24, 36, 48].map((y) => (
        <path
          key={y}
          d={`M${60 + (y - 20) * 0.5} ${y} H104`}
          stroke={ok ? "var(--color-structure)" : "var(--color-accent)"}
          strokeWidth="0.6"
          opacity="0.28"
        />
      ))}
    </svg>
  );
}

interface Allocation {
  ticker: string;
  lambda: number;
  n_analysts?: number | null;
  rationale?: string;
}

export default function RiskScreen() {
  const result = useResult();
  const [portfolio, setPortfolio] = useState<Allocation[] | null>(null);

  // A cross-company deviation budget only exists when more than one company has
  // been forecast. Absent, the sheet says so rather than inventing a portfolio.
  useEffect(() => {
    void fetch("/portfolio.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setPortfolio(data as Allocation[]))
      .catch(() => setPortfolio(null));
  }, []);

  if (!result) {
    return (
      <Sheet system="deviation + capital control" sheet={sheetOf("/risk/")}>
        <Empty
          title="No run to assess"
          detail="This sheet reads λ, the comparability flag and the cost ledger from out/results.json."
          command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
        />
      </Sheet>
    );
  }

  const f = result.forecast;
  const lam = f.lambda_decision;
  const comparability = (result.trace?.comparability ?? {}) as {
    flag?: string | null;
    note?: string;
  };
  const cost = (result.trace?.cost ?? {}) as {
    total_cost_usd?: number;
    ceiling_usd?: number;
    total_calls?: number;
  };
  const spent = cost.total_cost_usd ?? f.total_cost_usd ?? 0;
  const ceiling = cost.ceiling_usd ?? 25;
  const utilisation = ceiling ? spent / ceiling : 0;
  const stopped = Boolean(comparability.flag);
  const droppedCount = Object.keys(f.dropped_lenses ?? {}).length;

  const CONTROLS = [
    {
      n: 1,
      title: "Position size",
      body:
        "λ is how much deviation this name earns, fitted on backtest and conditioned on regime — coverage, dispersion, staleness, internal disagreement.",
      value: (lam?.value ?? 0).toFixed(3),
      unit: "λ",
    },
    {
      n: 2,
      title: "Stop loss",
      body:
        "The comparability check. M&A mid-quarter, an accounting change, a 53rd week — historical priors stop applying, so λ collapses before the forecast is made, not after it is wrong.",
      value: stopped ? "TRIGGERED" : "armed",
      unit: "",
    },
    {
      n: 3,
      title: "Daily limit",
      body:
        "A hard cost ceiling with a kill switch, checked before each call rather than after. An overspend you detect afterwards is an overspend you already paid for.",
      value: `${pct(utilisation, 0)}`,
      unit: "of ceiling",
    },
    {
      n: 4,
      title: "Exposure",
      body:
        "Internal disagreement across the surviving lenses. When our own evidence is inconsistent, λ is damped regardless of what the meta-layer says about consensus.",
      value: pct(lam?.internal_disagreement ?? 0, 1),
      unit: "CV",
    },
    {
      n: 5,
      title: "Allocation",
      body:
        "Deviation concentrated where consensus is weakest rather than spread evenly, and tokens allocated by leverage: cheap for extraction, one expensive call for the judge.",
      value: portfolio ? String(portfolio.length) : "1",
      unit: portfolio ? "names" : "name",
    },
  ];

  return (
    <Sheet
      system="deviation + capital control"
      readout={[`${f.ticker} ${f.period}`, `LOCKED ${f.as_of}`]}
      sheet={sheetOf("/risk/")}
      footer={
        <SheetFooter
          cells={[
            ["λ", (lam?.value ?? 0).toFixed(3)],
            ["stop", stopped ? `triggered — ${comparability.flag}` : "armed, not triggered"],
            ["spend", `$${spent.toFixed(4)} of $${ceiling.toFixed(2)}`],
            ["scarce resource", "deviation, not capital"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <SyntheticBanner trace={result.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Lede>
            This system holds no positions, so the scarce resource is not capital — it is deviation. Every basis point of disagreement with sixty-one analysts is risk taken, and it is budgeted the same way.
          </Lede>

          <StatusPanel
            title="risk status"
            state={stopped ? "constrained" : "protected"}
            detail={stopped ? "comparability stop triggered" : "all controls armed"}
            fraction={stopped ? 0.35 : 1}
            tone={stopped ? "running" : "done"}
            rows={[
              ["λ (position size)", (lam?.value ?? 0).toFixed(3)],
              ["ceiling used", pct(utilisation, 1)],
              ["lenses dropped", droppedCount],
              ["disagreement", pct(lam?.internal_disagreement ?? 0, 1)],
            ]}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="space-y-2.5">
            {CONTROLS.map((control) => (
              <Panel key={control.n} label={control.title} index={control.n}>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <p className="max-w-2xl flex-1 text-[12.5px] leading-relaxed text-ink-2">
                    {control.body}
                  </p>
                  <div className="text-right">
                    <div
                      className={`num display text-[24px] leading-none ${
                        control.value === "TRIGGERED"
                          ? "text-accent"
                          : "text-ink"
                      }`}
                    >
                      {control.value}
                    </div>
                    {control.unit && (
                      <div className="label mt-1">{control.unit}</div>
                    )}
                  </div>
                </div>
              </Panel>
            ))}
          </div>

          <div className="space-y-3">
            <Panel label="capital defended">
              <div className="flex flex-col items-center gap-2">
                <Shield protected={!stopped} />
                <Pill tone={stopped ? "warn" : "good"}>
                  {stopped ? "constrained" : "protected"}
                </Pill>
              </div>
            </Panel>
            <Callout label="deviation rules" tone="accent">
              <ul className="list-inside list-disc space-y-1">
                <li>Never deviate further than the evidence supports.</li>
                <li>Shrink when our own lenses disagree.</li>
                <li>Protect the forecast, not the view.</li>
                <li>Being consistently close beats being occasionally spectacular.</li>
              </ul>
            </Callout>
          </div>
        </div>

        <Panel label="risk overview" hint="every figure from this run, none modelled here">
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat
              label="max deviation"
              value={signedPct(f.surprise_vs_consensus)}
              sub="taken vs the Street"
              accent
            />
            <Stat
              label="λ used"
              value={(lam?.value ?? 0).toFixed(3)}
              sub={lam?.preset ?? ""}
            />
            <Stat
              label="disagreement"
              value={pct(lam?.internal_disagreement ?? 0, 1)}
              sub="across surviving lenses"
            />
            <Stat
              label="evidence depth"
              value={String(
                (result.trace?.evidence as { claims?: number })?.claims ?? "—",
              )}
              sub="cited claims available"
            />
            <Stat
              label="ceiling used"
              value={pct(utilisation, 1)}
              sub={`$${spent.toFixed(4)} of $${ceiling.toFixed(2)}`}
            />
          </div>
          <Dimension
            className="mt-4"
            value={`${eps(f.consensus?.eps)} → ${eps(f.eps_non_gaap)}`}
            label="deviation taken"
          />
        </Panel>

        <div className="grid gap-3 lg:grid-cols-2">
          <Panel
            label="stop loss detail"
            hint="the check that makes the system least confident where it would otherwise be most"
          >
            {stopped ? (
              <>
                <Pill tone="warn">triggered — {comparability.flag}</Pill>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">
                  {comparability.note}
                </p>
                <p className="dashed mt-3 pt-3 text-[12.5px] leading-relaxed">
                  λ is multiplied by 0.25. The quarter is not comparable to this
                  company&rsquo;s own history, so the guided-range landing
                  distribution and the surprise prior do not apply.
                </p>
              </>
            ) : (
              <>
                <Pill tone="good">armed, not triggered</Pill>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">
                  {comparability.note ?? "no comparability note recorded"}
                </p>
                <p className="dashed mt-3 pt-3 text-[11.5px] text-ink-3">
                  A clean quarter is the common case. A failed check returns
                  &ldquo;comparable&rdquo; rather than collapsing λ, because a
                  broken check that silently shrank every forecast would be a
                  one-directional accuracy loss nobody would notice.
                </p>
              </>
            )}
          </Panel>

          <Panel
            label="deviation budget across names"
            hint="concentrate where consensus is weakest, not evenly"
          >
            {!portfolio ? (
              <p className="text-[12.5px] leading-relaxed text-ink-2">
                Only one company forecast in this run, so there is no
                cross-company budget to allocate. With several, deviation is
                concentrated on the names where consensus is structurally weakest
                — thin coverage, wide dispersion, stale estimates — and set to
                zero on the well-covered ones. This panel populates from
                <code className="mx-1 font-mono text-[11.5px]">portfolio.json</code>
                when a multi-company run writes one.
              </p>
            ) : (
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="label border-b border-rule">
                    <th className="pb-1.5 text-left">name</th>
                    <th className="pb-1.5 text-right">analysts</th>
                    <th className="pb-1.5 text-right">λ</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.map((row) => (
                    <tr
                      key={row.ticker}
                      className="border-b border-rule-2 last:border-0"
                    >
                      <td className="py-1.5 font-semibold">{row.ticker}</td>
                      <td className="num py-1.5 text-right">
                        {row.n_analysts ?? "—"}
                      </td>
                      <td className="num py-1.5 text-right font-semibold">
                        {row.lambda.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        <Disclaimer>
          <strong className="text-ink">
            This sheet is about forecast risk, not capital at risk.
          </strong>{" "}
          The system produces an EPS estimate and a distribution; it takes no
          positions, holds no capital, and none of these figures are a return, a
          drawdown or a Sharpe ratio. The vocabulary is borrowed because the
          budgeting problem has the same shape — the scarce resource is how far
          to disagree.
        </Disclaimer>
      </div>
    </Sheet>
  );
}
