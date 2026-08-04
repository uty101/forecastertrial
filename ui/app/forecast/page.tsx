"use client";

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Callout,
  Dimension,
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
import { eps, eps4, pct, signedPct, tooltip, useResult } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 02 — the forecast.
 *
 * The distribution is the primary mark, not a decoration on a point estimate.
 * That is a claim about what the system knows: a well-calibrated interval is the
 * honest output, and the point is one reading of it.
 *
 * Consensus sits on the SAME axis in neutral ink. Our forecast is the only
 * accented thing on the sheet.
 */
export default function ForecastScreen() {
  const result = useResult();

  if (!result) {
    return (
      <Sheet system="earnings forecast" sheet={sheetOf("/forecast/")}>
        <Empty
          title="No forecast yet"
          detail="This sheet reads out/results.json. Run the pipeline, or append ?replay=nvda to load a recorded run."
          command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
        />
      </Sheet>
    );
  }

  const f = result.forecast;
  const quantiles = f.distribution?.quantiles ?? {};
  const levels = Object.keys(quantiles).sort((a, b) => Number(a) - Number(b));
  const bars = levels.map((q) => ({
    label: `p${Math.round(Number(q) * 100)}`,
    value: quantiles[q],
    isMedian: q === "0.5",
  }));

  const gap = f.eps_non_gaap - (f.consensus?.eps ?? f.eps_non_gaap);
  const lam = f.lambda_decision;
  const band = (quantiles["0.9"] ?? 0) - (quantiles["0.1"] ?? 0);

  return (
    <Sheet
      system="earnings forecast"
      readout={[`${f.ticker} ${f.period}`, `LOCKED ${f.as_of}`]}
      sheet={sheetOf("/forecast/")}
      footer={
        <SheetFooter
          cells={[
            ["basis", "non-GAAP (consensus basis)"],
            ["preset", lam?.preset ?? "—"],
            [
              "interval",
              f.distribution?.calibrated
                ? "calibrated on own residuals"
                : "uncalibrated",
            ],
            ["p10–p90 band", `$${band.toFixed(2)}`],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <SyntheticBanner trace={result.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Lede>
            A distribution is a strict superset of a point forecast — median for MAE, mean for MSE, quantiles for CRPS. Building it once makes the scoring rule a config value.
          </Lede>

          <StatusPanel
            title="forecast status"
            state={f.distribution?.calibrated ? "calibrated" : "uncalibrated"}
            detail={`${f.lenses?.length ?? 0} lenses survived`}
            fraction={f.distribution?.calibrated ? 1 : 0.55}
            tone={f.distribution?.calibrated ? "done" : "running"}
            rows={[
              ["our EPS", eps(f.eps_non_gaap)],
              ["consensus", eps(f.consensus?.eps)],
              ["λ", (lam?.value ?? 0).toFixed(3)],
              ["dropped", Object.keys(f.droppee_lenses ?? {}).length],
            ]}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-[300px_1fr]">
          <div className="space-y-3">
            <Panel label="our forecast" index={1}>
              <Stat
                label="non-GAAP EPS"
                value={eps(f.eps_non_gaap)}
                sub={`${signedPct(f.surprise_vs_consensus)} vs consensus`}
                accent
                size="lg"
              />
            </Panel>
            <Panel label="the street" index={2}>
              <Stat label="consensus EPS" value={eps(f.consensus?.eps)} />
            </Panel>
            <Panel label="the number to beat" index={3}>
              <Stat
                label="baseline"
                value={eps(f.baseline_eps)}
                sub="consensus × shrunk company surprise — not a strawman"
              />
            </Panel>
            {f.eps_gaap != null && (
              <Panel label="other basis" index={4}>
                <Stat
                  label="GAAP equivalent"
                  value={eps(f.eps_gaap)}
                  sub="carried so the basis is a flag, not a design input"
                />
              </Panel>
            )}
          </div>

          <Panel
            label="distribution"
            hint="the primary mark — consensus on the same axis, in neutral ink"
          >
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={bars}
                  margin={{ top: 10, right: 14, bottom: 4, left: 4 }}
                >
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    axisLine={{ stroke: "var(--color-rule)" }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={["dataMin - 0.12", "dataMax + 0.12"]}
                    tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                    axisLine={false}
                    tickLine={false}
                    width={54}
                    tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                  />
                  <Tooltip
                    formatter={tooltip((v) => eps4(v))}
                    contentStyle={{
                      fontSize: 11.5,
                      border: "1px solid var(--color-rule)",
                      background: "var(--color-sheet)",
                      borderRadius: 0,
                    }}
                  />
                  {f.consensus?.eps != null && (
                    <ReferenceLine
                      y={f.consensus.eps}
                      stroke="var(--color-ink-3)"
                      strokeDasharray="5 3"
                      label={{
                        value: `consensus ${eps(f.consensus.eps)}`,
                        position: "insideTopRight",
                        fontSize: 10.5,
                        fill: "var(--color-ink-2)",
                      }}
                    />
                  )}
                  <Bar dataKey="value">
                    {bars.map((bar) => (
                      <Cell
                        key={bar.label}
                        fill={
                          bar.isMedian
                            ? "var(--color-accent)"
                            : "var(--color-structure-soft)"
                        }
                        stroke={
                          bar.isMedian
                            ? "var(--color-accent-2)"
                            : "var(--color-structure)"
                        }
                        strokeWidth={1}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <Dimension
              className="mt-2"
              value={`$${band.toFixed(2)}`}
              label="p10 → p90"
            />
          </Panel>
        </div>

        {/* The gap, stated in words. A number on a chart is not an argument. */}
        <Panel label="the gap, in words">
          <p className="text-[14.5px] leading-relaxed">
            We forecast{" "}
            <strong className="num text-accent">
              {eps(f.eps_non_gaap)}
            </strong>{" "}
            against a Street consensus of{" "}
            <strong className="num">{eps(f.consensus?.eps)}</strong> —{" "}
            <strong className="num">
              {gap >= 0 ? "+" : ""}
              {gap.toFixed(2)}
            </strong>{" "}
            ({signedPct(f.surprise_vs_consensus)}).{" "}
            {lam && lam.value < 0.15 ? (
              <>
                λ is <span className="num">{lam.value.toFixed(3)}</span>, so we
                are deliberately close to the Street. On a well-covered name that
                is the skilful answer, not a failure to have a view.
              </>
            ) : (
              <>
                λ is <span className="num">{lam?.value.toFixed(3)}</span>, so we
                are committing away from the Street here.
              </>
            )}
          </p>
          {lam?.rationale && (
            <p className="dashed mt-3 pt-3 text-[12.5px] leading-relaxed text-ink-2">
              {lam.rationale}
            </p>
          )}
        </Panel>

        <div className="grid gap-3 md:grid-cols-3">
          <Panel label="why λ landed there">
            <dl className="space-y-1.5 text-[12.5px]">
              {[
                ["preset", lam?.preset],
                ["λ", lam?.value.toFixed(3)],
                ["analysts covering", lam?.n_analysts ?? "unknown"],
                [
                  "dispersion",
                  lam?.dispersion != null ? pct(lam.dispersion) : "unknown",
                ],
                ["consensus stale", lam?.consensus_stale ? "yes" : "no"],
                [
                  "internal disagreement",
                  lam?.internal_disagreement != null
                    ? pct(lam.internal_disagreement)
                    : "—",
                ],
                ["comparability", lam?.comparability_flag ?? "clean"],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between gap-4">
                  <dt className="tech text-ink-3">{String(label)}</dt>
                  <dd className="num text-right font-semibold">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <Panel label="run cost" hint="measured, not asserted">
            <dl className="space-y-1.5 text-[12.5px]">
              {[
                ["total cost", `$${(f.total_cost_usd ?? 0).toFixed(4)}`],
                ["input tokens", (f.total_input_tokens ?? 0).toLocaleString()],
                ["output tokens", (f.total_output_tokens ?? 0).toLocaleString()],
                ["wall clock", `${((f.wall_clock_ms ?? 0) / 1000).toFixed(1)}s`],
                ["lenses kept", f.lenses?.length ?? 0],
                ["lenses dropped", Object.keys(f.droppee_lenses ?? {}).length],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between gap-4">
                  <dt className="tech text-ink-3">{String(label)}</dt>
                  <dd className="num text-right font-semibold">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <div className="space-y-3">
            <Callout
              label="calibration"
              tone={f.distribution?.calibrated ? "structure" : "accent"}
            >
              {String(result.trace?.calibration ?? "no calibration note recorded")}
            </Callout>
            <Callout label="baseline">
              {String(result.trace?.baseline ?? "no baseline note recorded")}
            </Callout>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {f.distribution?.calibrated ? (
            <Pill tone="good">interval built from our own residuals</Pill>
          ) : (
            <Pill tone="warn">interval uncalibrated — not an 80% coverage claim</Pill>
          )}
          <Pill tone="neutral">median minimises MAE · mean minimises MSE</Pill>
        </div>
      </div>
    </Sheet>
  );
}
