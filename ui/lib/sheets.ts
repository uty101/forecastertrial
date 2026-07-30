/**
 * The sheet index.
 *
 * One place, so the "04/09" readout in every title block, the nav order and the
 * route list cannot drift apart. The number in the corner of a drawing is
 * meaningless if it doesn't match the drawing set.
 */

export interface SheetDef {
  href: string;
  n: number;
  nav: string;
  system: string;
}

export const SHEETS: SheetDef[] = [
  // Sheet 01 is the whole-system view: the one screen that answers "what is
  // this, what is running, and what is left" without reading the other nine.
  { href: "/system/", n: 1, nav: "System", system: "system overview" },
  { href: "/", n: 2, nav: "Live run", system: "pipeline execution" },
  { href: "/forecast/", n: 3, nav: "Forecast", system: "earnings forecast" },
  { href: "/reasoning/", n: 4, nav: "Reasoning", system: "lens + challenge trace" },
  { href: "/model/", n: 5, nav: "Model", system: "three-statement model" },
  { href: "/risk/", n: 6, nav: "Risk", system: "deviation + capital control" },
  { href: "/eval/", n: 7, nav: "Method", system: "backtest + calibration" },
  { href: "/agents/", n: 8, nav: "Agents", system: "agent roster" },
  { href: "/cost/", n: 9, nav: "Cost", system: "token allocation" },
  { href: "/integrity/", n: 10, nav: "Integrity", system: "provenance + point-in-time" },
];

export const TOTAL = SHEETS.length;

export function sheetOf(href: string): [number, number] {
  const found = SHEETS.find((s) => s.href === href);
  return [found?.n ?? 0, TOTAL];
}
