"use client";

import { useEffect, useState } from "react";
import {
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

import { Card, Empty, Pill } from "@/components/ui";
import { pct, tooltip } from "@/lib/data";

/**
 * Screen 5 — the method. This is what the architecture prize is actually
 * judged on, and it is the screen most teams do not build.
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
 */

interface EvalPayload {
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
    underpowered?: boolean;
    power_note?: string;
  };
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
      <div className="space-y-4">
        <h1 className="text-[17px] font-semibold tracking-tight">Method</h1>
        <Empty
          title="No eval yet — and this is the gate"
          detail="Nothing downstream means anything until the baseline number exists. Build the firm-quarter cases, score consensus × 1.02 against them, and everything after that is measured against it rather than asserted."
          command="uv run forecast cases  →  uv run forecast backtest"
        />
        <Card title="What goes here" hint="the four things a sceptical reader asks for">
          <ol className="list-inside list-decimal space-y-2 text-[13.5px] leading-relaxed text-[--color-ink-2]">
            <li>
              <strong className="text-[--color-ink]">Backtest vs the baseline.</strong>{" "}
              Not vs nothing. <code className="font-mono text-[12px]">consensus × (1 + shrunk company tilt)</code>{" "}
              is a genuinely strong forecaster — 78% of S&amp;P 500 companies beat
              consensus, aggregate surprise +7% — and every competent competitor will
              find it.
            </li>
            <li>
              <strong className="text-[--color-ink]">A reliability diagram.</strong> Do
              the 80% intervals cover 80%? They will not at first. Fixing that is
              cheap and visual; hiding it is not honest.
            </li>
            <li>
              <strong className="text-[--color-ink]">
                Leave-one-lens-out ablation.
              </strong>{" "}
              The marginal contribution of each of the seven. Non-optional. If two do
              not earn their tokens, drop them and say so on stage.
            </li>
            <li>
              <strong className="text-[--color-ink]">n, with a confidence interval.</strong>{" "}
              Detecting a 2% edge at 80% power needs about 350 resolved forecasts.
              With a handful of live companies nobody can distinguish skill from luck
              — say it before someone else does.
            </li>
          </ol>
        </Card>
      </div>
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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[17px] font-semibold tracking-tight">Method</h1>
        {bt.underpowered ? (
          <Pill tone="warn">underpowered — ranking is variance-dominated</Pill>
        ) : (
          <Pill tone="good">adequately powered</Pill>
        )}
        <p className="ml-auto text-[12.5px] text-[--color-ink-2]">
          n = <span className="num">{bt.n ?? 0}</span> resolved firm-quarters
        </p>
      </div>

      {bt.power_note && (
        <Card>
          <p className="text-[13.5px] leading-relaxed text-[--color-ink-2]">
            {bt.power_note}
          </p>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Mean absolute error"
          hint="the baseline is on the chart — it is not a strawman"
        >
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={maeChart} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  axisLine={{ stroke: "var(--color-line)" }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  axisLine={false}
                  tickLine={false}
                  width={52}
                />
                <Tooltip
                  formatter={tooltip((v) => v.toFixed(4))}
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: "1px solid var(--color-line)",
                    background: "var(--color-surface)",
                  }}
                />
                {/* Only OUR bar gets the accent. Consensus and the baseline are
                    neutral grey — the moment a second thing is accented the eye
                    stops knowing which number is the claim. */}
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {maeChart.map((bar) => (
                    <Cell
                      key={bar.name}
                      fill={
                        bar.kind === "ours"
                          ? "var(--color-accent)"
                          : "var(--color-street)"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-[--color-line] pt-3 text-[13px]">
            <div className="flex justify-between gap-3">
              <dt className="text-[--color-ink-2]">Skill vs consensus</dt>
              <dd className="num font-medium">{pct(bt.skill_vs_consensus, 2)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[--color-ink-2]">Beat the baseline</dt>
              <dd className="num font-medium">{pct(bt.beat_baseline_rate, 1)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[--color-ink-2]">Win rate</dt>
              <dd className="num font-medium">{pct(bt.win_rate_vs_consensus, 1)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[--color-ink-2]">95% CI</dt>
              <dd className="num font-medium">
                {bt.win_rate_ci95
                  ? `${pct(bt.win_rate_ci95[0], 0)} – ${pct(bt.win_rate_ci95[1], 0)}`
                  : "—"}
              </dd>
            </div>
          </dl>
          {bt.win_rate_ci95 &&
            bt.win_rate_ci95[0] < 0.5 &&
            bt.win_rate_ci95[1] > 0.5 && (
              <p className="mt-2 text-[12.5px] text-amber-700 dark:text-amber-400">
                The interval spans 50%. At this sample size we cannot distinguish
                skill from luck, and saying so is the point.
              </p>
            )}
        </Card>

        <Card
          title="Calibration"
          hint="do the intervals cover what they claim? perfect calibration is the diagonal"
        >
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data.calibration ?? []}
                margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" />
                <XAxis
                  dataKey="nominal"
                  type="number"
                  domain={[0, 1]}
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  axisLine={{ stroke: "var(--color-line)" }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 1]}
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                />
                <Tooltip
                  formatter={tooltip((v) => pct(v))}
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: "1px solid var(--color-line)",
                    background: "var(--color-surface)",
                  }}
                />
                <ReferenceLine
                  segment={[
                    { x: 0, y: 0 },
                    { x: 1, y: 1 },
                  ]}
                  stroke="var(--color-street)"
                  strokeDasharray="4 3"
                />
                <Line
                  type="monotone"
                  dataKey="empirical"
                  stroke="var(--color-accent)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-3 border-t border-[--color-line] pt-3 text-[12.5px] text-[--color-ink-2]">
            Intervals come from bootstrapped residuals of our own backtest,
            conditioned on regime — how wrong we have been, not how wrong the model
            thinks it might be.
          </p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Leave-one-lens-out ablation"
          hint="change in MAE when the lens is removed — positive means it earns its tokens"
        >
          {ablation.length === 0 ? (
            <p className="text-[13px] text-[--color-ink-2]">
              Not run yet. This is non-optional: without it, seven lenses is a claim
              rather than a finding.
            </p>
          ) : (
            <table className="w-full text-[13px]">
              <tbody>
                {ablation.map(({ lens, delta }) => (
                  <tr key={lens} className="border-b border-[--color-line] last:border-0">
                    <td className="py-1.5 font-medium">{lens}</td>
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
        </Card>

        <Card
          title="λ, fitted"
          hint="β from actual ~ α·consensus + β·own, per regime"
        >
          {!data.lambda?.buckets ? (
            <p className="text-[13px] text-[--color-ink-2]">
              Not fitted yet — <code className="font-mono text-[12px]">FITTED_BETA</code>{" "}
              still holds placeholders, so the thesis is asserted rather than measured.
            </p>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-[--color-ink-3]">
                  <th className="pb-2 text-left font-semibold">Regime</th>
                  <th className="pb-2 text-right font-semibold">β</th>
                  <th className="pb-2 text-right font-semibold">n</th>
                  <th className="pb-2 text-right font-semibold">R²</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.lambda.buckets).map(([regime, fit]) => (
                  <tr key={regime} className="border-b border-[--color-line] last:border-0">
                    <td className="py-1.5">
                      {regime}
                      {!fit.is_measured && (
                        <span className="ml-2 text-[11px] text-amber-600 dark:text-amber-400">
                          borrowed from pooled
                        </span>
                      )}
                    </td>
                    <td className="num py-1.5 text-right font-medium">
                      {fit.beta.toFixed(3)}
                    </td>
                    <td className="num py-1.5 text-right">{fit.n}</td>
                    <td className="num py-1.5 text-right">{fit.r_squared.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 border-t border-[--color-line] pt-3 text-[12.5px] text-[--color-ink-2]">
            Expect β small. A β near zero on heavy-coverage names is the correct
            result, not a failure — shrinking to sixty-one analysts with segment
            models is the skilful answer.
          </p>
        </Card>
      </div>
    </div>
  );
}
