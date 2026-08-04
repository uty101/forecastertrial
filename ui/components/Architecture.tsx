"use client";

import type { NodeStatus } from "@/lib/data";

/**
 * The architecture diagram IS the UI.
 *
 * This is the idea that collapses two prizes into one artifact: nodes light up
 * as the pipeline executes, with token counts and latency ticking in place. The
 * demo stops being "here's our architecture" and then "here's our output" — it
 * is one thing, and the room watches the system think.
 *
 * Hand-authored SVG, not React Flow. The graph is fixed, so a layout engine
 * buys nothing and costs a dependency, a bundle, and a fight with its
 * positioning. Here every node is a rect at a known coordinate wrapped in a
 * component that takes a status.
 */

export interface NodeSpec {
  id: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Pure code — cannot hallucinate. Drawn with a solid rule to make the point. */
  deterministic?: boolean;
}

export const NODES: NodeSpec[] = [
  // B — acquire
  { id: "B1_numbers", label: "Numbers", sub: "XBRL · consensus", x: 150, y: 99, w: 128, h: 46 },
  { id: "B1b_series", label: "Series", sub: "quarters · price bars", x: 150, y: 152, w: 128, h: 46 },
  { id: "B2_filings", label: "Filings", sub: "8-K 2.02 · EX-99", x: 150, y: 205, w: 128, h: 46 },
  { id: "B3_industry", label: "Industry", sub: "peers by SIC · news", x: 150, y: 258, w: 128, h: 46 },
  { id: "B4_macro", label: "Macro", sub: "FRED, point-in-time", x: 150, y: 311, w: 128, h: 46 },
  { id: "B5_extract", label: "Extract", sub: "guidance → cited guide", x: 150, y: 364, w: 128, h: 46 },

  // C — structure
  { id: "C_structure", label: "Evidence store", sub: "claims + quotes", x: 318, y: 228, w: 132, h: 58, deterministic: true },

  // D — the three-statement model
  { id: "D_model", label: "3-statement model", sub: "ratio base · self-checked", x: 490, y: 228, w: 132, h: 58, deterministic: true },

  // E — the seven lenses
  { id: "E_mechanical", label: "Mechanical", sub: "FX · shares · interest", x: 640, y: 96, w: 142, h: 44, deterministic: true },
  { id: "E_guidance", label: "Guidance", sub: "guide + landing CDF", x: 640, y: 148, w: 142, h: 44 },
  { id: "E_drivers", label: "Drivers", sub: "units × ASP", x: 640, y: 200, w: 142, h: 44 },
  { id: "E_margins", label: "Margins", sub: "GM mix · opex · tax", x: 640, y: 252, w: 142, h: 44 },
  { id: "E_forensics", label: "Forensics", sub: "accruals · exclusions", x: 640, y: 304, w: 142, h: 44 },
  { id: "E_peer_read", label: "Peer read", sub: "who already reported", x: 640, y: 356, w: 142, h: 44 },
  { id: "E_macro", label: "Macro", sub: "series vs assumed", x: 640, y: 408, w: 142, h: 44 },

  // V1 — reconcile
  { id: "V1_reconcile", label: "Reconcile", sub: "arithmetic + citations", x: 818, y: 96, w: 92, h: 356, deterministic: true },

  // D — champion
  { id: "F_champion", label: "Devil's advocate", sub: "argue, then argue against", x: 946, y: 96, w: 122, h: 356 },

  // E — judge
  { id: "G_judge", label: "Judge", sub: "materiality, never votes", x: 1104, y: 232, w: 118, h: 88 },

  // consensus + λ + V2
  { id: "consensus", label: "Wall St consensus", sub: "coverage · dispersion", x: 1258, y: 120, w: 118, h: 56 },
  { id: "H_lambda", label: "λ Positioning", sub: "fitted, not guessed", x: 1258, y: 232, w: 118, h: 88, deterministic: true },
  { id: "V2_comparability", label: "Comparability", sub: "fires → λ collapses", x: 1258, y: 366, w: 118, h: 62 },

  // V3 + output
  { id: "V3_calibrate", label: "Calibrate", sub: "own residuals", x: 1412, y: 240, w: 104, h: 72, deterministic: true },
  { id: "I_output", label: "Forecast", sub: "as a distribution", x: 1552, y: 240, w: 122, h: 72 },
];

const EDGES: Array<[string, string]> = [
  ["C_structure", "D_model"],
  ["B1_numbers", "C_structure"],
  ["B1b_series", "C_structure"],
  ["B2_filings", "C_structure"],
  ["B3_industry", "C_structure"],
  ["B4_macro", "C_structure"],
  ["B5_extract", "C_structure"],
  ["D_model", "E_mechanical"],
  ["D_model", "E_guidance"],
  ["D_model", "E_drivers"],
  ["D_model", "E_margins"],
  ["D_model", "E_forensics"],
  ["D_model", "E_peer_read"],
  ["D_model", "E_macro"],
  ["E_mechanical", "V1_reconcile"],
  ["E_guidance", "V1_reconcile"],
  ["E_drivers", "V1_reconcile"],
  ["E_margins", "V1_reconcile"],
  ["E_forensics", "V1_reconcile"],
  ["E_peer_read", "V1_reconcile"],
  ["E_macro", "V1_reconcile"],
  ["V1_reconcile", "F_champion"],
  ["F_champion", "G_judge"],
  ["G_judge", "H_lambda"],
  ["consensus", "H_lambda"],
  ["V2_comparability", "H_lambda"],
  ["H_lambda", "V3_calibrate"],
  ["V3_calibrate", "I_output"],
];

const FILL = {
  idle: "var(--color-paper-2)",
  running: "var(--color-accent-soft)",
  done: "var(--color-structure-soft)",
  failed: "var(--color-accent-soft)",
} as const;

const STROKE = {
  idle: "var(--color-idle)",
  running: "var(--color-accent)",
  done: "var(--color-structure)",
  failed: "var(--color-failed)",
} as const;

function edgePath(from: NodeSpec, to: NodeSpec): string {
  const x1 = from.x + from.w;
  const y1 = from.y + from.h / 2;
  const x2 = to.x;
  const y2 = to.y + to.h / 2;
  const mid = x1 + (x2 - x1) / 2;
  return `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
}

export default function Architecture({
  nodes,
}: {
  nodes: Record<string, NodeStatus>;
}) {
  const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

  return (
    <div className="scroll-x border border-rule bg-sheet p-3">
      <svg viewBox="0 0 1710 500" className="h-auto w-full min-w-[900px]">
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-ink-3)" />
          </marker>
        </defs>

        {/* phase labels */}
        {[
          ["1 · ACQUIRE", 214],
          ["2 · STRUCTURE", 384],
          ["3 · ANALYSE", 561],
          ["CHECK", 714],
          ["4 · CHALLENGE", 857],
          ["5 · JUDGE", 1013],
          ["6 · POSITION", 1167],
          ["CALIBRATE", 1314],
        ].map(([label, x]) => (
          <text
            key={label as string}
            x={x as number}
            y={42}
            textAnchor="middle"
            className="fill-ink-3"
            style={{
              fontSize: 9.5,
              fontWeight: 700,
              letterSpacing: "0.12em",
            }}
          >
            {label}
          </text>
        ))}

        {EDGES.map(([a, b]) => {
          const from = byId[a];
          const to = byId[b];
          if (!from || !to) return null;
          const active = nodes[a]?.state === "done";
          return (
            <path
              key={`${a}->${b}`}
              d={edgePath(from, to)}
              fill="none"
              stroke={active ? "var(--color-structure)" : "var(--color-idle)"}
              strokeWidth={active ? 1.5 : 1.1}
              opacity={active ? 0.75 : 0.4}
              markerEnd="url(#arrow)"
              className="state-change"
            />
          );
        })}

        {NODES.map((node) => {
          const status = nodes[node.id]?.state ?? "idle";
          const latency = nodes[node.id]?.latencyMs;
          return (
            <g
              key={node.id}
              className={status === "running" ? "node-running" : undefined}
            >
              <rect
                x={node.x}
                y={node.y}
                width={node.w}
                height={node.h}
                rx={8}
                fill={FILL[status]}
                stroke={STROKE[status]}
                strokeWidth={1.6}
                strokeDasharray={status === "idle" ? "4 3" : undefined}
                className="state-change"
              />
              <text
                x={node.x + node.w / 2}
                y={node.y + (node.sub ? node.h / 2 - 2 : node.h / 2 + 4)}
                textAnchor="middle"
                className="fill-ink"
                style={{ fontSize: 12, fontWeight: 650 }}
              >
                {node.label}
              </text>
              {node.sub && (
                <text
                  x={node.x + node.w / 2}
                  y={node.y + node.h / 2 + 13}
                  textAnchor="middle"
                  className="fill-ink-2"
                  style={{ fontSize: 9.5 }}
                >
                  {node.sub}
                </text>
              )}
              {/* Latency ticks in place — the token/latency read the demo
                  narrative depends on. */}
              {latency !== undefined && latency > 0 && (
                <text
                  x={node.x + node.w - 6}
                  y={node.y + 12}
                  textAnchor="end"
                  className="num fill-ink-3"
                  style={{ fontSize: 8.5 }}
                >
                  {latency >= 1000
                    ? `${(latency / 1000).toFixed(1)}s`
                    : `${latency}ms`}
                </text>
              )}
              {/* A dropped lens looks INTENTIONAL — greyed with a reason —
                  because something will fail live and failure should read as a
                  designed state rather than a crash. */}
              {status === "failed" && (
                <text
                  x={node.x + 6}
                  y={node.y + 12}
                  className="fill-failed"
                  style={{ fontSize: 9, fontWeight: 700 }}
                >
                  dropped
                </text>
              )}
            </g>
          );
        })}

        {/* The one architectural claim worth putting on the diagram itself. */}
        <text
          x={561}
          y={472}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 10 }}
        >
          seven lenses, blind to each other — if they talk, they converge
        </text>
        <text
          x={1167}
          y={452}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 10 }}
        >
          λ decides how far to deviate
        </text>
      </svg>

      <div className="mt-2 flex flex-wrap gap-4 border-t border-rule pt-3">
        {(
          [
            ["idle", "waiting"],
            ["running", "running"],
            ["done", "complete"],
            ["failed", "dropped, with a reason"],
          ] as const
        ).map(([state, label]) => (
          <span key={state} className="tech flex items-center gap-2">
            <span
              className="inline-block h-3 w-5 border"
              style={{ background: FILL[state], borderColor: STROKE[state] }}
            />
            {label}
          </span>
        ))}
        <span className="tech ml-auto text-ink-3">
          solid rule = pure code, no model, cannot hallucinate
        </span>
      </div>
    </div>
  );
}
