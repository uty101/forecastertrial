/**
 * Does the org chart actually fit on the page, and do any two boxes sit on top
 * of each other?
 *
 * This exists because the answer was NO and nobody noticed. Six boxes overlapped
 * — the eval harness sat across two champion columns, the LLM client across two
 * more, V1 across two lenses — and the chart still rendered, because SVG will
 * happily paint one rectangle over another. On a projector it reads as a smudge,
 * and the fix is invisible in a diff: every box has plausible coordinates.
 *
 * The node list is arithmetic on a handful of layout constants, so a check is
 * cheap and exact. What it cannot check is whether the picture is TRUE — that
 * the boxes are the components that exist and the edges are the calls that
 * happen. `test_agent_count_matches_every_surface_that_states_it` pins the count
 * from the Python side; this pins the geometry.
 *
 * It works by evaluating the layout section of the .tsx with the TypeScript
 * annotations stripped, which is crude and deliberately loud: if the strip fails
 * it throws rather than silently checking nothing. Keep the layout section plain
 * data — arithmetic, arrays and .map — and this keeps working.
 *
 *     node ui/scripts/check-layout.mjs
 */

import { readFileSync } from "node:fs";

const FILES = [
  { path: "ui/components/OrgChart.tsx", from: "const W =", to: "const distinct" },
  // The schematic adds a rule the org chart does not have: a conductor that
  // crosses a part is unreadable, because you cannot tell a crossing from a
  // connection. Every vertical bus lane is checked against every part's
  // horizontal span for exactly that.
  {
    path: "ui/components/Schematic.tsx",
    from: "const W =",
    to: "const BY_ID",
    buses: true,
  },
];

const strip = (body) =>
  body
    .replace(/export /g, "")
    .replace(/ as const/g, "")
    .replace(/ as Kind/g, "")
    .replace(/ as OrgNode\[[^\]]*\]/g, "")
    .replace(/ as "[^"]*"( \| "[^"]*")*/g, "")
    .replace(/: OrgNode\[\]/g, "")
    .replace(/\(n: number, w: number, gap: number, i: number\)/g, "(n, w, gap, i)")
    .replace(/\(i: number\)/g, "(i)")
    .replace(/: Kind\b/g, "")
    .replace(/: Part\[\]/g, "")
    .replace(/\(p: Part\)/g, "(p)");

let failures = 0;

for (const { path, from, to, buses } of FILES) {
  const src = readFileSync(path, "utf8");
  const start = src.indexOf(from);
  const end = src.indexOf(to);
  if (start === -1 || end === -1 || end < start) {
    console.error(`${path}: could not find the layout section — the markers moved`);
    failures++;
    continue;
  }

  // The org chart calls its list NODES and the schematic calls it PARTS; the
  // geometry is the same shape either way.
  const { NODES, W, H, BUS } = new Function(
    strip(src.slice(start, end)) +
      "\nreturn {" +
      "  NODES: typeof NODES !== 'undefined' ? NODES : PARTS," +
      "  W, H, BUS: typeof BUS !== 'undefined' ? BUS : null };",
  )();

  const problems = [];
  for (let i = 0; i < NODES.length; i++) {
    for (let j = i + 1; j < NODES.length; j++) {
      const a = NODES[i];
      const b = NODES[j];
      const dx = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const dy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (dx > 0 && dy > 0) {
        problems.push(`  overlap: ${a.id} × ${b.id} — ${dx}×${dy}px`);
      }
    }
  }

  for (const n of NODES) {
    if (n.x < 0 || n.y < 0 || n.x + n.w > W || n.y + n.h > H) {
      problems.push(`  off-frame: ${n.id} at ${n.x},${n.y} (${n.w}×${n.h})`);
    }
  }

  // The org chart's rank labels run down the left edge from x=14, so a box
  // reaching left of this lands on the word SOURCES. The schematic labels its
  // columns along the top instead and has no such gutter.
  const LABEL_GUTTER = buses ? 0 : 100;
  for (const n of NODES) {
    if (n.x < LABEL_GUTTER) {
      problems.push(`  in the rank-label gutter: ${n.id} at x=${n.x}`);
    }
  }

  // A vertical conductor that runs through a package cannot be read as a
  // crossing, so no bus lane may sit inside a part's horizontal span at a y the
  // part occupies. Approximated as "not inside the span at all", which is
  // stricter than necessary and correspondingly easy to satisfy.
  //
  // Only the six vertical gutters between columns are checked. The others in
  // BUS are not pass-through lanes and would false-positive: `rail` is a Y
  // (the consensus bus runs horizontally along the bottom), and `lamIn`,
  // `eJog`, `v2Ctl` and `v3Ctl` are control lines that TURN UP INTO a part —
  // which is a connection, and connections are the point.
  const GUTTERS = ["src", "railDown", "acquire", "structure", "model", "v1"];
  // The consensus rail is the one horizontal pass-through: it enters at B1 and
  // runs the width of the sheet into lambda's second input, untouched. It is
  // the thesis drawn as a wire, so a package sitting on it is the worst
  // possible thing this check could miss.
  const RAILS = ["rail"];
  if (buses && BUS) {
    for (const lane of GUTTERS) {
      const x = BUS[lane];
      for (const n of NODES) {
        if (x > n.x && x < n.x + n.w) {
          problems.push(`  bus '${lane}' at x=${x} runs through ${n.id}`);
        }
      }
    }
    for (const lane of RAILS) {
      const y = BUS[lane];
      for (const n of NODES) {
        // The baseline part is deliberately ON the rail — it is tapped off it.
        if (n.id === "baseline") continue;
        if (y > n.y && y < n.y + n.h) {
          problems.push(`  rail '${lane}' at y=${y} runs through ${n.id}`);
        }
      }
    }
  }

  if (problems.length) {
    console.error(`${path}: ${problems.length} layout problem(s)`);
    problems.forEach((p) => console.error(p));
    failures += problems.length;
  } else {
    console.log(`${path}: ${NODES.length} boxes, no overlaps, all inside ${W}×${H}`);
  }
}

process.exit(failures ? 1 : 0);
