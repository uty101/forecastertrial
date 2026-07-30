"use client";

import type { NodeStatus } from "@/lib/data";

/**
 * The whole system as a reporting chain.
 *
 * An org chart implies hierarchy, so the hierarchy has to be the real one. It is:
 * the forecast is the deliverable, λ decides how far from consensus to sit, the
 * judge hands λ a distribution, seven champions each hand the judge one attacked
 * case, each champion pairs with exactly one lens, every lens draws on the same
 * evidence store, and four acquirers feed it from four data sources.
 *
 * The three verification layers sit BESIDE the chain rather than in it, drawn
 * with dashed leaders, because that is what they are: an independent function
 * with veto power. V1 can drop a lens, V2 can collapse λ, V3 can rewrite the
 * interval. None of them contributes an estimate.
 *
 * One structural fact the layout is built to make obvious: the lens row has no
 * horizontal links. Seven siblings, no peer edges. In an org chart that reads as
 * "these roles do not coordinate", which is exactly right — they are blind to
 * each other by design.
 *
 * Three overlays on one chart, because the same hierarchy answers three
 * different questions: what is built, what is running, and what each part costs.
 */

export type Overlay = "build" | "live" | "tier";

export interface OrgNode {
  id: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Component id in build.json, when one exists. */
  component?: string;
  /** Event-log node id, when one exists. */
  liveId?: string;
  tier?: "none" | "cheap" | "mid" | "deep";
  /** Verification layers are drawn as an independent function, not a step. */
  audit?: boolean;
  role?: string;
}

const W = 1520;
const H = 900;
const MID = W / 2;

const LENS_NAMES = [
  ["mechanical", "Mechanical", "FX · shares · interest", "none"],
  ["guidance", "Guidance", "guide + landing CDF", "mid"],
  ["drivers", "Drivers", "units × ASP", "mid"],
  ["margins", "Margins", "GM mix · opex · tax", "mid"],
  ["forensics", "Forensics", "accruals · exclusions", "mid"],
  ["peer_read", "Peer read", "who already reported", "mid"],
  ["macro", "Macro", "series vs assumed", "mid"],
] as const;

const LENS_W = 176;
const LENS_GAP = 16;
const LENS_ROW_W = LENS_NAMES.length * LENS_W + (LENS_NAMES.length - 1) * LENS_GAP;
const LENS_X0 = MID - LENS_ROW_W / 2;

function lensX(i: number) {
  return LENS_X0 + i * (LENS_W + LENS_GAP);
}

export const NODES: OrgNode[] = [
  {
    id: "forecast",
    label: "Forecast",
    sub: "EPS + a distribution",
    role: "deliverable",
    x: MID - 110,
    y: 62,
    w: 220,
    h: 56,
  },
  {
    id: "lambda",
    label: "λ Positioning",
    sub: "how far from consensus",
    role: "the decision",
    component: "lambda",
    liveId: "F_lambda",
    tier: "none",
    x: MID - 110,
    y: 156,
    w: 220,
    h: 58,
  },
  {
    id: "judge",
    label: "Judge",
    sub: "materiality, never votes",
    role: "verdict",
    component: "judge",
    liveId: "E_judge",
    tier: "deep",
    x: MID - 110,
    y: 252,
    w: 220,
    h: 58,
  },
  // Champions and lenses, seven columns.
  ...LENS_NAMES.map(([id], i) => ({
    id: `champion_${id}`,
    label: "Champion",
    sub: "argue, then attack",
    component: "champion",
    liveId: `D_${id}`,
    tier: "mid" as const,
    x: lensX(i),
    y: 356,
    w: LENS_W,
    h: 50,
  })),
  ...LENS_NAMES.map(([id, label, sub, tier], i) => ({
    id: `lens_${id}`,
    label,
    sub,
    role: "lens",
    component: id,
    liveId: `C_${id}`,
    tier: tier as OrgNode["tier"],
    x: lensX(i),
    y: 446,
    w: LENS_W,
    h: 56,
  })),
  {
    id: "evidence",
    label: "Evidence store",
    sub: "claims + verified quotes",
    role: "shared, cached corpus",
    component: "evidence",
    liveId: "B_structure",
    tier: "none",
    x: MID - 130,
    y: 556,
    w: 260,
    h: 58,
  },
  // Acquirers.
  ...[
    ["A1_numbers", "A1 Numbers", "XBRL · consensus", "acquire"],
    ["A2_filings", "A2 Filings", "8-K · 10-Q · text", "acquire"],
    ["A3_industry", "A3 Industry", "peers · value chain", "acquire"],
    ["A4_macro", "A4 Macro", "FRED, point-in-time", "acquire"],
  ].map(([liveId, label, sub], i) => ({
    id: liveId,
    label,
    sub,
    component: "acquire",
    liveId,
    tier: "none" as const,
    x: MID - 400 + i * 205,
    y: 656,
    w: 190,
    h: 52,
  })),
  // Sources.
  ...[
    ["sec", "SEC", "XBRL + filing text"],
    ["yfinance", "yfinance", "consensus, point-in-time"],
    ["universe", "Universe", "peers + drivers"],
    ["fred", "FRED", "macro via ALFRED"],
  ].map(([component, label, sub], i) => ({
    id: `src_${component}`,
    label,
    sub,
    component,
    role: "source",
    tier: "none" as const,
    x: MID - 400 + i * 205,
    y: 748,
    w: 190,
    h: 50,
  })),
  {
    id: "src_sponsor",
    label: "Sponsor feed",
    sub: "written on the day",
    component: "sponsor",
    role: "source",
    tier: "none",
    x: MID + 425,
    y: 748,
    w: 176,
    h: 50,
  },
  // Verification — beside the chain, not in it.
  {
    id: "v3",
    label: "V3 Calibrate",
    sub: "our own residuals",
    component: "v3",
    liveId: "V3_calibrate",
    audit: true,
    tier: "none",
    x: MID + 200,
    y: 156,
    w: 172,
    h: 58,
  },
  {
    id: "v2",
    label: "V2 Comparability",
    sub: "fires → λ collapses",
    component: "v2",
    liveId: "V2_comparability",
    audit: true,
    tier: "cheap",
    x: MID + 200,
    y: 252,
    w: 172,
    h: 58,
  },
  {
    id: "v1",
    label: "V1 Reconcile",
    sub: "arithmetic + citations",
    component: "v1",
    liveId: "V1_reconcile",
    audit: true,
    tier: "none",
    x: MID - 396,
    y: 446,
    w: 172,
    h: 56,
  },
  // Supporting functions.
  {
    id: "statements",
    label: "3-statement model",
    sub: "linked, balance-checked",
    component: "statements",
    audit: false,
    tier: "none",
    x: MID + 200,
    y: 556,
    w: 172,
    h: 58,
  },
  {
    id: "bridge",
    label: "GAAP ↔ non-GAAP",
    sub: "cited, verify() ties",
    component: "bridge",
    tier: "none",
    x: MID - 396,
    y: 556,
    w: 172,
    h: 58,
  },
  {
    id: "llm",
    label: "LLM client",
    sub: "schema-forced · cost ceiling",
    component: "llm",
    role: "infra",
    tier: "none",
    x: MID + 425,
    y: 356,
    w: 176,
    h: 50,
  },
  {
    id: "extract_guidance",
    label: "Guidance extractor",
    sub: "8-K → structured guide",
    component: "extract_guidance",
    tier: "cheap",
    x: MID + 425,
    y: 656,
    w: 176,
    h: 52,
  },
  {
    id: "eval",
    label: "Eval harness",
    sub: "cases · backtest · fit",
    component: "backtest",
    role: "wraps everything",
    tier: "none",
    x: MID - 616,
    y: 356,
    w: 176,
    h: 50,
  },
];

/** Solid = reports to. Dashed = audits / feeds sideways. */
const EDGES: Array<[string, string, "reports" | "audit"]> = [
  ["lambda", "forecast", "reports"],
  ["judge", "lambda", "reports"],
  ...LENS_NAMES.map(
    ([id]) => [`champion_${id}`, "judge", "reports"] as [string, string, "reports"],
  ),
  ...LENS_NAMES.map(
    ([id]) =>
      [`lens_${id}`, `champion_${id}`, "reports"] as [string, string, "reports"],
  ),
  ...LENS_NAMES.map(
    ([id]) => ["evidence", `lens_${id}`, "reports"] as [string, string, "reports"],
  ),
  ["A1_numbers", "evidence", "reports"],
  ["A2_filings", "evidence", "reports"],
  ["A3_industry", "evidence", "reports"],
  ["A4_macro", "evidence", "reports"],
  ["src_sec", "A1_numbers", "reports"],
  ["src_yfinance", "A1_numbers", "reports"],
  ["src_universe", "A3_industry", "reports"],
  ["src_fred", "A4_macro", "reports"],
  // audits and side functions
  ["v3", "lambda", "audit"],
  ["v2", "judge", "audit"],
  ["v1", "judge", "audit"],
  ["statements", "evidence", "audit"],
  ["bridge", "evidence", "audit"],
  ["extract_guidance", "evidence", "audit"],
];

const BUILD_FILL = {
  built: "var(--color-structure-soft)",
  partial: "var(--color-accent-soft)",
  missing: "var(--color-paper-2)",
  unknown: "var(--color-paper-2)",
} as const;

const BUILD_STROKE = {
  built: "var(--color-structure)",
  partial: "var(--color-accent)",
  missing: "var(--color-failed)",
  unknown: "var(--color-idle)",
} as const;

const LIVE_FILL = {
  idle: "var(--color-paper-2)",
  running: "var(--color-accent-soft)",
  done: "var(--color-structure-soft)",
  failed: "var(--color-accent-soft)",
} as const;

const LIVE_STROKE = {
  idle: "var(--color-idle)",
  running: "var(--color-accent)",
  done: "var(--color-structure)",
  failed: "var(--color-failed)",
} as const;

const TIER_FILL = {
  none: "var(--color-structure-soft)",
  cheap: "var(--color-paper-2)",
  mid: "var(--color-accent-soft)",
  deep: "var(--color-accent)",
} as const;

const TIER_STROKE = {
  none: "var(--color-structure)",
  cheap: "var(--color-idle)",
  mid: "var(--color-accent)",
  deep: "var(--color-accent-2)",
} as const;

export interface BuildComponent {
  id: string;
  state: string;
  label: string;
  detail?: string;
  tests?: number;
}

function edgePath(from: OrgNode, to: OrgNode, kind: "reports" | "audit"): string {
  if (kind === "audit") {
    // Sideways leader into the middle of the chain node.
    const fromRight = from.x + from.w / 2 < to.x + to.w / 2;
    const x1 = fromRight ? from.x + from.w : from.x;
    const y1 = from.y + from.h / 2;
    const x2 = fromRight ? to.x : to.x + to.w;
    const y2 = to.y + to.h / 2;
    return `M${x1},${y1} L${x2},${y2}`;
  }
  // Orthogonal reporting line: up out of `from`, across, down into `to`.
  const x1 = from.x + from.w / 2;
  const y1 = from.y;
  const x2 = to.x + to.w / 2;
  const y2 = to.y + to.h;
  const midY = y2 + (y1 - y2) / 2;
  return `M${x1},${y1} V${midY} H${x2} V${y2}`;
}

export default function OrgChart({
  overlay,
  build,
  live,
  onSelect,
  selected,
}: {
  overlay: Overlay;
  build: Record<string, BuildComponent>;
  live: Record<string, NodeStatus>;
  onSelect?: (node: OrgNode) => void;
  selected?: string | null;
}) {
  const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

  function paint(node: OrgNode): { fill: string; stroke: string; pulse: boolean } {
    if (overlay === "live") {
      const state = node.liveId ? (live[node.liveId]?.state ?? "idle") : "idle";
      return {
        fill: LIVE_FILL[state],
        stroke: LIVE_STROKE[state],
        pulse: state === "running",
      };
    }
    if (overlay === "tier") {
      const tier = node.tier ?? "none";
      return { fill: TIER_FILL[tier], stroke: TIER_STROKE[tier], pulse: false };
    }
    const state = (node.component ? build[node.component]?.state : undefined) as
      | keyof typeof BUILD_FILL
      | undefined;
    const key = state ?? "unknown";
    return { fill: BUILD_FILL[key], stroke: BUILD_STROKE[key], pulse: false };
  }

  return (
    <div className="scroll-x">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[1100px]">
        <defs>
          <marker
            id="org-arrow"
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

        {/* Row labels down the left edge — the layer each rank belongs to. */}
        {[
          ["G  OUTPUT", 90],
          ["F  POSITION", 185],
          ["E  JUDGE", 281],
          ["D  CHALLENGE", 381],
          ["C  ANALYSE", 474],
          ["B  STRUCTURE", 585],
          ["A  ACQUIRE", 682],
          ["   SOURCES", 773],
        ].map(([label, y]) => (
          <text
            key={label as string}
            x={14}
            y={y as number}
            className="fill-ink-3"
            style={{
              fontSize: 9.5,
              fontWeight: 700,
              letterSpacing: "0.12em",
              fontFamily: "var(--font-mono)",
            }}
          >
            {label}
          </text>
        ))}

        {EDGES.map(([a, b, kind]) => {
          const from = byId[a];
          const to = byId[b];
          if (!from || !to) return null;
          const active =
            overlay === "live" &&
            from.liveId &&
            live[from.liveId]?.state === "done";
          return (
            <path
              key={`${a}->${b}`}
              d={edgePath(from, to, kind)}
              fill="none"
              stroke={
                active ? "var(--color-structure)" : "var(--color-ink-3)"
              }
              strokeWidth={kind === "audit" ? 0.9 : active ? 1.5 : 1.1}
              strokeDasharray={kind === "audit" ? "4 4" : undefined}
              opacity={kind === "audit" ? 0.42 : active ? 0.8 : 0.5}
              markerEnd={kind === "reports" ? "url(#org-arrow)" : undefined}
              className="state-change"
            />
          );
        })}

        {NODES.map((node) => {
          const { fill, stroke, pulse } = paint(node);
          const component = node.component ? build[node.component] : undefined;
          const isSelected = selected === node.id;
          return (
            <g
              key={node.id}
              className={pulse ? "node-running" : undefined}
              onClick={() => onSelect?.(node)}
              style={{ cursor: onSelect ? "pointer" : undefined }}
            >
              <rect
                x={node.x}
                y={node.y}
                width={node.w}
                height={node.h}
                fill={fill}
                stroke={isSelected ? "var(--color-ink)" : stroke}
                strokeWidth={isSelected ? 2.4 : 1.6}
                strokeDasharray={node.audit ? "5 3" : undefined}
                className="state-change"
              />
              <text
                x={node.x + node.w / 2}
                y={node.y + (node.sub ? node.h / 2 - 1 : node.h / 2 + 4)}
                textAnchor="middle"
                className={
                  overlay === "tier" && node.tier === "deep"
                    ? "display fill-paper"
                    : "display fill-ink"
                }
                style={{ fontSize: 12.5 }}
              >
                {node.label}
              </text>
              {node.sub && (
                <text
                  x={node.x + node.w / 2}
                  y={node.y + node.h / 2 + 13}
                  textAnchor="middle"
                  className={
                    overlay === "tier" && node.tier === "deep"
                      ? "fill-paper"
                      : "fill-ink-2"
                  }
                  style={{ fontSize: 9 }}
                >
                  {node.sub}
                </text>
              )}

              {/* Build overlay: a test-count badge, because "it imports" is a
                  much weaker claim than "a test encodes how it fails". */}
              {overlay === "build" && component && (
                <text
                  x={node.x + node.w - 6}
                  y={node.y + 12}
                  textAnchor="end"
                  className={
                    component.state === "built" ? "fill-structure" : "fill-accent"
                  }
                  style={{ fontSize: 8.5, fontWeight: 700 }}
                >
                  {component.state === "built"
                    ? `${component.tests ?? 0} tests`
                    : component.state === "partial"
                      ? "untested"
                      : "missing"}
                </text>
              )}

              {overlay === "live" &&
                node.liveId &&
                live[node.liveId]?.latencyMs !== undefined &&
                (live[node.liveId]!.latencyMs ?? 0) > 0 && (
                  <text
                    x={node.x + node.w - 6}
                    y={node.y + 12}
                    textAnchor="end"
                    className="num fill-ink-3"
                    style={{ fontSize: 8.5 }}
                  >
                    {(live[node.liveId]!.latencyMs ?? 0) >= 1000
                      ? `${((live[node.liveId]!.latencyMs ?? 0) / 1000).toFixed(1)}s`
                      : `${live[node.liveId]!.latencyMs}ms`}
                  </text>
                )}

              {overlay === "tier" && node.tier && node.tier !== "none" && (
                <text
                  x={node.x + 6}
                  y={node.y + 12}
                  className={
                    node.tier === "deep" ? "fill-paper" : "fill-ink-3"
                  }
                  style={{ fontSize: 8.5, fontWeight: 700 }}
                >
                  {node.tier.toUpperCase()}
                </text>
              )}
              {overlay === "tier" && node.tier === "none" && node.component && (
                <text
                  x={node.x + 6}
                  y={node.y + 12}
                  className="fill-structure"
                  style={{ fontSize: 8.5, fontWeight: 700 }}
                >
                  NO MODEL
                </text>
              )}
            </g>
          );
        })}

        {/* The structural point the layout exists to make. */}
        <text
          x={MID}
          y={524}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 9.5 }}
        >
          seven siblings, no peer links — the lenses are blind to each other by design
        </text>
        <text
          x={MID + 286}
          y={332}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 9 }}
        >
          dashed = audits the chain, contributes no estimate
        </text>
        <text
          x={MID}
          y={840}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 9.5 }}
        >
          every acquirer has a ranked target list and a hard budget, and logs what
          it skipped
        </text>
      </svg>
    </div>
  );
}
