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

import { Card, Empty, Pill, Stat, SyntheticBanner } from "@/components/ui";
import { eps, eps4, pct, signedPct, tooltip, useResult } from "@/lib/data";

/**
 * Screen 2 — the forecast.
 *
 * The distribution is the primary mark, not a decoration on a point estimate.
 * That is a claim about what the system knows: a well-calibrated interval is
 * the honest output, and the point is just one reading of it.
 *
 * Consensus sits on the SAME axis in neutral grey. Our forecast is the only
 * accented thing on the screen.
 */
export default function ForecastScreen() {
  const result = useResult();

  if (!result) {
    return (
      <Empty
        title="No forecast yet"
        detail="This screen reads out/results.json. Run the pipeline, or append ?replay=nvda to load a recorded run."
        command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
      />
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

  return (
    <div className="space-y-4">
      <SyntheticBanner trace={result.trace} />
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[17px] font-semibold tracking-tight">
          {f.ticker} {f.period}
        </h1>
        <p className="text-[12.5px] text-[--color-ink-2]">
          locked {f.as_of} · {f.distribution?.calibrated ? "calibrated" : "uncalibrated"} ·{" "}
          {lam?.preset}
        </p>
        {f.distribution?.calibrated ? (
          <Pill tone="good">interval from our own residuals</Pill>
        ) : (
          <Pill tone="warn">interval uncalibrated — not an 80% coverage claim</Pill>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <div className="space-y-5">
            <Stat
              label="Our forecast (non-GAAP)"
              value={eps(f.eps_non_gaap)}
              sub={`${signedPct(f.surprise_vs_consensus)} vs consensus`}
              accent
            />
            <Stat label="Wall Street consensus" value={eps(f.consensus?.eps)} />
            <Stat
              label="Baseline to beat"
              value={eps(f.baseline_eps)}
              sub="consensus × shrunk company surprise"
            />
            {f.eps_gaap != null && (
              <Stat
                label="GAAP equivalent"
                value={eps(f.eps_gaap)}
                sub="carried so the basis is a flag, not a design input"
              />
            )}
          </div>
        </Card>

        <Card
          className="lg:col-span-2"
          title="The distribution"
          hint="a strict superset of a point forecast — median for MAE, mean for MSE, quantiles for CRPS"
        >
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  axisLine={{ stroke: "var(--color-line)" }}
                  tickLine={false}
                />
                <YAxis
                  domain={["dataMin - 0.1", "dataMax + 0.1"]}
                  tick={{ fontSize: 11, fill: "var(--color-ink-2)" }}
                  axisLine={false}
                  tickLine={false}
                  width={52}
                  tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                />
                <Tooltip
                  formatter={tooltip((v) => eps4(v))}
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: "1px solid var(--color-line)",
                    background: "var(--color-surface)",
                  }}
                />
                {f.consensus?.eps != null && (
                  <ReferenceLine
                    y={f.consensus.eps}
                    stroke="var(--color-street)"
                    strokeDasharray="4 3"
                    label={{
                      value: `consensus ${eps(f.consensus.eps)}`,
                      position: "insideTopRight",
                      fontSize: 11,
                      fill: "var(--color-street)",
                    }}
                  />
                )}
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {bars.map((bar) => (
                    <Cell
                      key={bar.label}
                      fill={
                        bar.isMedian ? "var(--color-accent)" : "var(--color-accent-soft)"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* The gap, stated in words. A number on a chart is not an argument. */}
      <Card title="The gap, in words">
        <p className="text-[14px] leading-relaxed">
          We forecast{" "}
          <strong className="num text-[--color-accent]">{eps(f.eps_non_gaap)}</strong>{" "}
          against a Street consensus of{" "}
          <strong className="num">{eps(f.consensus?.eps)}</strong> —{" "}
          <strong className="num">
            {gap >= 0 ? "+" : ""}
            {gap.toFixed(2)}
          </strong>{" "}
          ({signedPct(f.surprise_vs_consensus)}).{" "}
          {lam && lam.value < 0.15 ? (
            <>
              λ is <span className="num">{lam.value.toFixed(3)}</span>, so we are
              deliberately close to the Street. On a well-covered name that is the
              skilful answer, not a failure to have a view.
            </>
          ) : (
            <>
              λ is <span className="num">{lam?.value.toFixed(3)}</span>, so we are
              committing away from the Street here.
            </>
          )}
        </p>
        {lam?.rationale && (
          <p className="mt-3 border-t border-[--color-line] pt-3 text-[13px] text-[--color-ink-2]">
            {lam.rationale}
          </p>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Why λ landed there" hint="the thesis, made explicit">
          <dl className="space-y-2 text-[13px]">
            {[
              ["Preset", lam?.preset],
              ["λ", lam?.value.toFixed(3)],
              ["Analysts covering", lam?.n_analysts ?? "unknown"],
              ["Dispersion", lam?.dispersion != null ? pct(lam.dispersion) : "unknown"],
              ["Consensus stale", lam?.consensus_stale ? "yes" : "no"],
              [
                "Internal disagreement",
                lam?.internal_disagreement != null
                  ? pct(lam.internal_disagreement)
                  : "—",
              ],
              ["Comparability flag", lam?.comparability_flag ?? "none — quarter is comparable"],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex justify-between gap-4">
                <dt className="text-[--color-ink-2]">{label}</dt>
                <dd className="num text-right font-medium">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </Card>

        <Card title="Run cost" hint="measured, not asserted">
          <dl className="space-y-2 text-[13px]">
            {[
              ["Total cost", `$${(f.total_cost_usd ?? 0).toFixed(4)}`],
              ["Input tokens", (f.total_input_tokens ?? 0).toLocaleString()],
              ["Output tokens", (f.total_output_tokens ?? 0).toLocaleString()],
              ["Wall clock", `${((f.wall_clock_ms ?? 0) / 1000).toFixed(1)}s`],
              ["Lenses kept", f.lenses?.length ?? 0],
              ["Lenses dropped", Object.keys(f.dropped_lenses ?? {}).length],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex justify-between gap-4">
                <dt className="text-[--color-ink-2]">{label}</dt>
                <dd className="num text-right font-medium">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </div>
  );
}
