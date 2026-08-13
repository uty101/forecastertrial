"use client";

import {
  BUILD_STROKE,
  fillFor,
  strokeFor,
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
 *   bus          at B1 and runs along the bottom of the sheet, past every stage,
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

const W = 1910;
// Raised from 992 when the lens rank went from seven parts to nine. Everything
// on the sheet is anchored to SPINE, which is derived from the rank, so the
// whole drawing recentres rather than needing to be re-routed by hand.
const H = 1128;

/* Nine, not seven. Market and Demand were added because two of the questions
   that move a forecast were being asked by nobody: is this growth the
   market's or the company's, and what have its customers said about their own
   budgets. Declared before the rank constants because the rank is derived
   from its length. */
export const LENSES = [
  ["mechanical", "Mechanical", "FX · shares · interest", "none"],
  ["guidance", "Guidance", "guide + landing CDF", "mid"],
  ["drivers", "Drivers", "units × ASP", "mid"],
  ["demand", "Demand", "customers · suppliers", "mid"],
  ["market", "Market", "market growth vs share", "mid"],
  ["margins", "Margins", "GM mix · opex · tax", "mid"],
  ["forensics", "Forensics", "accruals · exclusions", "mid"],
  ["peer_read", "Peer read", "who already reported", "mid"],
  ["macro", "Macro", "series vs assumed", "mid"],
] as const;

/* The lens rank is the spine of the drawing; everything else centres on it. */
const LY0 = 226;
const LH = 52;
const LPITCH = 68;
const lensY = (i: number) => LY0 + i * LPITCH;
const LENS_BOTTOM = lensY(LENSES.length - 1) + LH;
const SPINE = (LY0 + LENS_BOTTOM) / 2;

/* Column origins. Buses run in the gutters between them.
 *
 * Keyed by stage NAME rather than stage letter. They were letters, and when
 * Sources became stage A every one of them was off by one — a key called `a`
 * holding the acquire column. Names cannot desync from a renumbering. */
const X = {
  sources: 28,
  acquire: 214,
  structure: 414,
  model: 600,
  analyse: 816,
  v1: 1042,
  challenge: 1136,
  judge: 1336,
  position: 1540,
  output: 1746,
} as const;

/**
 * Bus lanes, all in the gutters between columns.
 *
 * These are hand-picked rather than derived, and every one of them was moved at
 * least once: the first routing put the consensus rail straight through the B2,
 * B3 and B4 packages, and V2's control line through V3. A schematic where a
 * conductor crosses a part is not a stylistic problem — it is unreadable, since
 * you cannot tell a crossing from a connection. Crossings between conductors are
 * fine and expected, which is exactly why junction dots exist.
 */
const BUS = {
  src: 170, // sources fan into the acquirers
  railDown: 196, // the consensus rail drops down this gutter, left of column B
  acquire: 380, // acquirers merge into the evidence store
  structure: 576, // the store hands the model its claims
  model: 782, // the model fans out to the lenses
  v1: 1112, // reconciled outputs collect into the champion
  rail: 952, // the consensus bus, along the bottom of the sheet
  lamIn: 1492, // where the rail turns up into λ's second input
  eJog: 1518, // where the judge's output steps into λ's first input
  v2Lane: 560, // V2's control line runs along here, clear of V3
  v2Ctl: 1570, // and turns up into λ's underside
  v3Ctl: 1772, // V3's control line turns up into the output
} as const;

const RAW_PARTS: Part[] = [
  // ---- sources: terminals, not components -------------------------------- //
  ...(
    [
      ["sec", "SEC", "XBRL · filings · SIC peers", 250],
      ["yfinance", "yfinance", "consensus · prices · shares", 318],
      ["exa", "Exa", "news, date-bounded", 386],
      ["lse", "LSE", "options chain · implied move", 454],
      ["universe", "Universe", "prepared, local", 522],
      ["fred", "FRED", "macro via ALFRED", 590],
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
    x: X.sources,
    y,
    w: 108,
    h: 44,
  })),
  {
    id: "src_sponsor",
    ref: "J7",
    label: "Sponsor feed",
    sub: "one adapter, written on the day",
    component: "sponsor",
    role: "source",
    kind: "data",
    tier: "none",
    // Still a ghost: it is the one terminal with nothing behind it until 10am.
    ghost: true,
    stubs: 1,
    sides: "out",
    x: X.sources,
    y: 658,
    w: 108,
    h: 44,
  },

  // ---- A: acquire --------------------------------------------------------- //
  //
  // B5 sits directly under B2 rather than at the numeric end of the rank,
  // because it is the one acquirer fed by another acquirer rather than by a
  // source: it reads the EX-99 body B2 pulled down. Any other placement routes
  // its feed either straight through B3 and B4 — on a schematic you cannot tell
  // a crossing from a connection — or out to a lane and back into the same edge
  // it left, which reads as a fault. The org chart keeps numeric order because
  // it draws rank; this sheet draws signal flow, and they disagree here.
  ...(
    [
      ["B1_numbers", "B1 Numbers", "XBRL · consensus", 250, "acquire", "none"],
      ["B1b_series", "B1b Series", "74 quarters · daily bars", 318, "acquire", "none"],
      ["B2_filings", "B2 Filings", "8-K item 2.02 · EX-99", 386, "acquire", "none"],
      ["B5_extract", "B5 Extract", "EX-99 prose → cited guide", 454,
       "extract_guidance", "cheap"],
      ["B3_industry", "B3 Industry", "peers by SIC · news", 522, "acquire", "none"],
      ["B4_macro", "B4 Macro", "realtime_start pinned", 590, "acquire", "none"],
      // Three more model calls over the same acquired prose. They are in this
      // column rather than a rank of their own because on a schematic a column
      // is a stage, and these run inside acquisition — but the tier overlay
      // paints them as agents, which is the distinction that matters: five of
      // these nine packages cannot be wrong in an interesting way, and four can.
      ["B6_bridge", "B6 Bridge", "GAAP → non-GAAP, ×5", 658,
       "extract_bridge", "cheap"],
      ["E7_calls", "E7 Calls", "8 calls → what CHANGED", 726,
       "scan_calls", "cheap"],
      ["E6_perception", "E6 Perception", "coverage → stance + spread", 794,
       "scan_perception", "cheap"],
    ] as const
  ).map(([id, label, sub, y, component, tier], i) => ({
    id,
    ref: `U${i + 1}`,
    label,
    sub,
    component,
    liveId: id,
    kind: (tier === "none" ? "data" : "agent") as Kind,
    tier,
    stubs: 2,
    x: X.acquire,
    y,
    w: 128,
    h: 50,
  })),

  // ---- B: structure ------------------------------------------------------- //
  {
    id: "C_structure",
    ref: "U7",
    label: "Evidence store",
    sub: "one byte-identical corpus",
    role: "shared, cached, keyed on input hash",
    component: "evidence",
    liveId: "C_structure",
    kind: "code",
    tier: "none",
    stubs: 3,
    x: X.structure,
    y: SPINE - 38,
    w: 140,
    h: 76,
  },

  // ---- D: the three-statement model --------------------------------------- //
  //
  // In the signal path, not beside it. The lenses read the model rather than
  // the store directly, so every one of them argues with the same ratio base
  // and is told the same thing about how much of a change the arithmetic
  // downstream can actually resolve.
  {
    id: "D_model",
    ref: "U8",
    label: "3-statement model",
    sub: "ratio base · reproduces past quarters",
    role: "deterministic — nothing here can hallucinate",
    component: "model",
    liveId: "D_model",
    kind: "code",
    tier: "none",
    stubs: 3,
    x: X.model,
    y: SPINE - 38,
    w: 150,
    h: 76,
  },

  // ---- E: seven lenses, and no nets between them --------------------------- //
  ...LENSES.map(([id, label, sub, tier], i) => ({
    id: `E_${id}`,
    ref: `U${9 + i}`,
    label,
    sub,
    role: "lens",
    component: id,
    liveId: `E_${id}`,
    kind: (tier === "none" ? "code" : "agent") as Kind,
    tier,
    stubs: 2,
    x: X.analyse,
    y: lensY(i),
    w: 178,
    h: LH,
  })),

  // ---- V1: a series element, inside the signal path ------------------------ //
  {
    id: "V1_reconcile",
    ref: "U16",
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
    id: "F_champion",
    ref: "U17",
    label: "Champion",
    sub: "argue, then attack",
    role: "×7 — one prompt, seven parallel calls",
    component: "champion",
    liveId: "F_champion",
    kind: "agent",
    tier: "mid",
    stubs: 3,
    x: X.challenge,
    y: SPINE - 40,
    w: 134,
    h: 80,
  },
  {
    id: "G_judge",
    ref: "U18",
    label: "Judge",
    sub: "materiality, never votes",
    role: "one expensive call, highest leverage",
    component: "judge",
    liveId: "G_judge",
    kind: "agent",
    tier: "deep",
    stubs: 3,
    x: X.judge,
    y: SPINE - 40,
    w: 138,
    h: 80,
  },

  // ---- V2, V3: control lines, not series elements --------------------------- //
  {
    id: "V2_comparability",
    ref: "U19",
    label: "V2 Comparability",
    sub: "M&A · accounting · 53rd week",
    role: "gate — when it fires, λ collapses",
    component: "v2",
    liveId: "V2_comparability",
    kind: "agent",
    tier: "cheap",
    audit: true,
    stubs: 2,
    x: X.judge,
    y: 704,
    w: 138,
    h: 48,
  },
  {
    id: "V3_calibrate",
    ref: "U20",
    label: "V3 Calibrate",
    sub: "bootstrapped own residuals",
    role: "gate — sets the interval width, nothing else",
    component: "v3",
    liveId: "V3_calibrate",
    kind: "code",
    tier: "none",
    audit: true,
    stubs: 2,
    x: X.position,
    y: 704,
    w: 150,
    h: 48,
  },

  // ---- F: the mixer -------------------------------------------------------- //
  {
    id: "H_lambda",
    ref: "U21",
    label: "λ",
    sub: "fitted, regime-conditioned",
    role: "crossfade: consensus ↔ our own estimate",
    component: "lambda",
    liveId: "H_lambda",
    kind: "code",
    tier: "none",
    stubs: 2,
    x: X.position,
    y: SPINE - 54,
    w: 150,
    h: 108,
  },

  // ---- the baseline, tapped off the consensus rail -------------------------- //
  {
    id: "baseline",
    ref: "U22",
    label: "Baseline",
    sub: "consensus × (1 + shrunk surprise)",
    role: "the bar to beat — on every chart, by rule",
    component: "backtest",
    kind: "code",
    tier: "none",
    stubs: 2,
    x: X.challenge,
    y: BUS.rail - 22,
    w: 134,
    h: 44,
  },

  // ---- G ------------------------------------------------------------------- //
  {
    id: "I_output",
    ref: "OUT",
    label: "Forecast",
    sub: "point + full quantiles",
    role: "out/results.json — the only interface to any screen",
    kind: "output",
    stubs: 1,
    sides: "in",
    x: X.output,
    y: SPINE - 38,
    w: 130,
    h: 76,
  },
];

/**
 * Designators, numbered in sheet order rather than typed by hand.
 *
 * They were hand-numbered, and adding two lenses put U16 on both the reconciler
 * and a lens. On a real schematic a duplicate designator is a build error; here
 * it silently mislabels two parts on the one drawing whose whole claim is that
 * it is precise. A running counter cannot collide.
 *
 * Terminals keep their J numbers and the output keeps OUT — those are a
 * different series, as on a real sheet.
 */
let designator = 0;
export const PARTS: Part[] = RAW_PARTS.map((part) =>
  part.ref.startsWith("U") ? { ...part, ref: `U${++designator}` } : part,
);

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

/**
 * A printed reading on a conductor: how many claims are on that wire right here.
 *
 * Width is the fast read across a room; the number is what someone leaning in
 * wants, and it is the difference between "that wire looks thicker" and "the
 * store handed the lenses 24 claims and 21 of them survived reconciliation".
 * These are annotations on existing conductors, never extra conductors.
 */
interface Gauge {
  x: number;
  y: number;
  value: number;
  label: string;
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
  const dropped = forecast?.droppee_lenses ?? {};
  const maxVolume = Math.max(1, ...claims.values());
  const totalKept = [...claims.values()].reduce((a, b) => a + b, 0);

  const nets: Net[] = [];
  const junctions: Junction[] = [];

  // sources → acquirers. SEC feeds two: the numbers and the filing body text.
  for (const [a, b] of [
    ["src_sec", "B1_numbers"],
    ["src_sec", "B1b_series"],
    ["src_sec", "B2_filings"],
    ["src_sec", "B3_industry"],
    ["src_yfinance", "B1_numbers"],
    ["src_yfinance", "B1b_series"],
    ["src_exa", "B3_industry"],
    // Exa feeds the two prose scans as well as the industry read: coverage for
    // the perception score, transcripts for the cross-quarter call reading.
    ["src_exa", "E6_perception"],
    ["src_exa", "E7_calls"],
    ["src_lse", "B3_industry"],
    ["src_universe", "B3_industry"],
    ["src_fred", "B4_macro"],
    ["src_sponsor", "B1_numbers"],
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
  for (const id of [
    "B1_numbers",
    "B1b_series",
    "B2_filings",
    "B5_extract",
    "B6_bridge",
    "E7_calls",
    "B3_industry",
    "B4_macro",
  ]) {
    nets.push({
      id: `${id}>B`,
      d: hvh(BY_ID[id], BY_ID.C_structure, BUS.acquire),
      kind: "signal",
      from: id,
      to: "C_structure",
    });
    junctions.push({ x: BUS.acquire, y: cy(BY_ID[id]) });
  }

  // evidence store → model. One conductor, straight across the gutter: the
  // model is fed by the whole corpus rather than by any one acquirer.
  nets.push({
    id: "C_structure>D_model",
    d: `M${right(BY_ID.C_structure)},${cy(BY_ID.C_structure)} H${X.model}`,
    kind: "signal",
    from: "C_structure",
    to: "D_model",
  });

  // B2 → B5, the one net inside column B. The extractor reads the EX-99 body B2
  // pulled down, so its feed is a short vertical between adjacent parts rather
  // than anything routed out to a lane. Drawn off-centre from the merge bus stub
  // so the two conductors on B5's outline do not appear to be one wire passing
  // through the part.
  // The bridge reads the same EX-99 bodies B2 pulled down — five quarters of
  // them, where the guidance extractor reads only the latest.
  nets.push({
    id: "B2_filings>B6_bridge",
    d: `M${BY_ID.B2_filings.x + 76},${BY_ID.B2_filings.y + BY_ID.B2_filings.h} `
      + `V${BY_ID.B6_bridge.y - 14} H${BY_ID.B6_bridge.x + 76} V${BY_ID.B6_bridge.y}`,
    kind: "signal",
    from: "B2_filings",
    to: "B6_bridge",
  });

  // PERCEPTION IS A CONTROL LINE, NOT A SIGNAL, and it lands on the model
  // rather than on the evidence store. That is the whole argument about where
  // sentiment belongs: it is evidence about what is already BELIEVED, and what
  // is already believed is already in the price. It moves the equity risk
  // premium in the DCF and the width of the stress grid. It never touches a
  // driver, and drawing it into the store would say that it does.
  nets.push({
    id: "E6_perception>D_model",
    d: `M${right(BY_ID.E6_perception)},${cy(BY_ID.E6_perception)} `
      + `H${BUS.structure} V${cy(BY_ID.D_model) + 26} H${X.model}`,
    kind: "control",
    from: "E6_perception",
    to: "D_model",
  });

  nets.push({
    id: "B2_filings>B5_extract",
    d: `M${BY_ID.B2_filings.x + 40},${BY_ID.B2_filings.y + BY_ID.B2_filings.h} V${BY_ID.B5_extract.y}`,
    kind: "signal",
    from: "B2_filings",
    to: "B5_extract",
  });

  // evidence store → each lens, off one distribution bus. Width is that lens's
  // own citation count, so a lens standing on a single quote looks like it does.
  for (const [id] of LENSES) {
    const lens = BY_ID[`E_${id}`];
    nets.push({
      id: `D>E_${id}`,
      d: `M${right(BY_ID.D_model)},${cy(BY_ID.D_model)} H${BUS.model} V${cy(lens)} H${lens.x}`,
      kind: "signal",
      from: "D_model",
      to: `E_${id}`,
      volume: claims.get(id),
    });
    junctions.push({ x: BUS.model, y: cy(lens) });
  }

  // lens → V1. In-line: this is the net V1 is able to break.
  for (const [id] of LENSES) {
    const lens = BY_ID[`E_${id}`];
    const open = id in dropped;
    nets.push({
      id: `E_${id}>V1`,
      d: `M${right(lens)},${cy(lens)} H${X.v1}`,
      kind: "signal",
      from: `E_${id}`,
      to: "V1_reconcile",
      volume: claims.get(id),
      open,
      mark: open ? [(right(lens) + X.v1) / 2, cy(lens)] : undefined,
    });
  }

  // V1 → champion, collecting on one bus. A dropped lens is open here too, and
  // the collector bus is visibly thinner for it.
  for (const [id] of LENSES) {
    const lens = BY_ID[`E_${id}`];
    const open = id in dropped;
    nets.push({
      id: `V1>D_${id}`,
      d: `M${right(BY_ID.V1_reconcile)},${cy(lens)} H${BUS.v1} V${cy(BY_ID.F_champion)} H${X.challenge}`,
      kind: "signal",
      from: "V1_reconcile",
      to: "F_champion",
      volume: claims.get(id),
      open,
      mark: open ? [(right(BY_ID.V1_reconcile) + BUS.v1) / 2, cy(lens)] : undefined,
    });
    if (!open) junctions.push({ x: BUS.v1, y: cy(lens) });
  }

  nets.push({
    id: "D>E",
    d: `M${right(BY_ID.F_champion)},${cy(BY_ID.F_champion)} H${X.judge}`,
    kind: "signal",
    from: "F_champion",
    to: "G_judge",
    volume: totalKept,
  });

  // judge → λ's first input. One distribution, not a bundle of claims, so this
  // conductor is a fixed weight: the volume story ends at the judge.
  nets.push({
    id: "E>F",
    d: `M${right(BY_ID.G_judge)},${cy(BY_ID.G_judge)} H${BUS.eJog} V${BY_ID.H_lambda.y + 30} H${X.position}`,
    kind: "signal",
    from: "G_judge",
    to: "H_lambda",
  });

  // THE CONSENSUS BUS. Tapped at B1's underside, down the outboard gutter so it
  // clears the rest of column B, along the bottom of the sheet, through the
  // baseline in series, and up into λ's second input. It touches nothing else.
  const a1 = BY_ID.B1_numbers;
  nets.push({
    id: "rail_in",
    d: `M${X.acquire + 24},${a1.y + a1.h} V${a1.y + a1.h + 18} H${BUS.railDown} V${BUS.rail} H${X.challenge}`,
    kind: "rail",
    from: "B1_numbers",
  });
  // The baseline is IN SERIES on the rail, not a branch off it: it is consensus
  // with the company's own shrunk surprise applied, and nothing else touches it.
  // Its output deliberately terminates here — the baseline is what the forecast
  // is scored against, not an input to it. Wiring it into G would be a lie.
  nets.push({
    id: "rail_lambda",
    d: `M${right(BY_ID.baseline)},${BUS.rail} H${BUS.lamIn} V${BY_ID.H_lambda.y + 78} H${X.position}`,
    kind: "rail",
    from: "B1_numbers",
    to: "H_lambda",
  });

  nets.push({
    id: "F>G",
    d: `M${right(BY_ID.H_lambda)},${cy(BY_ID.H_lambda)} H${X.output}`,
    kind: "signal",
    from: "H_lambda",
    to: "I_output",
  });

  // Control lines. Dashed, thin, arrowed, entering the underside of the part they
  // modulate — the visual grammar for "changes how this behaves" rather than
  // "feeds this". V2 leaves upward into its own lane at y=560 so it passes above
  // V3 instead of through it.
  const v2 = BY_ID.V2_comparability;
  nets.push({
    id: "V2>F",
    d: `M${v2.x + v2.w / 2},${v2.y} V${BUS.v2Lane} H${BUS.v2Ctl} V${BY_ID.H_lambda.y + BY_ID.H_lambda.h}`,
    kind: "control",
    from: "V2_comparability",
  });
  nets.push({
    id: "V3>G",
    d: `M${right(BY_ID.V3_calibrate)},${cy(BY_ID.V3_calibrate)} H${BUS.v3Ctl} V${SPINE + 38}`,
    kind: "control",
    from: "V3_calibrate",
  });

  const keptCount = (forecast?.lenses ?? []).length;
  const gauges: Gauge[] = forecast
    ? [
        {
          x: BUS.structure - 34,
          y: cy(BY_ID.C_structure) - 12,
          value: forecast.lenses.reduce((a, l) => a + l.claim_ids.length, 0),
          label: "cited",
        },
        {
          x: BUS.v1 - 40,
          y: cy(BY_ID.F_champion) - 12,
          value: totalKept,
          label: "verified",
        },
        {
          x: (right(BY_ID.F_champion) + X.judge) / 2,
          y: cy(BY_ID.G_judge) - 12,
          value: keptCount,
          label: "cases",
        },
      ]
    : [];

  return { nets, junctions, maxVolume, gauges };
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
  const { nets, junctions, maxVolume, gauges } = buildNets(result);
  const lambda = result?.forecast.lambda_decision.value ?? null;
  const comparability = result?.forecast.lambda_decision.comparability_flag ?? null;

  /**
   * Kind first, always. The outline hue is what the part IS, and the overlay
   * only modulates it — dimming what is not built, brightening what is running.
   * Repainting the outline by state would throw away the one distinction that
   * has to survive every overlay.
   */
  function paint(part: Part) {
    const kind = strokeFor(part.kind, part.tier);
    const fill = fillFor(part.kind, part.tier);

    if (overlay === "live") {
      const state = part.liveId ? (live[part.liveId]?.state ?? "idle") : "idle";
      if (state === "failed")
        return { fill, stroke: "var(--color-failed)", pulse: false, dim: false };
      return {
        fill,
        stroke: kind,
        pulse: state === "running",
        // Nothing that has not run yet competes with what is running now.
        dim: state === "idle" && !part.ghost,
      };
    }
    if (overlay === "tier") {
      return { fill, stroke: kind, pulse: false, dim: part.kind !== "agent" };
    }
    const state = part.component ? build[part.component]?.state : undefined;
    return {
      fill,
      stroke: state === "missing" ? BUILD_STROKE.missing : kind,
      pulse: false,
      dim: state !== "built",
    };
  }

  /** The per-part readout under the label: what this call cost, and how long. */
  function metrics(part: Part): string | null {
    if (!part.liveId) return null;
    const status = live[part.liveId];
    if (!status) return null;
    const lens = result?.forecast.lenses.find(
      (l) => `E_${l.lens}` === part.liveId,
    );
    const tok = lens ? (lens.input_tokens ?? 0) + (lens.output_tokens ?? 0) : 0;
    const ms = status.latencyMs ?? 0;
    const t = tok >= 1000 ? `${(tok / 1000).toFixed(1)}k` : `${tok}`;
    const d = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
    return `${t}tok · ${d}`;
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
            consensus bus — <tspan className="fill-ink">routed straight to λ</tspan>
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
            ["A · SOURCES", X.sources, 108],
            ["B · ACQUIRE", X.acquire, 128],
            ["C · STRUCTURE", X.structure, 140],
            ["D · MODEL", X.model, 150],
            ["E · ANALYSE", X.analyse, 178],
            ["V1", X.v1, 50],
            ["F · CHALLENGE", X.challenge, 134],
            ["G · JUDGE", X.judge, 138],
            ["H · POSITION", X.position, 150],
            ["I", X.output, 130],
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

        {/* Printed gauges on the trunks. */}
        {gauges.map((g) => (
          <g key={g.label} pointerEvents="none">
            <text
              x={g.x}
              y={g.y}
              textAnchor="middle"
              className="num"
              fill="var(--color-ink)"
              style={{ fontSize: 12, fontWeight: 700 }}
            >
              {g.value}
            </text>
            <text
              x={g.x}
              y={g.y + 10}
              textAnchor="middle"
              className="fill-ink-3"
              style={{ fontSize: 7.5, letterSpacing: "0.1em" }}
            >
              {g.label.toUpperCase()}
            </text>
          </g>
        ))}

        {/* ---- parts ------------------------------------------------------- */}
        {PARTS.map((part) => {
          const { fill, stroke, pulse, dim } = paint(part);
          const component = part.component ? build[part.component] : undefined;
          const isSelected = selected === part.id;
          const vertical = part.w < 70;
          const readout = metrics(part);
          const stubYs = Array.from(
            { length: part.stubs },
            (_, i) => part.y + (part.h * (i + 1)) / (part.stubs + 1),
          );
          return (
            <g
              key={part.id}
              className={pulse ? "node-running" : undefined}
              onClick={() => onSelect?.(part)}
              style={{
                cursor: onSelect ? "pointer" : undefined,
                opacity: dim && !isSelected ? 0.45 : 1,
                transition: "opacity 180ms ease",
              }}
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

              {/* The agent's tab, in its own tier hue. Redundant with the
                  outline colour on purpose: two cues, because colour alone fails
                  in greyscale and on a projector at the back of a room. */}
              {part.kind === "agent" && (
                <rect
                  x={part.x}
                  y={part.y}
                  width={3}
                  height={part.h}
                  fill={stroke}
                  pointerEvents="none"
                />
              )}

              {vertical ? (
                <text
                  transform={`rotate(-90 ${part.x + part.w / 2} ${part.y + part.h / 2})`}
                  x={part.x + part.w / 2}
                  y={part.y + part.h / 2 + 3}
                  textAnchor="middle"
                  fill={stroke}
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.14em",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {part.label.toUpperCase()} · {part.sub}
                </text>
              ) : (
                <>
                  {/* The name, in the part's own hue: you can read the kind off
                      the label without tracing the outline. */}
                  <text
                    x={part.x + part.w / 2 + 2}
                    y={part.y + (readout ? part.h / 2 - 6 : part.h / 2 - 1)}
                    textAnchor="middle"
                    fill={stroke}
                    style={{
                      fontSize: 10.5,
                      fontWeight: 700,
                      letterSpacing: "0.09em",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {part.label.toUpperCase()}
                  </text>
                  <text
                    x={part.x + part.w / 2 + 2}
                    y={part.y + (readout ? part.h / 2 + 6 : part.h / 2 + 12)}
                    textAnchor="middle"
                    className="fill-ink-2"
                    style={{ fontSize: 8.5 }}
                  >
                    {part.sub}
                  </text>
                  {/* Cost and latency, in place, on the part that spent it. A
                      separate cost table makes you correlate two screens; this
                      makes the expensive call obvious while it is happening. */}
                  {readout && (
                    <text
                      x={part.x + part.w / 2 + 2}
                      y={part.y + part.h - 5}
                      textAnchor="middle"
                      className="num fill-ink-3"
                      style={{ fontSize: 7.5 }}
                    >
                      {readout}
                    </text>
                  )}
                </>
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
            const f = BY_ID.H_lambda;
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

        {/* ---- comparability, drawn as a ground -----------------------------
            A ground symbol is exactly the right idiom for what V2 does: when it
            fires, λ is pulled to zero and the forecast sits on consensus. So it
            is not a label saying "λ collapses" — it is a conductor to ground
            that energises when the flag is set, and reads as clear when it is
            not. The symbol lives on the control line, where it belongs. */}
        <g pointerEvents="none">
          {(() => {
            const f = BY_ID.H_lambda;
            const gx = f.x + f.w / 2;
            const gTop = f.y + f.h;
            const fired = Boolean(comparability);
            const hue = fired ? "var(--color-failed)" : "var(--color-ink-3)";
            return (
              <>
                {/* Stem stops short of V2's control lane at y=560 rather than
                    running into it — two conductors meeting without a junction
                    dot is the one ambiguity a schematic must never have. */}
                <path
                  d={`M${gx},${gTop} V${gTop + 24}`}
                  stroke={hue}
                  strokeWidth={fired ? 2.4 : 1}
                  strokeDasharray={fired ? undefined : "3 3"}
                  fill="none"
                  className={fired ? "blink" : undefined}
                />
                {[14, 9, 4].map((halfWidth, i) => (
                  <path
                    key={halfWidth}
                    d={`M${gx - halfWidth},${gTop + 24 + i * 5} H${gx + halfWidth}`}
                    stroke={hue}
                    strokeWidth={fired ? 2.2 : 1.2}
                    fill="none"
                  />
                ))}
                <text
                  x={gx + 22}
                  y={gTop + 31}
                  fill={hue}
                  style={{ fontSize: 8, fontWeight: 700, letterSpacing: "0.08em" }}
                >
                  {fired
                    ? `COMPARABILITY FIRED — λ → 0 (${comparability})`
                    : "COMPARABILITY — CLEAR"}
                </text>
              </>
            );
          })()}
        </g>

        {/* ---- the annotations that carry the argument --------------------- */}
        <text
          x={X.analyse + 89}
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
          Tapped at B1, past every stage untouched, into λ&rsquo;s second input. The
          baseline sits in series and terminates there: it is what the forecast is
          scored against, not an input to it.
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
          collapses λ, V3 sets interval width only · ✕ open circuit = lens dropped
          and the judge told it is missing · dashed footprint = built, not in the
          circuit
        </text>
      </svg>
    </div>
  );
}
