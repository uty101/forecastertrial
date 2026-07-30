"use client";

import Architecture from "@/components/Architecture";
import {
  Callout,
  Display,
  Empty,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  StageStrip,
  Stat,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import { eps, signedPct, useRun, type NodeStatus } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 01 — the live run. This is the demo.
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

const STAGES = [
  { n: 1, title: "Acquire", detail: "Numbers, filings, peers, macro — ranked, budgeted", ids: ["A1_numbers", "A2_filings", "A3_industry", "A4_macro"] },
  { n: 2, title: "Structure", detail: "Evidence store, one cached corpus", ids: ["B_structure"] },
  { n: 3, title: "Analyse", detail: "Seven lenses, blind to each other", ids: ["C_mechanical", "C_guidance", "C_drivers", "C_margins", "C_forensics", "C_peer_read", "C_macro"] },
  { n: 4, title: "Reconcile", detail: "Arithmetic + citations; fail drops the lens", ids: ["V1_reconcile"] },
  { n: 5, title: "Challenge", detail: "Argue each case, then argue against it", ids: ["D_champion"] },
  { n: 6, title: "Judge", detail: "Materiality, never votes → a distribution", ids: ["E_judge"] },
  { n: 7, title: "Position", detail: "λ vs consensus, fitted and conditioned", ids: ["F_lambda", "V2_comparability", "V3_calibrate"] },
];

function stageState(
  ids: string[],
  nodes: Record<string, NodeStatus>,
): "idle" | "running" | "done" | "failed" {
  const seen = ids.map((id) => nodes[id]?.state).filter(Boolean);
  if (!seen.length) return "idle";
  if (seen.includes("running")) return "running";
  if (seen.every((s) => s === "failed")) return "failed";
  return seen.length === ids.length ? "done" : "running";
}

export default function LiveRun() {
  const run = useRun();
  const nodes = fold(run.nodes);
  const forecast = run.result?.forecast;

  const states = Object.values(nodes).map((n) => n.state);
  const done = states.filter((s) => s === "done").length;
  const failed = states.filter((s) => s === "failed").length;
  const running = states.filter((s) => s === "running").length;
  const total = 19; // nodes on the diagram

  const elapsed = run.events.at(-1)?.ts_ms ?? 0;

  return (
    <Sheet
      system="pipeline execution"
      readout={
        forecast
          ? [`${forecast.ticker} ${forecast.period}`, `LOCKED ${forecast.as_of}`]
          : ["AWAITING RUN", "NO LOCK DATE"]
      }
      sheet={sheetOf("/")}
      footer={
        <SheetFooter
          cells={[
            ["stages", `${done}/${total} nodes complete`],
            ["source", run.source === "replay" ? "recorded log, original pacing" : run.source],
            ["elapsed", `${(elapsed / 1000).toFixed(1)}s`],
            ["interface", "out/events.ndjson — no API"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        {run.result?.trace && <SyntheticBanner trace={run.result.trace} />}

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <div className="space-y-5">
            <Display
              kicker="No forecast starts with a guess. Every number on this sheet traces to a filing, a quote and a date — or it does not exist."
            >
              First,
              <br />
              <Green>it reads everything.</Green>
            </Display>

            {run.finished && <Pill tone="good">run complete</Pill>}
            {!run.finished && running > 0 && (
              <span className="inline-flex items-center gap-2">
                <span className="blink inline-block h-2 w-2 rounded-full bg-accent" />
                <Pill tone="warn">executing</Pill>
              </span>
            )}
            {run.source === "replay" && (
              <Pill tone="neutral">replay — recorded log, identical code path</Pill>
            )}
          </div>

          <StatusPanel
            title="run status"
            state={
              run.finished
                ? "complete"
                : running > 0
                  ? "active"
                  : run.started
                    ? "idle"
                    : "waiting"
            }
            detail={run.started ? `${running} node${running === 1 ? "" : "s"} running` : undefined}
            fraction={done / total}
            tone={run.finished ? "done" : running > 0 ? "running" : "idle"}
            rows={[
              ["nodes done", done],
              ["dropped", failed],
              ["claims", run.claims],
              ["events", run.events.length],
            ]}
          />
        </div>

        {!run.started ? (
          <Empty
            title="No run in progress"
            detail="The pipeline appends to out/events.ndjson and this sheet polls it four times a second. Start a run, or append ?replay=nvda to watch a recorded one at its original pace."
            command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
          />
        ) : (
          <Architecture nodes={nodes} />
        )}

        <StageStrip
          stages={STAGES.map((s) => ({
            n: s.n,
            title: s.title,
            detail: s.detail,
            state: stageState(s.ids, nodes),
          }))}
        />

        {forecast && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Panel label="our forecast">
              <Stat
                label="non-GAAP EPS"
                value={eps(forecast.eps_non_gaap)}
                sub={`${signedPct(forecast.surprise_vs_consensus)} vs the Street`}
                accent
              />
            </Panel>
            <Panel label="consensus">
              <Stat label="the bar" value={eps(forecast.consensus?.eps)} />
            </Panel>
            <Panel label="baseline">
              <Stat
                label="to beat"
                value={eps(forecast.baseline_eps)}
                sub="consensus × shrunk company tilt"
              />
            </Panel>
            <Panel label="position">
              <Stat
                label="λ"
                value={(forecast.lambda_decision?.value ?? 0).toFixed(3)}
                sub={
                  (forecast.lambda_decision?.value ?? 0) < 0.15
                    ? "shrunk to the Street — often the skilful answer"
                    : "committed away from the Street"
                }
              />
            </Panel>
          </div>
        )}

        <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
          {run.started && (
            <Panel label="event stream" hint="the pipeline's only interface to this sheet">
              <div className="scroll-x max-h-72 overflow-y-auto">
                <table className="w-full text-[11.5px]">
                  <tbody>
                    {run.events
                      .slice(-45)
                      .reverse()
                      .map((event) => (
                        <tr
                          key={event.seq}
                          className="border-b border-rule-2"
                        >
                          <td className="num py-1 pr-3 text-ink-3">
                            {(event.ts_ms / 1000).toFixed(2)}s
                          </td>
                          <td className="tech py-1 pr-3">{event.type}</td>
                          <td className="py-1 pr-3 font-medium">
                            {event.node ?? "—"}
                          </td>
                          <td className="py-1 text-ink-2">
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
            </Panel>
          )}

          <div className="space-y-3">
            <Callout label="core principle" tone="accent">
              Reproduce the analysis. Strip the incentives. Then ask the one
              question no individual analyst can, because they{" "}
              <em>are</em> the consensus: where is it structurally weak?
            </Callout>
            <Callout label="why files, not an API">
              Python appends events; this sheet polls the file. Nothing to crash
              mid-demo — and replay mode comes free, because a recorded run
              replays through the identical code path.
            </Callout>
          </div>
        </div>
      </div>
    </Sheet>
  );
}
