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
 *
 * And running underneath all three overlays, always on: WHICH OF THESE ARE
 * AGENTS. Drawn as identical boxes the chart implied that everything here
 * reasons with a model, which flatters it and is false. Ten of these are agents;
 * the rest is deterministic code and data plumbing. That split is the load-
 * bearing claim of the architecture — every stage that can hallucinate is
 * checked by one that cannot — so it is encoded in the boxes themselves rather
 * than left to an overlay the judge might not click.
 */

/**
 * An `agent` is defined here exactly as it is defined in the repo: a component
 * with a versioned prompt in `llm/prompts/*.yaml`. That is checkable rather than
 * asserted, and `AGENT_ROLES` below must equal that file count.
 */
export type Kind = "agent" | "code" | "data" | "output";

export type Overlay = "build" | "live" | "tier";

export interface OrgNode {
  id: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  kind: Kind;
  /** Component id in build.json, when one exists. */
  component?: string;
  /** Event-log node id, when one exists. */
  liveId?: string;
  tier?: "none" | "cheap" | "mid" | "deep";
  /** Verification layers are drawn as an independent function, not a step. */
  audit?: boolean;
  role?: string;
  /** Built and tested, but `run.py` never calls it. Shown, not hidden. */
  unwired?: boolean;
}

const W = 1520;
// Raised from 900 when acquisition grew from four boxes to six plus the
// dossier: the sources row had been sitting on the frame's edge.
const H = 1000;
const MID = W / 2;

// The two widest rows, spread evenly about the midline. Computed rather than
// hand-placed, because the row widths change whenever a source or an acquirer is
// added and hand-tuned x offsets are how a diagram silently stops matching the
// system it describes.
//
// The widths are not arbitrary: the rank labels run down the left edge from
// x=14, so a row reaching past x≈100 would put a box on top of the word SOURCES.
// Both rows are sized to stop at 101 or later.
const rowX = (n: number, w: number, gap: number, i: number) =>
  MID - (n * w + (n - 1) * gap) / 2 + i * (w + gap);

const ACQUIRE_W = 206;
const ACQUIRE_X = (i: number) => rowX(6, ACQUIRE_W, 14, i);
const SOURCE_W = 178;
const SOURCE_X = (i: number) => rowX(7, SOURCE_W, 12, i);

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
    kind: "output",
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
    liveId: "H_lambda",
    // The most consequential decision in the system, and there is no model in
    // it: arithmetic on a coefficient fitted by the backtest.
    kind: "code",
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
    liveId: "G_judge",
    kind: "agent",
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
    liveId: `F_${id}`,
    kind: "agent" as const,
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
    liveId: `E_${id}`,
    // Mechanical is the one lens with no prompt file, so it is code, not an
    // agent. Deriving the kind from the tier keeps the two from drifting apart.
    kind: (tier === "none" ? "code" : "agent") as Kind,
    tier: tier as OrgNode["tier"],
    x: lensX(i),
    y: 446,
    w: LENS_W,
    h: 56,
  })),
  // Stage D. Deterministic, and deliberately BELOW the lenses in the chain
  // rather than above the judge: only the projection needs a revenue view, and
  // the historical statements, the ratio base and the model's own measured
  // error are arithmetic on filings. Every lens argues with this dict.
  {
    id: "model",
    label: "3-statement model",
    sub: "ratio base · reproduces past quarters",
    role: "measured, not asserted",
    component: "model",
    liveId: "D_model",
    kind: "code",
    tier: "none",
    x: MID - 170,
    y: 526,
    w: 340,
    h: 58,
  },
  {
    id: "evidence",
    label: "Evidence store",
    sub: "claims + verified quotes",
    role: "shared, cached corpus",
    component: "evidence",
    liveId: "C_structure",
    kind: "code",
    tier: "none",
    x: MID - 130,
    y: 608,
    w: 260,
    h: 58,
  },
  // Acquirers. Six now, not four: A1b carries the quarterly series and the
  // price history the three-statement model rolls forward from, and B5 lifts
  // guidance out of the earnings release into citable claims.
  // Five of the six are pure retrieval and cost nothing but time. B5 is the one
  // model call in this stage, and it is on the cheap tier — reading a guide out
  // of a press release the company wrote is not a judgement call.
  ...[
    ["B1_numbers", "B1 Numbers", "XBRL · consensus", "acquire", "none"],
    ["B1b_series", "B1b Series", "74 quarters · daily bars", "acquire", "none"],
    ["B2_filings", "B2 Filings", "8-K item 2.02 · EX-99 text", "acquire", "none"],
    ["B3_industry", "B3 Industry", "peers by SIC · news", "acquire", "none"],
    ["B4_macro", "B4 Macro", "FRED, point-in-time", "acquire", "none"],
    ["B5_extract", "B5 Extract", "guidance → cited claims", "extract_guidance", "cheap"],
  ].map(([liveId, label, sub, component, tier], i) => ({
    id: liveId,
    label,
    sub,
    component,
    liveId,
    kind: (tier === "none" ? "data" : "agent") as "data" | "agent",
    tier: tier as "none" | "cheap",
    x: ACQUIRE_X(i),
    y: 708,
    w: ACQUIRE_W,
    h: 52,
  })),
  // The dossier. Acquisition's output is an artifact on disk, which is what
  // lets stage 3 run without the network — acquire once, iterate prompts.
  {
    id: "dossier",
    label: "Dossier",
    sub: "out/acquired/<ticker>/<period>_<as_of>",
    role: "acquire writes, analysis reads",
    component: "dossier",
    kind: "data",
    tier: "none",
    x: MID - 200,
    y: 778,
    w: 400,
    h: 46,
  },
  // Sources. Stage 1: where the data lives, distinct from stage 2 which goes
  // and gets it. The sponsor feed sits in this row rather than off to one side
  // because on the day it is a source like any other — the only one whose
  // adapter is written in the room.
  //
  // Universe is the odd one: a local file, not a fetch. It stays in the row
  // anyway because acquisition genuinely reads peers, driver text and macro
  // series ids out of it, and a chart that omits it cannot answer "where did
  // this company's driver decomposition come from".
  ...[
    ["sec", "SEC", "XBRL · filings · SIC peers"],
    ["yfinance", "yfinance", "consensus · prices · shares"],
    ["exa", "Exa", "news, date-bounded"],
    ["lse", "LSE", "options chain · implied move"],
    ["fred", "FRED", "macro via ALFRED"],
    ["universe", "Universe", "prepared, local · warm start"],
    ["sponsor", "Sponsor feed", "written on the day"],
  ].map(([component, label, sub], i) => ({
    id: `src_${component}`,
    label,
    sub,
    component,
    role: "source",
    kind: "data" as const,
    tier: "none" as const,
    x: SOURCE_X(i),
    y: 858,
    w: SOURCE_W,
    h: 50,
  })),
  // Verification — beside the chain, not in it. Two of the three are pure code,
  // deliberately: the thing checking the agents must not itself be able to
  // hallucinate.
  {
    id: "v3",
    label: "V3 Calibrate",
    sub: "our own residuals",
    component: "v3",
    liveId: "V3_calibrate",
    audit: true,
    kind: "code",
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
    // The only audit layer that is an agent, because the question — is this
    // quarter comparable to the company's own history — needs reading prose.
    kind: "agent",
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
    kind: "code",
    tier: "none",
    x: MID - 396,
    y: 446,
    w: 172,
    h: 56,
  },
  // Supporting functions.
  //
  // `statements` used to sit here as a floating box with an edge into the
  // evidence store and no `unwired` mark — which claimed a connection that did
  // not exist, since nothing in `run.py` called it. It is stage D now, in the
  // chain, so the duplicate is gone rather than relabelled.
  {
    id: "bridge",
    label: "GAAP ↔ non-GAAP",
    sub: "cited, verify() ties",
    component: "bridge",
    kind: "code",
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
    // It calls the models; it is not one. Schema forcing, retries, cost ceiling.
    kind: "code",
    tier: "none",
    x: MID + 425,
    y: 356,
    w: 176,
    h: 50,
  },
  // The guidance extractor used to stand off to one side marked `unwired` —
  // built, tested, and never called. It is now B5 in the acquirer row, where a
  // step `run.py` actually executes belongs.
  {
    id: "eval",
    label: "Eval harness",
    sub: "cases · backtest · fit",
    component: "backtest",
    role: "wraps everything",
    kind: "code",
    tier: "none",
    x: MID - 616,
    y: 356,
    w: 176,
    h: 50,
  },
];

/**
 * Distinct COMPONENTS of each kind, not boxes — and all three counted the same
 * way, because a legend that reports roles for one kind and boxes for another is
 * worse than no legend. The seven champion columns are seven parallel calls of
 * one prompt, so they count once; likewise the four acquirer boxes are one
 * `acquire` component.
 *
 * The consequence worth checking: `KIND_COUNTS.agent` must equal the file count
 * of `llm/prompts/*.yaml`. Add a prompt without a box, or a box without a
 * prompt, and the two disagree.
 */
const distinct = (kind: Kind) =>
  new Set(
    NODES.filter((n) => n.kind === kind).map((n) => n.component ?? n.id),
  ).size;

export const KIND_COUNTS = {
  agent: distinct("agent"),
  code: distinct("code"),
  data: distinct("data"),
};

export const AGENT_ROLES = KIND_COUNTS.agent;

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
    // Through the model, not around it. Every lens sees the same ratio base and
    // the same measured error, so their disagreement is about judgment rather
    // than partly an artefact of having been given different arithmetic.
    ([id]) => ["model", `lens_${id}`, "reports"] as [string, string, "reports"],
  ),
  // Acquisition no longer hands the corpus straight up the chain — it writes
  // the dossier, and the evidence store is built from that. This is the edge
  // that makes stage 3 runnable on its own.
  ["B1_numbers", "dossier", "reports"],
  ["B1b_series", "dossier", "reports"],
  ["B2_filings", "dossier", "reports"],
  ["B3_industry", "dossier", "reports"],
  ["B4_macro", "dossier", "reports"],
  ["B5_extract", "dossier", "reports"],
  ["dossier", "evidence", "reports"],
  ["evidence", "model", "reports"],
  ["src_sec", "B1_numbers", "reports"],
  ["src_sec", "B1b_series", "reports"],
  ["src_sec", "B2_filings", "reports"],
  ["src_yfinance", "B1_numbers", "reports"],
  ["src_yfinance", "B1b_series", "reports"],
  ["src_exa", "B3_industry", "reports"],
  ["src_lse", "B3_industry", "reports"],
  ["src_fred", "B4_macro", "reports"],
  ["src_universe", "B3_industry", "reports"],
  ["src_universe", "B4_macro", "reports"],
  ["src_sponsor", "B1_numbers", "reports"],
  // audits and side functions
  ["v3", "lambda", "audit"],
  ["v2", "judge", "audit"],
  ["v1", "judge", "audit"],
  ["bridge", "evidence", "audit"],
  ["llm", "B5_extract", "audit"],
];

/* The state palettes are exported because the schematic view paints from the same
   three overlays. Two components inventing their own greens is how a legend ends
   up describing a colour that appears nowhere. */
export const BUILD_FILL = {
  built: "var(--color-structure-soft)",
  partial: "var(--color-accent-soft)",
  missing: "var(--color-paper-2)",
  unknown: "var(--color-paper-2)",
} as const;

export const BUILD_STROKE = {
  built: "var(--color-structure)",
  partial: "var(--color-accent)",
  missing: "var(--color-failed)",
  unknown: "var(--color-idle)",
} as const;

export const LIVE_FILL = {
  idle: "var(--color-paper-2)",
  running: "var(--color-accent-soft)",
  done: "var(--color-structure-soft)",
  failed: "var(--color-accent-soft)",
} as const;

export const LIVE_STROKE = {
  idle: "var(--color-idle)",
  running: "var(--color-accent)",
  done: "var(--color-structure)",
  failed: "var(--color-failed)",
} as const;

export const TIER_FILL = {
  none: "var(--color-structure-soft)",
  cheap: "var(--color-paper-2)",
  mid: "var(--color-accent-soft)",
  deep: "var(--color-accent)",
} as const;

export const TIER_STROKE = {
  none: "var(--color-structure)",
  cheap: "var(--color-idle)",
  mid: "var(--color-accent)",
  deep: "var(--color-accent-2)",
} as const;

/** The agent's left-edge tab, coloured by what the call costs. */
export const TAB = {
  none: "var(--color-ink-3)",
  cheap: "var(--color-accent-2)",
  mid: "var(--color-accent)",
  deep: "var(--color-deep)",
} as const;

/**
 * Rule 1 of the design language, as code: a part's outline says what KIND of
 * thing it is. Everything else — build state, live state, cost tier — is layered
 * on top of this, never in place of it, so the one distinction that matters is
 * legible on every overlay and at every zoom.
 */
export const KIND_STROKE = {
  agent: "var(--color-accent)",
  code: "var(--color-structure)",
  data: "var(--color-data)",
  output: "var(--color-ink)",
} as const;

export const KIND_FILL = {
  agent: "var(--color-accent-soft)",
  code: "var(--color-structure-soft)",
  data: "var(--color-data-soft)",
  output: "var(--color-paper-2)",
} as const;

/** The judge is the one deep-tier call, and it gets its own hue to say so. */
export const strokeFor = (kind: Kind, tier?: OrgNode["tier"]) =>
  kind === "agent" && tier === "deep" ? "var(--color-deep)" : KIND_STROKE[kind];

export const fillFor = (kind: Kind, tier?: OrgNode["tier"]) =>
  kind === "agent" && tier === "deep" ? "var(--color-deep-soft)" : KIND_FILL[kind];

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

          {/* Machined diagonal hatch — the drafting convention for a solid
              part, used here for everything deterministic. Nothing with a model
              in it is ever hatched. */}
          <pattern
            id="org-hatch"
            width="5"
            height="5"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="5"
              stroke="var(--color-ink-3)"
              strokeWidth="1"
            />
          </pattern>
        </defs>

        {/* Row labels down the left edge — the layer each rank belongs to. */}
        {[
          ["I  OUTPUT", 90],
          ["H  POSITION", 185],
          ["G  JUDGE", 281],
          ["F  CHALLENGE", 381],
          ["E  ANALYSE", 474],
          ["D  MODEL", 555],
          ["C  STRUCTURE", 637],
          ["B  ACQUIRE", 734],
          ["   DOSSIER", 801],
          ["A  SOURCES", 883],
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
                // Data plumbing gets a lighter rule than anything that makes a
                // judgment. Weight of line = weight of responsibility.
                strokeWidth={isSelected ? 2.4 : node.kind === "data" ? 1 : 1.6}
                strokeDasharray={node.audit ? "5 3" : undefined}
                className="state-change"
              />

              {node.kind === "code" && (
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.w}
                  height={node.h}
                  fill="url(#org-hatch)"
                  opacity={0.16}
                  pointerEvents="none"
                />
              )}

              {/* AGENT: a solid tab on the left edge plus a doubled inner rule.
                  Two cues rather than one, because colour alone fails in
                  greyscale and on a projector at the back of a room. */}
              {node.kind === "agent" && (
                <>
                  <rect
                    x={node.x}
                    y={node.y}
                    width={4}
                    height={node.h}
                    fill={TAB[node.tier ?? "mid"]}
                    pointerEvents="none"
                  />
                  <rect
                    x={node.x + 3.5}
                    y={node.y + 3.5}
                    width={node.w - 7}
                    height={node.h - 7}
                    fill="none"
                    stroke="var(--color-accent)"
                    strokeWidth={0.6}
                    opacity={0.45}
                    pointerEvents="none"
                  />
                </>
              )}

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

              {/* Agents carry their tier in the corner on every overlay, not
                  just the tier one — the cost story should be legible without
                  having to go looking for it. */}
              {node.kind === "agent" && node.tier && (
                <text
                  x={node.x + 9}
                  y={node.y + 12}
                  className={
                    overlay === "tier" && node.tier === "deep"
                      ? "fill-paper"
                      : "fill-ink-3"
                  }
                  style={{ fontSize: 8.5, fontWeight: 700 }}
                >
                  {node.tier.toUpperCase()}
                </text>
              )}
              {overlay === "tier" && node.kind === "code" && node.component && (
                <text
                  x={node.x + 6}
                  y={node.y + 12}
                  className="fill-structure"
                  style={{ fontSize: 8.5, fontWeight: 700 }}
                >
                  NO MODEL
                </text>
              )}

              {/* Built, tested, and never called. Saying so on the chart is the
                  whole reason the chart is worth drawing. */}
              {node.unwired && (
                <text
                  x={node.x + node.w / 2}
                  y={node.y + node.h + 11}
                  textAnchor="middle"
                  className="fill-accent"
                  style={{ fontSize: 8, fontWeight: 700, letterSpacing: "0.08em" }}
                >
                  NOT WIRED INTO run.py
                </text>
              )}
            </g>
          );
        })}

        {/* Names the kinds. Without this the encoding is decoration; with it,
            the best property of the architecture reads at a glance. */}
        <g transform="translate(14, 24)">
          <rect
            x={0}
            y={-13}
            width={4}
            height={13}
            fill="var(--color-accent)"
          />
          <rect
            x={0}
            y={-13}
            width={26}
            height={13}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={1.4}
          />
          <text x={32} y={-3} className="fill-ink" style={{ fontSize: 9 }}>
            <tspan style={{ fontWeight: 700 }}>{AGENT_ROLES} agents</tspan>
            <tspan className="fill-ink-2"> — reason with a model</tspan>
          </text>

          <rect
            x={182}
            y={-13}
            width={26}
            height={13}
            fill="url(#org-hatch)"
            opacity={0.3}
          />
          <rect
            x={182}
            y={-13}
            width={26}
            height={13}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={1.4}
          />
          <text x={214} y={-3} className="fill-ink" style={{ fontSize: 9 }}>
            <tspan style={{ fontWeight: 700 }}>{KIND_COUNTS.code} code</tspan>
            <tspan className="fill-ink-2"> — deterministic, cannot hallucinate</tspan>
          </text>

          <text x={32} y={11} className="fill-ink-3" style={{ fontSize: 8 }}>
            counts are distinct components, not boxes — the champion column is one
            prompt run seven times, and the four acquirers are one component
          </text>

          <rect
            x={452}
            y={-13}
            width={26}
            height={13}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={0.9}
          />
          <text x={484} y={-3} className="fill-ink" style={{ fontSize: 9 }}>
            <tspan style={{ fontWeight: 700 }}>{KIND_COUNTS.data} data</tspan>
            <tspan className="fill-ink-2"> — fetch and stage, make no judgment</tspan>
          </text>

        </g>

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
