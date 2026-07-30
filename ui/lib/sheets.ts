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
  { href: "/", n: 1, nav: "Live run", system: "pipeline execution" },
  { href: "/forecast/", n: 2, nav: "Forecast", system: "earnings forecast" },
  { href: "/reasoning/", n: 3, nav: "Reasoning", system: "lens + challenge trace" },
  { href: "/model/", n: 4, nav: "Model", system: "three-statement model" },
  { href: "/risk/", n: 5, nav: "Risk", system: "deviation + capital control" },
  { href: "/eval/", n: 6, nav: "Method", system: "backtest + calibration" },
  { href: "/agents/", n: 7, nav: "Agents", system: "agent roster" },
  { href: "/cost/", n: 8, nav: "Cost", system: "token allocation" },
  { href: "/integrity/", n: 9, nav: "Integrity", system: "provenance + point-in-time" },
];

export const TOTAL = SHEETS.length;

export function sheetOf(href: string): [number, number] {
  const found = SHEETS.find((s) => s.href === href);
  return [found?.n ?? 0, TOTAL];
}
