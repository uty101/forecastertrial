"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Callout,
  Dimension,
  Display,
  Empty,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import { pct, tooltip, useResult } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 08 — cost.
 *
 * Tokens are a variable cost to allocate strategically, and this sheet is the
 * receipt. Every figure is measured from the call ledger the client keeps —
 * nothing here is estimated, which matters because a cost claim on stage is the
 * easiest thing in a demo to be caught inventing.
 *
 * The number worth pointing at is the cached read share. Seven lenses fan out
 * against one evidence corpus placed behind a cache breakpoint, so it is written
 * once and read six times at a tenth of the price. That is most of the reason
 * five runs per config is affordable at all.
 */
export default function CostScreen() {
  const result = useResult();

  if (!result) {
    return (
      <Sheet system="token allocation" sheet={sheetOf("/cost/")}>
        <Empty
          title="No cost ledger yet"
          detail="Per-stage token accounting is recorded by the LLM client on every call and written into out/results.json."
          command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
        />
      </Sheet>
    );
  }

  const f = result.forecast;
  const cost = (result.trace?.cost ?? {}) as {
    total_cost_usd?: number;
    ceiling_usd?: number;
    total_calls?: number;
    by_prompt?: Record<
      string,
      { calls: number; input: number; output: number; cost_usd: number; cached: number }
    >;
  };
  const byPrompt = cost.by_prompt ?? {};
  const rows = Object.entries(byPrompt)
    .map(([id, row]) => ({ id, ...row }))
    .sort((a, b) => b.cost_usd - a.cost_usd);

  const spent = cost.total_cost_usd ?? f.total_cost_usd ?? 0;
  const ceiling = cost.ceiling_usd ?? 25;
  const utilisation = ceiling ? spent / ceiling : 0;
  const calls = cost.total_calls ?? rows.reduce((n, r) => n + r.calls, 0);
  const cachedCalls = rows.reduce((n, r) => n + r.cached, 0);

  return (
    <Sheet
      system="token allocation"
      readout={[`${f.ticker} ${f.period}`, `$${spent.toFixed(4)} SPENT`]}
      sheet={sheetOf("/cost/")}
      footer={
        <SheetFooter
          cells={[
            ["spend", `$${spent.toFixed(4)} of $${ceiling.toFixed(2)} ceiling`],
            ["calls", `${calls} (${cachedCalls} served from cache)`],
            ["kill switch", "checked before each call, not after"],
            ["accounting", "measured from the call ledger"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <SyntheticBanner trace={result.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Display kicker="Cheap models for extraction, mid for the seven lenses and the advocate, one expensive call for the judge. Every figure on this sheet is measured from the call ledger, never estimated.">
            Tokens are
            <br />
            <Green>a budget, not a bill.</Green>
          </Display>

          <StatusPanel
            title="budget status"
            state={utilisation > 0.9 ? "at limit" : "within budget"}
            detail={`$${spent.toFixed(4)} of $${ceiling.toFixed(2)}`}
            fraction={Math.min(1, utilisation)}
            tone={utilisation > 0.9 ? "failed" : utilisation > 0.6 ? "running" : "done"}
            rows={[
              ["total cost", `$${spent.toFixed(4)}`],
              ["ceiling", `$${ceiling.toFixed(2)}`],
              ["model calls", calls],
              ["cache hits", cachedCalls],
            ]}
          />
        </div>

        {rows.length === 0 ? (
          <Empty
            title="No model calls in this run"
            detail="Either every stage was served from cache, or this run was produced without the LLM layer. The Mechanical lens needs no model at all, so a run can legitimately reach a forecast with zero spend."
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Panel
              label="cost by agent"
              hint="one expensive judge call carries more of the bill than six lenses"
              index={1}
            >
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={rows}
                    layout="vertical"
                    margin={{ top: 6, right: 16, bottom: 4, left: 4 }}
                  >
                    <XAxis
                      type="number"
                      tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                      axisLine={{ stroke: "var(--color-rule)" }}
                      tickLine={false}
                      tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                    />
                    <YAxis
                      type="category"
                      dataKey="id"
                      width={124}
                      tick={{ fontSize: 10.5, fill: "var(--color-ink-2)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      formatter={tooltip((v) => `$${v.toFixed(5)}`)}
                      contentStyle={{
                        fontSize: 11.5,
                        border: "1px solid var(--color-rule)",
                        background: "var(--color-sheet)",
                        borderRadius: 0,
                      }}
                    />
                    <Bar dataKey="cost_usd">
                      {rows.map((row) => (
                        <Cell
                          key={row.id}
                          fill={
                            row.id === "judge"
                              ? "var(--color-accent)"
                              : "var(--color-structure-soft)"
                          }
                          stroke={
                            row.id === "judge"
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
                value={`$${spent.toFixed(4)}`}
                label="total this run"
              />
            </Panel>

            <div className="space-y-3">
              <Callout label="the cached prefix" tone="accent">
                The evidence corpus sits in a cached system block, so a seven-lens
                fan-out writes it once and reads it six times at a tenth of the
                price. Cache reads cost 0.1× base input; writes cost 1.25×. That
                multiplier is most of the reason five runs per config is
                affordable.
              </Callout>
              <Callout label="the kill switch">
                The ceiling is checked <em>before</em> the call that would breach
                it, not after. An overspend you detect afterwards is an overspend
                you already paid for — and a loop burning credits at 14:00 ends
                the day.
              </Callout>
            </div>
          </div>
        )}

        {rows.length > 0 && (
          <Panel label="per-agent ledger" hint="calls, tokens, cache hits and cost">
            <div className="scroll-x">
              <table className="w-full min-w-[620px] text-[12.5px]">
                <thead>
                  <tr className="label border-b border-rule">
                    <th className="pb-1.5 text-left">agent</th>
                    <th className="pb-1.5 text-right">calls</th>
                    <th className="pb-1.5 text-right">cached</th>
                    <th className="pb-1.5 text-right">input</th>
                    <th className="pb-1.5 text-right">output</th>
                    <th className="pb-1.5 text-right">cost</th>
                    <th className="pb-1.5 text-right">share</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-b border-rule-2 last:border-0"
                    >
                      <td className="py-1.5 font-semibold">{row.id}</td>
                      <td className="num py-1.5 text-right">{row.calls}</td>
                      <td className="num py-1.5 text-right">
                        {row.cached > 0 ? (
                          <span className="text-structure">
                            {row.cached}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="num py-1.5 text-right">
                        {row.input.toLocaleString()}
                      </td>
                      <td className="num py-1.5 text-right">
                        {row.output.toLocaleString()}
                      </td>
                      <td className="num py-1.5 text-right font-semibold">
                        ${row.cost_usd.toFixed(5)}
                      </td>
                      <td className="num py-1.5 text-right text-ink-2">
                        {spent ? pct(row.cost_usd / spent, 0) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        <div className="grid gap-3 sm:grid-cols-4">
          <Stat
            label="total cost"
            value={`$${spent.toFixed(4)}`}
            sub={`${pct(utilisation, 1)} of the ceiling`}
            accent
          />
          <Stat
            label="input tokens"
            value={(f.total_input_tokens ?? 0).toLocaleString()}
            sub="including cached reads"
          />
          <Stat
            label="output tokens"
            value={(f.total_output_tokens ?? 0).toLocaleString()}
          />
          <Stat
            label="wall clock"
            value={`${((f.wall_clock_ms ?? 0) / 1000).toFixed(1)}s`}
            sub={`${calls} model calls`}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <Pill tone="neutral">cheap → extraction</Pill>
          <Pill tone="neutral">mid → seven lenses + advocate</Pill>
          <Pill tone="warn">deep → one judge call</Pill>
          <Pill tone="good">λ → plain code, no model</Pill>
        </div>
      </div>
    </Sheet>
  );
}
