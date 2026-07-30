"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Callout,
  Disclaimer,
  Display,
  Empty,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
} from "@/components/blueprint";
import { pct, tooltip } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 06 — the method. What the architecture prize is actually judged on, and
 * the sheet most teams do not build.
 *
 * Four things, in order of how much they matter to a sceptical reader:
 *
 *   1. The baseline on every chart. `consensus × (1 + shrunk tilt)` is not a
 *      strawman — 78% of S&P 500 companies beat consensus — and if we cannot
 *      beat it, λ should have been zero and we say so.
 *   2. The reliability diagram. Do our 80% intervals cover 80%? They won't at
 *      first, and showing that is worth more than hiding it.
 *   3. Leave-one-lens-out ablation. If two of seven earn nothing, drop them and
 *      say so — an honest negative result lands better than an unfalsifiable win.
 *   4. n and a confidence interval. Detecting a 2% edge at 80% power needs ~350
 *      resolved forecasts. Below that, ranking is variance. Say it first.
 *
 * The cumulative skill curve is this system's equity curve — the honest
 * translation. It plots error saved against consensus as cases resolve, so the
 * line going up means the pipeline was closer than the Street more often than
 * not. It is NOT a return, and the disclaimer says so.
 */

interface EvalPayload {
  synthetic?: boolean;
  note?: string;
  backtest?: {
    n?: number;
    mae?: number;
    median_ae?: number;
    mae_consensus?: number;
    mae_baseline?: number;
    skill_vs_consensus?: number;
    beat_baseline_rate?: number;
    win_rate_vs_consensus?: number;
    win_rate_ci95?: [number, number];
    mean_run_spread?: number;
    information_ratio?: number;
    underpowered?: boolean;
    power_note?: string;
  };
  skill_curve?: Array<{ i: number; cumulative_skill: number; baseline: number }>;
  calibration?: Array<{ nominal: number; empirical: number; n: number }>;
  ablation?: Record<string, number>;
  lambda?: {
    buckets?: Record<
      string,
      { beta: number; n: number; r_squared: number; is_measured: boolean }
    >;
  };
}

export default function EvalScreen() {
  const [data, setData] = useState<EvalPayload | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    void fetch("/eval.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("no eval.json"))))
      .then((payload) => setData(payload as EvalPayload))
      .catch(() => setMissing(true));
  }, []);

  if (missing || !data) {
    return (
      <Sheet system="backtest + calibration" sheet={sheetOf("/eval/")}>
        <div className="space-y-5">
          <Display kicker="Nothing downstream means anything until the baseline number exists. Build the firm-quarter cases, score consensus × 1.02 against them, and everything after that is measured rather than asserted.">
            Every claim
            <br />
            <Green>gets backtested.</Green>
          </Display>
          <Empty
            title="No eval yet — and this is the gate"
            detail="The case set has not been built. Until consensus × 1.02 has a score, a pipeline result has nothing to be compared to and cannot be interpreted."
            command="uv run forecast cases  →  uv run forecast backtest"
          />
          <Panel label="what goes here" hint="the four things a sceptical reader asks for">
            <ol className="list-inside list-decimal space-y-2 text-[12.5px] leading-relaxed text-ink-2">
              <li>
                <strong className="text-ink">
                  Backtest against the baseline
                </strong>{" "}
                — not against nothing.{" "}
                <code className="font-mono text-[11.5px]">
                  consensus × (1 + shrunk tilt)
                </code>{" "}
                is a genuinely strong forecaster and every competent competitor
                will find it.
              </li>
              <li>
                <strong className="text-ink">A reliability diagram</strong>{" "}
                — do the 80% intervals cover 80%? They will not at first. Fixing
                that is cheap and visual; hiding it is not honest.
              </li>
              <li>
                <strong className="text-ink">
                  Leave-one-lens-out ablation
                </strong>{" "}
                — non-optional. If two of seven do not earn their tokens, drop
                them and say so on stage.
              </li>
              <li>
                <strong className="text-ink">
                  n, with a confidence interval
                </strong>{" "}
                — detecting a 2% edge at 80% power needs about 350 resolved
                forecasts. Say it before someone else does.
              </li>
            </ol>
          </Panel>
        </div>
      </Sheet>
    );
  }

  const bt = data.backtest ?? {};
  const maeChart = [
    { name: "Consensus", value: bt.mae_consensus ?? 0, kind: "street" },
    { name: "Baseline", value: bt.mae_baseline ?? 0, kind: "street" },
    { name: "Ours", value: bt.mae ?? 0, kind: "ours" },
  ];
  const ablation = Object.entries(data.ablation ?? {})
    .map(([lens, delta]) => ({ lens, delta }))
    .sort((a, b) => b.delta - a.delta);
  const spansHalf =
    bt.win_rate_ci95 && bt.win_rate_ci95[0] < 0.5 && bt.win_rate_ci95[1] > 0.5;

  return (
    <Sheet
      system="backtest + calibration"
      readout={[`n = ${bt.n ?? 0} FIRM-QUARTERS`, bt.underpowered ? "UNDERPOWERED" : "POWERED"]}
      sheet={sheetOf("/eval/")}
      footer={
        <SheetFooter
          cells={[
            ["cases", `${bt.n ?? 0} resolved`],
            ["skill vs consensus", pct(bt.skill_vs_consensus, 2)],
            ["runs per config", "5 — a single run is a coin flip in a suit"],
            ["power", bt.underpowered ? "below 350, variance-dominated" : "adequate"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        {data.synthetic && (
          <div className="border-l-2 border-accent bg-accent-soft px-4 py-2.5">
            <div className="label text-accent">⚠ synthetic fixture</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
              <strong className="text-ink">
                These are not measured results.
              </strong>{" "}
              {data.note}
            </p>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Display kicker="Before claiming an edge. The baseline is on every chart, the intervals are checked against their own coverage, and every lens has to earn its tokens or be dropped.">
            Every claim
            <br />
            <Green>gets backtested.</Green>
          </Display>

          <StatusPanel
            title="backtest status"
            state={bt.underpowered ? "underpowered" : "complete"}
            detail={`${bt.n ?? 0} resolved firm-quarters`}
            fraction={Math.min(1, (bt.n ?? 0) / 350)}
            tone={bt.underpowered ? "running" : "done"}
            rows={[
              ["MAE, ours", (bt.mae ?? 0).toFixed(4)],
              ["MAE, baseline", (bt.mae_baseline ?? 0).toFixed(4)],
              ["skill", pct(bt.skill_vs_consensus, 2)],
              ["run spread", (bt.mean_run_spread ?? 0).toFixed(4)],
            ]}
          />
        </div>

        {bt.power_note && (
          <Callout label="statistical power" tone={bt.underpowered ? "accent" : "structure"}>
            {bt.power_note}
          </Callout>
        )}

        {/* The equity-curve equivalent, named honestly. */}
        <Panel
          label="cumulative skill vs consensus"
          hint="this system's equity curve — error saved as cases resolve, not a return"
          index={1}
        >
          {!data.skill_curve?.length ? (
            <p className="text-[12.5px] text-ink-2">
              Not computed yet. Populated by the backtest once the case set exists.
            </p>
          ) : (
            <>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart
                    data={data.skill_curve}
                    margin={{ top: 10, right: 14, bottom: 4, left: 4 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="var(--color-rule-2)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="i"
                      tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                      axisLine={{ stroke: "var(--color-rule)" }}
                      tickLine={false}
                      label={{
                        value: "firm-quarters resolved",
                        position: "insideBottom",
                        offset: -2,
                        fontSize: 10,
                        fill: "var(--color-ink-3)",
                      }}
                    />
                    <YAxis
                      tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                      axisLine={false}
                      tickLine={false}
                      width={58}
                      tickFormatter={(v: number) => v.toFixed(2)}
                    />
                    <Tooltip
                      formatter={tooltip((v) => v.toFixed(4))}
                      contentStyle={{
                        fontSize: 11.5,
                        border: "1px solid var(--color-rule)",
                        background: "var(--color-sheet)",
                        borderRadius: 0,
                      }}
                    />
                    <ReferenceLine y={0} stroke="var(--color-ink-3)" />
                    {/* The baseline is on the chart. Always. */}
                    <Area
                      type="monotone"
                      dataKey="baseline"
                      stroke="var(--color-ink-3)"
                      strokeDasharray="5 3"
                      fill="none"
                      strokeWidth={1.2}
                    />
                    <Area
                      type="monotone"
                      dataKey="cumulative_skill"
                      stroke="var(--color-structure)"
                      fill="var(--color-structure)"
                      fillOpacity={0.14}
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <p className="dashed mt-2 pt-2 text-[11.5px] text-ink-3">
                Solid green: cumulative absolute error saved versus consensus.
                Dashed: the same for the baseline. Up means closer than the Street
                more often than not — it is not money, and there is no compounding.
              </p>
            </>
          )}
        </Panel>

        <div className="grid gap-3 lg:grid-cols-2">
          <Panel
            label="mean absolute error"
            hint="the baseline is on the chart — it is not a strawman"
            index={2}
          >
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={maeChart}
                  margin={{ top: 10, right: 14, bottom: 4, left: 4 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--color-rule-2)"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    axisLine={{ stroke: "var(--color-rule)" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    axisLine={false}
                    tickLine={false}
                    width={56}
                  />
                  <Tooltip
                    formatter={tooltip((v) => v.toFixed(4))}
                    contentStyle={{
                      fontSize: 11.5,
                      border: "1px solid var(--color-rule)",
                      background: "var(--color-sheet)",
                      borderRadius: 0,
                    }}
                  />
                  {/* Only OUR bar is accented. The moment consensus or the
                      baseline is orange, the eye stops knowing which is the claim. */}
                  <Bar dataKey="value">
                    {maeChart.map((bar) => (
                      <Cell
                        key={bar.name}
                        fill={
                          bar.kind === "ours"
                            ? "var(--color-accent)"
                            : "var(--color-paper-2)"
                        }
                        stroke={
                          bar.kind === "ours"
                            ? "var(--color-accent-2)"
                            : "var(--color-ink-3)"
                        }
                        strokeWidth={1}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dashed mt-3 grid grid-cols-2 gap-2 pt-3 text-[12.5px]">
              {[
                ["skill vs consensus", pct(bt.skill_vs_consensus, 2)],
                ["beat the baseline", pct(bt.beat_baseline_rate, 1)],
                ["win rate", pct(bt.win_rate_vs_consensus, 1)],
                [
                  "95% CI",
                  bt.win_rate_ci95
                    ? `${pct(bt.win_rate_ci95[0], 0)} – ${pct(bt.win_rate_ci95[1], 0)}`
                    : "—",
                ],
                [
                  "information ratio",
                  bt.information_ratio != null
                    ? bt.information_ratio.toFixed(2)
                    : "—",
                ],
                ["median AE", (bt.median_ae ?? 0).toFixed(4)],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between gap-3">
                  <dt className="tech text-ink-3">{String(label)}</dt>
                  <dd className="num font-semibold">{String(value)}</dd>
                </div>
              ))}
            </div>
            {spansHalf && (
              <p className="mt-2 text-[11.5px] leading-relaxed text-accent">
                The interval spans 50%. At this sample size we cannot distinguish
                skill from luck, and saying so is the point.
              </p>
            )}
          </Panel>

          <Panel
            label="calibration"
            hint="do the intervals cover what they claim? perfect is the diagonal"
            index={3}
          >
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={data.calibration ?? []}
                  margin={{ top: 10, right: 14, bottom: 4, left: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-rule-2)" />
                  <XAxis
                    dataKey="nominal"
                    type="number"
                    domain={[0, 1]}
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                    axisLine={{ stroke: "var(--color-rule)" }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 1]}
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                    axisLine={false}
                    tickLine={false}
                    width={46}
                  />
                  <Tooltip
                    formatter={tooltip((v) => pct(v))}
                    contentStyle={{
                      fontSize: 11.5,
                      border: "1px solid var(--color-rule)",
                      background: "var(--color-sheet)",
                      borderRadius: 0,
                    }}
                  />
                  <ReferenceLine
                    segment={[
                      { x: 0, y: 0 },
                      { x: 1, y: 1 },
                    ]}
                    stroke="var(--color-ink-3)"
                    strokeDasharray="5 3"
                  />
                  <Line
                    type="monotone"
                    dataKey="empirical"
                    stroke="var(--color-accent)"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "var(--color-accent)" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="dashed mt-2 pt-2 text-[11.5px] text-ink-3">
              Intervals come from bootstrapped residuals of our own backtest,
              conditioned on regime — how wrong we <em>have been</em>, not how
              wrong the model thinks it might be.
            </p>
          </Panel>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <Panel
            label="leave-one-lens-out ablation"
            hint="change in MAE when removed — positive means it earns its tokens"
            index={4}
          >
            {ablation.length === 0 ? (
              <p className="text-[12.5px] text-ink-2">
                Not run yet. Non-optional: without it, seven lenses is a claim
                rather than a finding.
              </p>
            ) : (
              <table className="w-full text-[12.5px]">
                <tbody>
                  {ablation.map(({ lens, delta }) => (
                    <tr
                      key={lens}
                      className="border-b border-rule-2 last:border-0"
                    >
                      <td className="py-1.5 font-semibold">
                        {lens.replace("_", " ")}
                      </td>
                      <td className="num py-1.5 text-right">
                        {delta >= 0 ? "+" : ""}
                        {delta.toFixed(5)}
                      </td>
                      <td className="py-1.5 pl-3 text-right">
                        {delta > 0.0001 ? (
                          <Pill tone="good">earns its tokens</Pill>
                        ) : (
                          <Pill tone="bad">drop it, and say so</Pill>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel
            label="λ, fitted"
            hint="β from actual ~ α·consensus + β·own, per regime"
            index={5}
          >
            {!data.lambda?.buckets ? (
              <p className="text-[12.5px] text-ink-2">
                Not fitted yet —{" "}
                <code className="font-mono text-[11.5px]">FITTED_BETA</code> still
                holds placeholders, so the thesis is asserted rather than measured.
              </p>
            ) : (
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="label border-b border-rule">
                    <th className="pb-1.5 text-left">regime</th>
                    <th className="pb-1.5 text-right">β</th>
                    <th className="pb-1.5 text-right">n</th>
                    <th className="pb-1.5 text-right">R²</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.lambda.buckets).map(([regime, fit]) => (
                    <tr
                      key={regime}
                      className="border-b border-rule-2 last:border-0"
                    >
                      <td className="py-1.5">
                        {regime}
                        {!fit.is_measured && (
                          <span className="tech ml-2 text-accent">
                            borrowed
                          </span>
                        )}
                      </td>
                      <td className="num py-1.5 text-right font-semibold">
                        {fit.beta.toFixed(3)}
                      </td>
                      <td className="num py-1.5 text-right">{fit.n}</td>
                      <td className="num py-1.5 text-right">
                        {fit.r_squared.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="dashed mt-3 pt-3 text-[11.5px] text-ink-3">
              Expect β small. A β near zero on heavy-coverage names is the correct
              result, not a failure — shrinking to sixty-one analysts with
              segment-level models is the skilful answer.
            </p>
          </Panel>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <Stat
            label="cases"
            value={String(bt.n ?? 0)}
            sub={`of 350 needed for 80% power`}
          />
          <Stat
            label="skill"
            value={pct(bt.skill_vs_consensus, 2)}
            sub="1 − Σ|F−A| / Σ|C−A|"
            accent
          />
          <Stat
            label="win rate"
            value={pct(bt.win_rate_vs_consensus, 1)}
            sub="closer than consensus"
          />
          <Stat
            label="run spread"
            value={(bt.mean_run_spread ?? 0).toFixed(4)}
            sub="across 5 runs per config"
          />
        </div>

        <Disclaimer>
          <strong className="text-ink">Historical validation only.</strong>{" "}
          Past accuracy is not indicative of future accuracy, and at this sample
          size the confidence interval on the win rate very likely spans 50% —
          which means nobody in the room can distinguish skill from luck. That is
          the honest reading and it is stated here rather than left for someone
          else to point out.
        </Disclaimer>
      </div>
    </Sheet>
  );
}
