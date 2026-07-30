"use client";

import {
  BUILD_FILL,
  BUILD_STROKE,
  LIVE_FILL,
  LIVE_STROKE,
  TAB,
  TIER_FILL,
  TIER_STROKE,
  type BuildComponent,
  type Kind,
  type OrgNode,
  type Overlay,
} from "@/components/OrgChart";
import type { NodeStatus, RunResult } from "@/lib/data";

/**
 * THE SYSTEM AS A SIGNAL-FLOW SCHEMATIC.
 *
 * An org chart answers "who reports to whom", which is the wrong question about
 * this system — nothing here reports to anything, evidence flows through it. So
 * this is drawn to the conventions of a circuit schematic instead, and those
 * conventions map onto the architecture almost exactly:
 *
 *   parts        Each stage is an IC: pin stubs, a designator above it. Agents
 *                keep the orange tab, deterministic code the machined hatch,
 *                data fetchers the light rule. Same encoding as everywhere else.
 *
 *   conductors   Wire width carries live claim volume. A lens that cited forty
 *                claims is visibly a fatter conductor than one standing on four,
 *                and the marching dashes travel the way the data travels.
 *
 *   open         A dropped lens is an open circuit — the trunk goes thin, dashed
 *   circuit      and gets a break marker. Not a red box off to one side: the
 *                signal visibly does not arrive, which is what dropping means.
 *
 *   in-line      V1 is a SERIES element. Every lens output passes through it and
 *   vs gate      it can break the connection. V2 and V3 are CONTROL lines into
 *                the parts they modulate — V2 collapses λ, V3 sets the interval
 *                width and nothing else. A component in the signal path and one
 *                that modulates it are different things, and the architecture
 *                makes exactly that distinction.
 *
 *   λ as a       forecast = consensus + λ · (own − consensus) is literally a
 *   mixer        crossfade between two inputs, so λ is drawn as one: a track with
 *                a wiper, consensus at one end and our own estimate at the other,
 *                the wiper sitting at the fitted λ. You can read our distance
 *                from the Street straight off the slider.
 *
 *   consensus    And the thing an org chart cannot show at all: consensus enters
 *   bus          at A1 and runs along the bottom of the sheet, past every stage,
 *                untouched, into λ's second input. That rail IS the thesis. Seven
 *                lenses, a champion round and one expensive judge all exist to
 *                earn the right to move the wiper off it.
 */

interface Part extends OrgNode {
  /** Schematic designator, drawn above the part as on a real sheet. */
  ref: string;
  /** Pin stubs per side. The reconciler has seven; most parts have two or three. */
  stubs: number;
  /** Terminals have pins on one side only. */
  sides?: "both" | "out" | "in";
  /** A footprint with no part fitted: built but not in the circuit. */
  ghost?: boolean;
}

const W = 1740;
const H = 992;

/* The lens rank is the spine of the drawing; everything else centres on it. */
const LY0 = 226;
const LH = 52;
const LPITCH = 68;
const lensY = (i: number) => LY0 + i * LPITCH;
const LENS_BOTTOM = lensY(6) + LH;
const SPINE = (LY0 + LENS_BOTTOM) / 2;

/* Column origins. Buses run in the gutters between them. */
const X = {
  src: 28,
  a: 214,
  b: 414,
  c: 646,
  v1: 872,
  d: 966,
  e: 1166,
  f: 1370,
  g: 1576,
} as const;

/**
 * Bus lanes, all in the gutters between columns.
 *
 * These are hand-picked rather than derived, and every one of them was moved at
 * least once: the first routing put the consensus rail straight through the A2,
 * A3 and A4 packages, and V2's control line through V3. A schematic where a
 * conductor crosses a part is not a stylistic problem — it is unreadable, since
 * you cannot tell a crossing from a connection. Crossings between conductors are
 * fine and expected, which is exactly why junction dots exist.
 */
const BUS = {
  src: 170, // sources fan into the acquirers
  railDown: 196, // the consensus rail drops down this gutter, left of column A
  a: 380, // acquirers merge into the evidence store
  extract: 362, // the extractor's own feed, inboard of the merge bus
  b: 602, // the store fans out to the lenses
  v1: 942, // reconciled outputs collect into the champion
  rail: 852, // the consensus bus, along the bottom of the sheet
  lamIn: 1322, // where the rail turns up into λ's second input
  eJog: 1348, // where the judge's output steps into λ's first input
  v2Lane: 560, // V2's control line runs along here, clear of V3
  v2Ctl: 1400, // and turns up into λ's underside
  v3Ctl: 1602, // V3's control line turns up into the output
} as const;

export const LENSES = [
  ["mechanical", "Mechanical", "FX · shares · interest", "none"],
  ["guidance", "Guidance", "guide + landing CDF", "mid"],
  ["drivers", "Drivers", "units × ASP", "mid"],
  ["margins", "Margins", "GM mix · opex · tax", "mid"],
  ["forensics", "Forensics", "accruals · exclusions", "mid"],
  ["peer_read", "Peer read", "who already reported", "mid"],
  ["macro", "Macro", "series vs assumed", "mid"],
] as const;

export const PARTS: Part[] = [
  // ---- sources: terminals, not components -------------------------------- //
  ...(
    [
      ["sec", "SEC", "XBRL + filing text", 262],
      ["yfinance", "yfinance", "consensus, point-in-time", 336],
      ["universe", "Universe", "peers + value chain", 440],
      ["fred", "FRED", "macro via ALFRED", 524],
    ] as const
  ).map(([component, label, sub, y], i) => ({
    id: `src_${component}`,
    ref: `J${i + 1}`,
    label,
    sub,
    component,
    role: "source",
    kind: "data" as const,
    tier: "none" as const,
    stubs: 1,
    sides: "out" as const,
    x: X.src,
    y,
    w: 108,
    h: 44,
  })),
  {
    id: "src_sponsor",
    ref: "J5",
    label: "Sponsor feed",
    sub: "one adapter, written on the day",
    component: "sponsor",
    role: "source",
    kind: "data",
    tier: "none",
    ghost: true,
    stubs: 1,
    sides: "out",
    x: X.src,
    y: 612,
    w: 108,
    h: 44,
  },

  // ---- A: acquire --------------------------------------------------------- //
  ...(
    [
      ["A1_numbers", "A1 Numbers", "XBRL · consensus", 286],
      ["A2_filings", "A2 Filings", "8-K · 10-Q · body text", 360],
      ["A3_industry", "A3 Industry", "peers, 100-day window", 440],
      ["A4_macro", "A4 Macro", "realtime_start pinned", 524],
    ] as const
  ).map(([id, label, sub, y], i) => ({
    id,
    ref: `U${i + 1}`,
    label,
    sub,
    component: "acquire",
    liveId: id,
    kind: "data" as const,
    tier: "none" as const,
    stubs: 2,
    x: X.a,
    y,
    w: 128,
    h: 50,
  })),

  // ---- B: structure ------------------------------------------------------- //
  {
    id: "B_structure",
    ref: "U5",
    label: "Evidence store",
    sub: "one byte-identical corpus",
    role: "shared, cached, keyed on input hash",
    component: "evidence",
    liveId: "B_structure",
    kind: "code",
    tier: "none",
    stubs: 3,
    x: X.b,
    y: SPINE - 38,
    w: 140,
    h: 76,
  },
  {
    id: "B_extract",
    ref: "U6",
    label: "Guidance extract",
    sub: "8-K prose → structured guide",
    component: "extract_guidance",
    kind: "agent",
    tier: "cheap",
    unwired: true,
    ghost: true,
    stubs: 2,
    x: X.b,
    y: 552,
    w: 140,
    h: 48,
  },

  // ---- C: seven lenses, and no nets between them --------------------------- //
  ...LENSES.map(([id, label, sub, tier], i) => ({
    id: `C_${id}`,
    ref: `U${7 + i}`,
    label,
    sub,
    role: "lens",
    component: id,
    liveId: `C_${id}`,
    kind: (tier === "none" ? "code" : "agent") as Kind,
    tier,
    stubs: 2,
    x: X.c,
    y: lensY(i),
    w: 178,
    h: LH,
  })),

  // ---- V1: a series element, inside the signal path ------------------------ //
  {
    id: "V1_reconcile",
    ref: "U14",
    label: "V1",
    sub: "recompute · string-match",
    role: "in-line — breaks the net on failure",
    component: "v1",
    liveId: "V1_reconcile",
    kind: "code",
    tier: "none",
    audit: true,
    stubs: 7,
    x: X.v1,
    y: LY0,
    w: 50,
    h: LENS_BOTTOM - LY0,
  },

  // ---- D, E ---------------------------------------------------------------- //
  {
    id: "D_champion",
    ref: "U15",
    label: "Champion",
    sub: "argue, then attack",
    role: "×7 — one prompt, seven parallel calls",
    component: "champion",
    liveId: "D_champion",
    kind: "agent",
    tier: "mid",
    stubs: 3,
    x: X.d,
    y: SPINE - 40,
    w: 134,
    h: 80,
  },
  {
    id: "E_judge",
    ref: "U16",
    label: "Judge",
    sub: "materiality, never votes",
    role: "one expensive call, highest leverage",
    component: "judge",
    liveId: "E_judge",
    kind: "agent",
    tier: "deep",
    stubs: 3,
    x: X.e,
    y: SPINE - 40,
    w: 138,
    h: 80,
  },

  // ---- V2, V3: control lines, not series elements --------------------------- //
  {
    id: "V2_comparability",
    ref: "U17",
    label: "V2 Comparability",
    sub: "M&A · accounting · 53rd week",
    role: "gate — when it fires, λ collapses",
    component: "v2",
    liveId: "V2_comparability",
    kind: "agent",
    tier: "cheap",
    audit: true,
    stubs: 2,
    x: X.e,
    y: 704,
    w: 138,
    h: 48,
  },
  {
    id: "V3_calibrate",
    ref: "U18",
    label: "V3 Calibrate",
    sub: "bootstrapped own residuals",
    role: "gate — sets the interval width, nothing else",
    component: "v3",
    liveId: "V3_calibrate",
    kind: "code",
    tier: "none",
    audit: true,
    stubs: 2,
    x: X.f,
    y: 704,
    w: 150,
    h: 48,
  },

  // ---- F: the mixer -------------------------------------------------------- //
  {
    id: "F_lambda",
    ref: "U19",
    label: "λ",
    sub: "fitted, regime-conditioned",
    role: "crossfade: consensus ↔ our own estimate",
    component: "lambda",
    liveId: "F_lambda",
    kind: "code",
    tier: "none",
    stubs: 2,
    x: X.f,
    y: SPINE - 54,
    w: 150,
    h: 108,
  },

  // ---- the baseline, tapped off the consensus rail -------------------------- //
  {
    id: "baseline",
    ref: "U20",
    label: "Baseline",
    sub: "consensus × (1 + shrunk surprise)",
    role: "the bar to beat — on every chart, by rule",
    component: "backtest",
    kind: "code",
    tier: "none",
    stubs: 2,
    x: X.d,
    y: BUS.rail - 22,
    w: 134,
    h: 44,
  },

  // ---- G ------------------------------------------------------------------- //
  {
    id: "G_output",
    ref: "OUT",
    label: "Forecast",
    sub: "point + full quantiles",
    role: "out/results.json — the only interface to any screen",
    kind: "output",
    stubs: 1,
    sides: "in",
    x: X.g,
    y: SPINE - 38,
    w: 130,
    h: 76,
  },
];

const BY_ID: Record<string, Part> = Object.fromEntries(
  PARTS.map((p) => [p.id, p]),
);

/* ------------------------------------------------------------------------- *
 * Routing. Orthogonal, sharp corners, no diagonals — schematic convention,
 * and it also makes a bus merge legible in a way a bundle of curves is not.
 * ------------------------------------------------------------------------- */

const cy = (p: Part) => p.y + p.h / 2;
const right = (p: Part) => p.x + p.w;

/** Right edge of `a` → bus x → level of `b` → left edge of `b`. */
const hvh = (a: Part, b: Part, busX: number, bY = cy(b), aY = cy(a)) =>
  `M${right(a)},${aY} H${busX} V${bY} H${b.x}`;

type NetKind = "signal" | "control" | "reference" | "rail";

interface Net {
  id: string;
  d: string;
  kind: NetKind;
  /** Part whose completion energises this net. */
  from?: string;
  /** Part this net feeds; running there means the net is carrying now. */
  to?: string;
  /** Claims on the wire. Drives conductor width. */
  volume?: number;
  /** Open circuit — the lens was dropped, so nothing arrives. */
  open?: boolean;
  /** Where to stamp the break marker on an open net. */
  mark?: [number, number];
}

interface Junction {
  x: number;
  y: number;
}

/**
 * The nets, widths and all. Built from the result file rather than declared, so
 * the drawing is a readout and not an illustration of one.
 */
function buildNets(result: RunResult | null) {
  const forecast = result?.forecast;
  const claims = new Map<string, number>(
    (forecast?.lenses ?? []).map((l) => [l.lens, l.claim_ids.length]),
  );
  const dropped = forecast?.dropped_lenses ?? {};
  const maxVolume = Math.max(1, ...claims.values());
  const totalKept = [...claims.values()].reduce((a, b) => a + b, 0);

  const nets: Net[] = [];
  const junctions: Junction[] = [];

  // sources → acquirers. SEC feeds two: the numbers and the filing body text.
  for (const [a, b] of [
    ["src_sec", "A1_numbers"],
    ["src_sec", "A2_filings"],
    ["src_yfinance", "A1_numbers"],
    ["src_universe", "A3_industry"],
    ["src_fred", "A4_macro"],
    ["src_sponsor", "A1_numbers"],
  ] as const) {
    nets.push({
      id: `${a}>${b}`,
      d: hvh(BY_ID[a], BY_ID[b], BUS.src),
      kind: "signal",
      from: a,
      to: b,
    });
  }

  // acquirers → evidence store, merging on one vertical bus.
  for (const id of ["A1_numbers", "A2_filings", "A3_industry", "A4_macro"]) {
    nets.push({
      id: `${id}>B`,
      d: hvh(BY_ID[id], BY_ID.B_structure, BUS.a),
      kind: "signal",
      from: id,
      to: "B_structure",
    });
    junctions.push({ x: BUS.a, y: cy(BY_ID[id]) });
  }

  // The extractor's footprint, wired with nets that carry nothing. Its return
  // leg goes straight up into the store's underside rather than hooking back to
  // the same edge the lens bus leaves from — a conductor that leaves an edge and
  // returns to it reads as a fault, not a feed.
  nets.push({
    id: "A2>B_extract",
    d: hvh(BY_ID.A2_filings, BY_ID.B_extract, BUS.extract),
    kind: "reference",
  });
  nets.push({
    id: "B_extract>B",
    d: `M${BY_ID.B_extract.x + 70},${BY_ID.B_extract.y} V${BY_ID.B_structure.y + BY_ID.B_structure.h}`,
    kind: "reference",
  });

  // evidence store → each lens, off one distribution bus. Width is that lens's
  // own citation count, so a lens standing on a single quote looks like it does.
  for (const [id] of LENSES) {
    const lens = BY_ID[`C_${id}`];
    nets.push({
      id: `B>C_${id}`,
      d: `M${right(BY_ID.B_structure)},${cy(BY_ID.B_structure)} H${BUS.b} V${cy(lens)} H${lens.x}`,
      kind: "signal",
      from: "B_structure",
      to: `C_${id}`,
      volume: claims.get(id),
    });
    junctions.push({ x: BUS.b, y: cy(lens) });
  }

  // lens → V1. In-line: this is the net V1 is able to break.
  for (const [id] of LENSES) {
    const lens = BY_ID[`C_${id}`];
    const open = id in dropped;
    nets.push({
      id: `C_${id}>V1`,
      d: `M${right(lens)},${cy(lens)} H${X.v1}`,
      kind: "signal",
      from: `C_${id}`,
      to: "V1_reconcile",
      volume: claims.get(id),
      open,
      mark: open ? [(right(lens) + X.v1) / 2, cy(lens)] : undefined,
    });
  }

  // V1 → champion, collecting on one bus. A dropped lens is open here too, and
  // the collector bus is visibly thinner for it.
  for (const [id] of LENSES) {
    const lens = BY_ID[`C_${id}`];
    const open = id in dropped;
    nets.push({
      id: `V1>D_${id}`,
      d: `M${right(BY_ID.V1_reconcile)},${cy(lens)} H${BUS.v1} V${cy(BY_ID.D_champion)} H${X.d}`,
      kind: "signal",
      from: "V1_reconcile",
      to: "D_champion",
      volume: claims.get(id),
      open,
      mark: open ? [(right(BY_ID.V1_reconcile) + BUS.v1) / 2, cy(lens)] : undefined,
    });
    if (!open) junctions.push({ x: BUS.v1, y: cy(lens) });
  }

  nets.push({
    id: "D>E",
    d: `M${right(BY_ID.D_champion)},${cy(BY_ID.D_champion)} H${X.e}`,
    kind: "signal",
    from: "D_champion",
    to: "E_judge",
    volume: totalKept,
  });

  // judge → λ's first input. One distribution, not a bundle of claims, so this
  // conductor is a fixed weight: the volume story ends at the judge.
  nets.push({
    id: "E>F",
    d: `M${right(BY_ID.E_judge)},${cy(BY_ID.E_judge)} H${BUS.eJog} V${BY_ID.F_lambda.y + 30} H${X.f}`,
    kind: "signal",
    from: "E_judge",
    to: "F_lambda",
  });

  // THE CONSENSUS BUS. Tapped at A1's underside, down the outboard gutter so it
  // clears the rest of column A, along the bottom of the sheet, through the
  // baseline in series, and up into λ's second input. It touches nothing else.
  const a1 = BY_ID.A1_numbers;
  nets.push({
    id: "rail_in",
    d: `M${X.a + 24},${a1.y + a1.h} V${a1.y + a1.h + 18} H${BUS.railDown} V${BUS.rail} H${X.d}`,
    kind: "rail",
    from: "A1_numbers",
  });
  // The baseline is IN SERIES on the rail, not a branch off it: it is consensus
  // with the company's own shrunk surprise applied, and nothing else touches it.
  // Its output deliberately terminates here — the baseline is what the forecast
  // is scored against, not an input to it. Wiring it into G would be a lie.
  nets.push({
    id: "rail_lambda",
    d: `M${right(BY_ID.baseline)},${BUS.rail} H${BUS.lamIn} V${BY_ID.F_lambda.y + 78} H${X.f}`,
    kind: "rail",
    from: "A1_numbers",
    to: "F_lambda",
  });

  nets.push({
    id: "F>G",
    d: `M${right(BY_ID.F_lambda)},${cy(BY_ID.F_lambda)} H${X.g}`,
    kind: "signal",
    from: "F_lambda",
    to: "G_output",
  });

  // Control lines. Dashed, thin, arrowed, entering the underside of the part they
  // modulate — the visual grammar for "changes how this behaves" rather than
  // "feeds this". V2 leaves upward into its own lane at y=560 so it passes above
  // V3 instead of through it.
  const v2 = BY_ID.V2_comparability;
  nets.push({
    id: "V2>F",
    d: `M${v2.x + v2.w / 2},${v2.y} V${BUS.v2Lane} H${BUS.v2Ctl} V${BY_ID.F_lambda.y + BY_ID.F_lambda.h}`,
    kind: "control",
    from: "V2_comparability",
  });
  nets.push({
    id: "V3>G",
    d: `M${right(BY_ID.V3_calibrate)},${cy(BY_ID.V3_calibrate)} H${BUS.v3Ctl} V${SPINE + 38}`,
    kind: "control",
    from: "V3_calibrate",
  });

  return { nets, junctions, maxVolume };
}

/**
 * Conductor width from claim volume.
 *
 * The exponent is 0.75 rather than 1.0 or 0.5 on purpose. Linear lets the
 * busiest lens crush the rest into hairlines; a square root flattens everything
 * into near-identical wires and the encoding stops saying anything. 0.75 across
 * the fixture's real spread (2 to 11 claims) gives a 2.3x range, which reads
 * across a room without any wire disappearing.
 */
function width(net: Net, max: number): number {
  if (net.kind === "rail") return 4.8;
  if (net.kind === "control") return 0.9;
  if (net.kind === "reference") return 0.8;
  if (net.open) return 0.7;
  if (net.volume == null) return 1.6;
  if (net.volume === 0) return 0.7;
  return 1.0 + 3.4 * Math.pow(net.volume / max, 0.75);
}

export default function Schematic({
  overlay,
  build,
  live,
  result,
  onSelect,
  selected,
}: {
  overlay: Overlay;
  build: Record<string, BuildComponent>;
  live: Record<string, NodeStatus>;
  result: RunResult | null;
  onSelect?: (part: OrgNode) => void;
  selected?: string | null;
}) {
  const { nets, junctions, maxVolume } = buildNets(result);
  const lambda = result?.forecast.lambda_decision.value ?? null;

  function paint(part: Part) {
    if (overlay === "live") {
      const state = part.liveId ? (live[part.liveId]?.state ?? "idle") : "idle";
      return {
        fill: LIVE_FILL[state],
        stroke: LIVE_STROKE[state],
        pulse: state === "running",
      };
    }
    if (overlay === "tier") {
      const tier = part.tier ?? "none";
      return { fill: TIER_FILL[tier], stroke: TIER_STROKE[tier], pulse: false };
    }
    const state = (part.component ? build[part.component]?.state : undefined) as
      | keyof typeof BUILD_FILL
      | undefined;
    return {
      fill: BUILD_FILL[state ?? "unknown"],
      stroke: BUILD_STROKE[state ?? "unknown"],
      pulse: false,
    };
  }

  /** A net is carrying now if its destination is running; solid once delivered. */
  function energy(net: Net): "off" | "carrying" | "delivered" {
    if (overlay !== "live" || net.open) return "off";
    const to = net.to ? BY_ID[net.to]?.liveId : undefined;
    if (to && live[to]?.state === "running") return "carrying";
    const from = net.from ? BY_ID[net.from]?.liveId : undefined;
    if (from && live[from]?.state === "done") return "delivered";
    return "off";
  }

  return (
    <div className="scroll-x">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[1240px]">
        <defs>
          <marker
            id="sch-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-ink-3)" />
          </marker>
          <pattern
            id="sch-hatch"
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

        {/* ---- sheet header ------------------------------------------------ */}
        <text x={20} y={40} className="display fill-ink" style={{ fontSize: 17 }}>
          Signal flow
        </text>
        <text
          x={20}
          y={56}
          className="fill-ink-3"
          style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: "0.14em" }}
        >
          FORECASTER · SHEET 10 · REV C
        </text>

        <g transform="translate(190, 0)">
          <rect x={0} y={30} width={26} height={13} fill="var(--color-paper-2)" />
          <rect x={0} y={30} width={4} height={13} fill="var(--color-accent)" />
          <rect
            x={0}
            y={30}
            width={26}
            height={13}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={1.4}
          />
          <text x={32} y={40} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            <tspan className="fill-ink" style={{ fontWeight: 700 }}>
              AGENT
            </tspan>{" "}
            reasons with a model
          </text>

          <rect x={0} y={50} width={26} height={13} fill="url(#sch-hatch)" opacity={0.3} />
          <rect
            x={0}
            y={50}
            width={26}
            height={13}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={1.4}
          />
          <text x={32} y={60} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            <tspan className="fill-ink" style={{ fontWeight: 700 }}>
              CODE
            </tspan>{" "}
            deterministic, cannot hallucinate
          </text>
        </g>

        <g transform="translate(560, 0)">
          <path
            d="M0,36 H40"
            stroke="var(--color-ink-3)"
            strokeWidth={3.6}
            fill="none"
          />
          <text x={48} y={40} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            conductor width = <tspan className="fill-ink">live claim volume</tspan>
          </text>
          <path
            d="M0,56 H14 M26,56 H40"
            stroke="var(--color-failed)"
            strokeWidth={0.9}
            fill="none"
          />
          <path
            d="M16,52 L24,60 M24,52 L16,60"
            stroke="var(--color-failed)"
            strokeWidth={1.1}
            fill="none"
          />
          <text x={48} y={60} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            open circuit = <tspan className="fill-ink">lens dropped, nothing arrives</tspan>
          </text>
        </g>

        <g transform="translate(950, 0)">
          <path
            d="M0,36 H40"
            stroke="var(--color-ink-3)"
            strokeWidth={1}
            strokeDasharray="4 3"
            fill="none"
            markerEnd="url(#sch-arrow)"
          />
          <text x={48} y={40} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            control line — <tspan className="fill-ink">modulates, contributes no estimate</tspan>
          </text>
          <path
            d="M0,56 H40"
            stroke="var(--color-structure)"
            strokeWidth={4.8}
            fill="none"
          />
          <text x={48} y={60} className="fill-ink-2" style={{ fontSize: 8.5 }}>
            consensus bus — <tspan className="fill-ink">the anchor, routed straight to λ</tspan>
          </text>
        </g>

        <path
          d={`M20,74 H${W - 20}`}
          stroke="var(--color-rule)"
          strokeWidth={1}
          fill="none"
        />

        {/* ---- column headers, drafted as a table row ---------------------- */}
        {(
          [
            ["SOURCES", X.src, 108],
            ["A · ACQUIRE", X.a, 128],
            ["B · STRUCTURE", X.b, 140],
            ["C · ANALYSE", X.c, 178],
            ["V1", X.v1, 50],
            ["D · CHALLENGE", X.d, 134],
            ["E · JUDGE", X.e, 138],
            ["F · POSITION", X.f, 150],
            ["G", X.g, 130],
          ] as const
        ).map(([label, x, w]) => (
          <g key={label}>
            <text
              x={x + w / 2}
              y={186}
              textAnchor="middle"
              className="fill-ink-3"
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.12em",
                fontFamily: "var(--font-mono)",
              }}
            >
              {label}
            </text>
            <path
              d={`M${x},194 H${x + w}`}
              stroke="var(--color-rule-2)"
              strokeWidth={1}
              fill="none"
            />
          </g>
        ))}

        {/* ---- nets -------------------------------------------------------- */}
        {nets.map((net) => {
          const state = energy(net);
          const stroke =
            net.open
              ? "var(--color-failed)"
              : net.kind === "rail"
                ? "var(--color-structure)"
                : state === "carrying"
                  ? "var(--color-accent)"
                  : state === "delivered"
                    ? "var(--color-structure)"
                    : "var(--color-ink-3)";
          return (
            <path
              key={net.id}
              d={net.d}
              fill="none"
              stroke={stroke}
              strokeWidth={width(net, maxVolume)}
              strokeDasharray={
                net.open
                  ? "5 5"
                  : net.kind === "control" || net.kind === "reference"
                    ? "4 3"
                    : undefined
              }
              opacity={
                net.open
                  ? 0.55
                  : net.kind === "reference"
                    ? 0.4
                    : net.kind === "control"
                      ? 0.5
                      : state === "off"
                        ? 0.5
                        : 0.9
              }
              markerEnd={net.kind === "control" ? "url(#sch-arrow)" : undefined}
              className={
                state === "carrying"
                  ? "trunk-live"
                  : state === "delivered"
                    ? "state-change"
                    : "state-change"
              }
            />
          );
        })}

        {/* Break markers. A dropped lens is an open circuit, drawn as one. */}
        {nets
          .filter((n) => n.mark)
          .map((n) => (
            <path
              key={`mark-${n.id}`}
              d={`M${n.mark![0] - 4},${n.mark![1] - 4} L${n.mark![0] + 4},${n.mark![1] + 4} M${n.mark![0] + 4},${n.mark![1] - 4} L${n.mark![0] - 4},${n.mark![1] + 4}`}
              stroke="var(--color-failed)"
              strokeWidth={1.4}
              fill="none"
            />
          ))}

        {junctions.map((j) => (
          <circle
            key={`${j.x}-${j.y}`}
            cx={j.x}
            cy={j.y}
            r={2.9}
            fill="var(--color-ink-3)"
          />
        ))}

        {/* ---- parts ------------------------------------------------------- */}
        {PARTS.map((part) => {
          const { fill, stroke, pulse } = paint(part);
          const component = part.component ? build[part.component] : undefined;
          const isSelected = selected === part.id;
          const vertical = part.w < 70;
          const stubYs = Array.from(
            { length: part.stubs },
            (_, i) => part.y + (part.h * (i + 1)) / (part.stubs + 1),
          );
          return (
            <g
              key={part.id}
              className={pulse ? "node-running" : undefined}
              onClick={() => onSelect?.(part)}
              style={{ cursor: onSelect ? "pointer" : undefined }}
            >
              <title>
                {part.label} — {part.role ?? part.sub}
              </title>

              {/* designator, above the part, as on a real sheet */}
              <text
                x={part.x}
                y={part.y - 5}
                className="fill-ink-3"
                style={{
                  fontSize: 8,
                  fontWeight: 700,
                  letterSpacing: "0.1em",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {part.ref}
              </text>

              {/* pin stubs */}
              {stubYs.map((y) => (
                <g key={y}>
                  {part.sides !== "out" && (
                    <path
                      d={`M${part.x - 7},${y} H${part.x}`}
                      stroke="var(--color-ink-3)"
                      strokeWidth={1}
                    />
                  )}
                  {part.sides !== "in" && (
                    <path
                      d={`M${part.x + part.w},${y} H${part.x + part.w + 7}`}
                      stroke="var(--color-ink-3)"
                      strokeWidth={1}
                    />
                  )}
                </g>
              ))}

              <rect
                x={part.x}
                y={part.y}
                width={part.w}
                height={part.h}
                fill={fill}
                stroke={isSelected ? "var(--color-ink)" : stroke}
                strokeWidth={isSelected ? 2.4 : part.kind === "data" ? 1 : 1.6}
                strokeDasharray={
                  part.audit ? "5 3" : part.ghost ? "3 3" : undefined
                }
                opacity={part.ghost ? 0.75 : 1}
                className="state-change"
              />

              {part.kind === "code" && (
                <rect
                  x={part.x}
                  y={part.y}
                  width={part.w}
                  height={part.h}
                  fill="url(#sch-hatch)"
                  opacity={0.16}
                  pointerEvents="none"
                />
              )}

              {part.kind === "agent" && (
                <>
                  <rect
                    x={part.x}
                    y={part.y}
                    width={4}
                    height={part.h}
                    fill={TAB[part.tier ?? "mid"]}
                    pointerEvents="none"
                  />
                  <rect
                    x={part.x + 3.5}
                    y={part.y + 3.5}
                    width={part.w - 7}
                    height={part.h - 7}
                    fill="none"
                    stroke="var(--color-accent)"
                    strokeWidth={0.6}
                    opacity={0.45}
                    pointerEvents="none"
                  />
                </>
              )}

              {vertical ? (
                <text
                  transform={`rotate(-90 ${part.x + part.w / 2} ${part.y + part.h / 2})`}
                  x={part.x + part.w / 2}
                  y={part.y + part.h / 2}
                  textAnchor="middle"
                  className="display fill-ink"
                  style={{ fontSize: 11.5 }}
                >
                  {part.label} · {part.sub}
                </text>
              ) : (
                <>
                  <text
                    x={part.x + part.w / 2 + (part.kind === "agent" ? 2 : 0)}
                    y={part.y + part.h / 2 - 1}
                    textAnchor="middle"
                    className={
                      overlay === "tier" && part.tier === "deep"
                        ? "display fill-paper"
                        : "display fill-ink"
                    }
                    style={{ fontSize: 12.5 }}
                  >
                    {part.label}
                  </text>
                  <text
                    x={part.x + part.w / 2 + (part.kind === "agent" ? 2 : 0)}
                    y={part.y + part.h / 2 + 12}
                    textAnchor="middle"
                    className={
                      overlay === "tier" && part.tier === "deep"
                        ? "fill-paper"
                        : "fill-ink-2"
                    }
                    style={{ fontSize: 8.5 }}
                  >
                    {part.sub}
                  </text>
                </>
              )}

              {part.kind === "agent" && part.tier && !vertical && (
                <text
                  x={part.x + 9}
                  y={part.y + 11}
                  className={
                    overlay === "tier" && part.tier === "deep"
                      ? "fill-paper"
                      : "fill-ink-3"
                  }
                  style={{ fontSize: 8, fontWeight: 700 }}
                >
                  {part.tier.toUpperCase()}
                </text>
              )}

              {overlay === "build" && component && !vertical && (
                <text
                  x={part.x + part.w - 6}
                  y={part.y + 11}
                  textAnchor="end"
                  className={
                    component.state === "built" ? "fill-structure" : "fill-accent"
                  }
                  style={{ fontSize: 8, fontWeight: 700 }}
                >
                  {component.state === "built"
                    ? `${component.tests ?? 0} tests`
                    : component.state === "partial"
                      ? "untested"
                      : "missing"}
                </text>
              )}

              {overlay === "live" &&
                part.liveId &&
                (live[part.liveId]?.latencyMs ?? 0) > 0 &&
                !vertical && (
                  <text
                    x={part.x + part.w - 6}
                    y={part.y + 11}
                    textAnchor="end"
                    className="num fill-ink-3"
                    style={{ fontSize: 8 }}
                  >
                    {(live[part.liveId]!.latencyMs ?? 0) >= 1000
                      ? `${((live[part.liveId]!.latencyMs ?? 0) / 1000).toFixed(1)}s`
                      : `${live[part.liveId]!.latencyMs}ms`}
                  </text>
                )}

              {part.unwired && (
                <text
                  x={part.x + part.w / 2}
                  y={part.y + part.h + 11}
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

        {/* ---- λ drawn as what it is: a crossfader ------------------------- */}
        <g pointerEvents="none">
          {(() => {
            const f = BY_ID.F_lambda;
            const trackX = f.x + 116;
            const top = f.y + 26;
            const bottom = f.y + 92;
            const wiper = lambda == null ? null : bottom - lambda * (bottom - top);
            return (
              <>
                <path
                  d={`M${trackX},${top} V${bottom}`}
                  stroke="var(--color-ink-3)"
                  strokeWidth={1.2}
                />
                {[0, 0.5, 1].map((t) => (
                  <path
                    key={t}
                    d={`M${trackX - 4},${bottom - t * (bottom - top)} H${trackX + 4}`}
                    stroke="var(--color-ink-3)"
                    strokeWidth={1}
                  />
                ))}
                <text
                  x={trackX + 8}
                  y={top + 3}
                  className="fill-ink-3"
                  style={{ fontSize: 7.5, fontWeight: 700 }}
                >
                  OWN
                </text>
                <text
                  x={trackX + 8}
                  y={bottom + 3}
                  className="fill-ink-3"
                  style={{ fontSize: 7.5, fontWeight: 700 }}
                >
                  CONS
                </text>
                {wiper != null && (
                  <>
                    <path
                      d={`M${trackX - 13},${wiper - 5} L${trackX - 2},${wiper} L${trackX - 13},${wiper + 5} Z`}
                      fill="var(--color-accent)"
                    />
                    <path
                      d={`M${f.x + 10},${wiper} H${trackX - 14}`}
                      stroke="var(--color-accent)"
                      strokeWidth={0.9}
                      strokeDasharray="3 2"
                    />
                  </>
                )}
                <text
                  x={f.x + 10}
                  y={f.y + 100}
                  className="num fill-ink-2"
                  style={{ fontSize: 9 }}
                >
                  λ {lambda == null ? "—" : lambda.toFixed(2)}
                </text>
              </>
            );
          })()}
        </g>

        {/* ---- the annotations that carry the argument --------------------- */}
        <text
          x={X.c + 89}
          y={LENS_BOTTOM + 24}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 9 }}
        >
          seven lenses, zero nets between them — blind to each other by design
        </text>

        <text
          x={BUS.railDown + 14}
          y={BUS.rail - 9}
          className="fill-structure"
          style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.1em" }}
        >
          CONSENSUS BUS
        </text>
        <text
          x={BUS.railDown}
          y={BUS.rail + 40}
          className="fill-ink-2"
          style={{ fontSize: 9.5 }}
        >
          Tapped at A1, past every stage untouched, into λ&rsquo;s second input. The
          baseline sits in series on it and terminates there — it is what the
          forecast is scored against, not an input to it.
        </text>
        <text
          x={BUS.railDown}
          y={BUS.rail + 55}
          className="fill-ink-3"
          style={{ fontSize: 9.5 }}
        >
          Everything above this line exists to earn the right to move the wiper off
          it. On a sixty-one-analyst mega-cap, not moving it is the correct answer —
          not a failure.
        </text>

        <text
          x={X.v1 + 25}
          y={LY0 - 8}
          textAnchor="middle"
          className="fill-ink-3"
          style={{ fontSize: 8, fontWeight: 700 }}
        >
          IN-LINE
        </text>

        <text
          x={20}
          y={H - 18}
          className="fill-ink-3"
          style={{ fontSize: 8.5, letterSpacing: "0.04em" }}
        >
          IN-LINE V1 sits in the signal path and can break it · CONTROL V2
          collapses λ, V3 sets interval width only · ✕ open circuit = lens dropped,
          logged, and the judge is told it is missing · dashed footprint = built but
          not in the circuit
        </text>
      </svg>
    </div>
  );
}
