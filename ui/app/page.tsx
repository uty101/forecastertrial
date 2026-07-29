"use client";

import Architecture from "@/components/Architecture";
import { Card, Empty, Pill, Stat } from "@/components/ui";
import { eps, signedPct, useRun, type NodeStatus } from "@/lib/data";

/**
 * Screen 1 — the live run. This is the demo.
 *
 * The architecture diagram is the UI: nodes go idle → running → done as the
 * pipeline executes, with latency ticking in place. The room watches the system
 * think, rather than being shown a diagram and then, separately, a result.
 */

/**
 * The champion stage fans out per lens (`D_guidance`, `D_margins`, …) but is one
 * box on the diagram. Fold those into it: running if any is running, failed only
 * if all failed — a single flaky champion call should not paint the whole stage
 * red when six others succeeded.
 */
function fold(nodes: Record<string, NodeStatus>): Record<string, NodeStatus> {
  const folded = { ...nodes };
  const champions = Object.entries(nodes).filter(([id]) => id.startsWith("D_"));
  if (champions.length) {
    const states = champions.map(([, s]) => s.state);
    folded["D_champion"] = {
      state: states.includes("running")
        ? "running"
        : states.every((s) => s === "failed")
          ? "failed"
          : "done",
      latencyMs: Math.max(...champions.map(([, s]) => s.latencyMs ?? 0)),
    };
  }
  return folded;
}

export default function LiveRun() {
  const run = useRun();
  const nodes = fold(run.nodes);
  const forecast = run.result?.forecast;

  const done = Object.values(nodes).filter((n) => n.state === "done").length;
  const failed = Object.values(nodes).filter((n) => n.state === "failed").length;
  const running = Object.values(nodes).filter((n) => n.state === "running").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[17px] font-semibold tracking-tight">Live run</h1>
        {run.source === "replay" && (
          <Pill tone="warn">replay — a recorded log through the same code path</Pill>
        )}
        {run.source === "live" && !run.finished && running > 0 && (
          <Pill tone="accent">running</Pill>
        )}
        {run.finished && <Pill tone="good">complete</Pill>}
        <p className="ml-auto text-[12.5px] text-[--color-ink-2]">
          <span className="num">{done}</span> done ·{" "}
          <span className="num">{running}</span> running ·{" "}
          <span className="num">{failed}</span> dropped ·{" "}
          <span className="num">{run.claims}</span> claims
        </p>
      </div>

      {!run.started ? (
        <Empty
          title="No run in progress"
          detail="The pipeline appends to out/events.ndjson and this page polls it four times a second. Start a run, or append ?replay=nvda to watch a recorded one at its original pace."
          command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
        />
      ) : (
        <Architecture nodes={nodes} />
      )}

      {forecast && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <Stat
              label="Our forecast"
              value={eps(forecast.eps_non_gaap)}
              sub={`${signedPct(forecast.surprise_vs_consensus)} vs the Street`}
              accent
            />
          </Card>
          <Card>
            <Stat label="Consensus" value={eps(forecast.consensus?.eps)} sub="the bar" />
          </Card>
          <Card>
            <Stat
              label="Baseline"
              value={eps(forecast.baseline_eps)}
              sub="consensus × shrunk company tilt"
            />
          </Card>
          <Card>
            <Stat
              label="λ"
              value={(forecast.lambda_decision?.value ?? 0).toFixed(3)}
              sub={
                (forecast.lambda_decision?.value ?? 0) < 0.15
                  ? "shrunk to the Street — often the skilful answer"
                  : "committed away from the Street"
              }
            />
          </Card>
        </div>
      )}

      {run.started && (
        <Card title="Event stream" hint="the pipeline's only interface to this UI">
          <div className="scroll-x max-h-64 overflow-y-auto">
            <table className="w-full text-[12.5px]">
              <tbody>
                {run.events
                  .slice(-40)
                  .reverse()
                  .map((event) => (
                    <tr key={event.seq} className="border-b border-[--color-line]">
                      <td className="num py-1 pr-3 text-[--color-ink-3]">
                        {(event.ts_ms / 1000).toFixed(2)}s
                      </td>
                      <td className="py-1 pr-3 font-mono text-[--color-ink-2]">
                        {event.type}
                      </td>
                      <td className="py-1 pr-3 font-medium">{event.node ?? "—"}</td>
                      <td className="py-1 text-[--color-ink-2]">
                        {Object.entries(event.payload ?? {})
                          .filter(([k]) => k !== "error")
                          .map(([k, v]) => `${k}=${String(v)}`)
                          .join("  ")}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
