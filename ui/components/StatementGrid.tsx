"use client";

import { useState } from "react";
import Link from "next/link";
import type { GridPayload, GridRow, GridCell, GridPeriod } from "@/lib/data";

/**
 * A statement laid out the way a three-statement model is laid out.
 *
 * This is deliberately not "a table of numbers with nice styling". Every
 * convention below is one a person who reads models for a living scans for
 * without thinking about it, and getting them wrong is the difference between a
 * screen they can audit in ten seconds and one they have to be walked through.
 *
 *   COLOUR IS WHAT THE CELL CONTAINS, never what the number means. Blue is a
 *   figure keyed from a filing. Black is a formula over cells on this statement.
 *   Green is a link from another statement. That is the whole code, and it is
 *   what lets you see at a glance which numbers we were told and which we worked
 *   out. Negatives are NOT red — red means something else in a model, and using
 *   it for negatives destroys the code.
 *
 *   NEGATIVES IN PARENTHESES. `(45.2)`, never `-45.2`.
 *
 *   SUBTOTALS CARRY A TOP BORDER, not a bottom one. In Excel that is because a
 *   top border survives a row being inserted into the block above it; here it is
 *   because a reader's eye is trained on it.
 *
 *   TOTALS ARE DOUBLE-UNDERLINED. The accounting double rule, for the figures a
 *   reader stops at: total assets, net income, ending cash.
 *
 *   RATIO ROWS ARE ITALIC AND INDENTED, directly beneath the line they describe,
 *   and never inside a sum.
 *
 *   TABULAR FIGURES AND A FIXED DECIMAL COUNT, so digits line up down a column.
 *   A column of numbers you cannot scan vertically is a column of numbers you
 *   will not check.
 *
 * The first column is frozen. Scrolling seventy quarters sideways is useless if
 * the labels leave with them.
 */

const FMT: Record<string, (v: number) => string> = {
  usd: (v) => {
    const millions = v / 1e6;
    const shown = Math.abs(millions).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
    return millions < 0 ? `(${shown})` : shown;
  },
  pct: (v) => {
    const shown = `${Math.abs(v * 100).toFixed(1)}%`;
    return v < 0 ? `(${shown})` : shown;
  },
  days: (v) => v.toFixed(0),
  shares: (v) => (v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 0 }),
  per_share: (v) => {
    const shown = Math.abs(v).toFixed(2);
    return v < 0 ? `(${shown})` : shown;
  },
  ratio: (v) => `${v.toFixed(1)}x`,
};

/** Font colour by what the cell contains. See the header comment. */
const ORIGIN_CLASS: Record<string, string> = {
  actual: "text-model-actual",
  link: "text-model-link",
  derived: "text-ink",
};

const ORIGIN_LABEL: Record<string, string> = {
  actual: "as reported in the filing",
  link: "linked from another statement",
  derived: "calculated on this statement",
};

function rowClass(row: GridRow): string {
  switch (row.style) {
    case "header":
      return "font-semibold text-ink pt-3";
    case "subtotal":
      return "font-semibold border-t border-rule";
    case "total":
      return "font-semibold border-t border-rule border-b-[3px] border-double border-b-rule";
    case "memo":
      return "italic text-ink-2";
    case "check":
      return "border-t border-rule text-[11px]";
    default:
      return "";
  }
}

function Cell({
  cell,
  row,
  period,
  filings,
  boundary,
}: {
  cell: GridCell | undefined;
  row: GridRow;
  period: GridPeriod;
  filings: GridPayload["filings"];
  /** First forecast column: carries the rule dividing reported from projected. */
  boundary: boolean;
}) {
  const zone = [
    boundary ? "border-l-2 border-l-accent" : "",
    period.estimate ? "bg-accent-soft/40" : "",
  ].join(" ");
  if (row.style === "header") return <td className={zone} />;
  if (!cell || cell.v == null) {
    // A dash, not a zero. "Not reported" and "reported as nothing" are different
    // facts and a model that renders them identically has lost one of them.
    return (
      <td className={`num px-2 py-[3px] text-right text-ink-3 ${zone}`}>
        &mdash;
      </td>
    );
  }

  const origin = cell.o ?? "derived";
  const filing = cell.s != null ? filings[cell.s] : undefined;
  const format = FMT[row.unit] ?? FMT.usd;
  const isCheck = row.style === "check";
  const broken = isCheck && Math.abs(cell.v) > 1;

  const title = [
    `${row.label} · ${period.label}`,
    ORIGIN_LABEL[origin],
    filing ? `${filing.form} filed ${filing.filed}` : null,
    cell.n,
    period.kind === "annual" && !period.complete
      ? `${period.quarters} of 4 quarters reported`
      : null,
  ]
    .filter(Boolean)
    .join(" — ");

  return (
    <td
      className={[
        "num px-2 py-[3px] text-right whitespace-nowrap",
        isCheck
          ? broken
            ? "bg-negative-soft font-semibold text-negative"
            : "text-ink-3"
          : ORIGIN_CLASS[origin],
        period.kind === "annual" && !period.complete ? "opacity-55" : "",
        zone,
      ].join(" ")}
      title={title}
    >
      {isCheck && !broken ? "0" : format(cell.v)}
    </td>
  );
}

export default function StatementGrid({
  grid,
  href,
}: {
  grid: GridPayload;
  /** Route prefix for cross-statement links, e.g. "/model". */
  href: string;
}) {
  const [focus, setFocus] = useState<string | null>(null);

  return (
    <div className="border border-rule bg-paper">
      {/* Units belong in a header block, not on every cell. */}
      <div className="flex items-baseline justify-between border-b border-rule px-3 py-2">
        <div>
          <div className="text-[13px] font-semibold text-ink">
            {grid.ticker} — {grid.title}
          </div>
          <div className="tech text-[10.5px] italic text-ink-3">
            ($ in millions, except per-share data · shares in millions)
          </div>
        </div>
        <div className="tech flex gap-3 text-[10px] text-ink-3">
          <span className="text-model-actual">as reported</span>
          <span className="text-ink">calculated</span>
          <span className="text-model-link">linked</span>
          {grid.periods.some((p) => p.estimate) && (
            <span className="border-l border-accent pl-2 text-accent">
              projected
            </span>
          )}
        </div>
      </div>

      <div className="scroll-x">
        <table className="min-w-full border-collapse text-[11.5px]">
          <thead>
            <tr className="border-b border-rule bg-paper-2">
              <th className="sticky left-0 z-10 min-w-[280px] bg-paper-2 px-3 py-1.5 text-left font-normal tech text-[10px] text-ink-3">
                {grid.periods[0]?.kind === "annual" ? "fiscal year" : "quarter"}
              </th>
              {grid.periods.map((period, i) => (
                <th
                  key={period.id}
                  className={[
                    "num px-2 py-1.5 text-right font-semibold text-[10.5px] whitespace-nowrap",
                    period.kind === "annual" && !period.complete
                      ? "text-ink-3 italic"
                      : "text-ink",
                    // The A/E boundary. A model sheet has exactly one division
                    // that matters more than the others, and this is it: where
                    // the filings stop and the assumptions start.
                    period.estimate && !grid.periods[i - 1]?.estimate
                      ? "border-l-2 border-l-accent"
                      : "",
                    period.estimate ? "bg-accent-soft/40" : "",
                  ].join(" ")}
                  // A part-finished year that renders identically to a full one
                  // is how a 25% figure gets read as a 100% one.
                  title={
                    period.complete
                      ? undefined
                      : `${period.quarters} of 4 quarters reported`
                  }
                >
                  {period.label}
                  {!period.complete && <span className="text-negative">*</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr
                key={row.id}
                className={[
                  rowClass(row),
                  focus === row.id ? "bg-accent-soft" : "hover:bg-paper-2",
                ].join(" ")}
                onMouseEnter={() => setFocus(row.id)}
                onMouseLeave={() => setFocus(null)}
              >
                <th
                  scope="row"
                  className={[
                    "sticky left-0 z-10 px-3 py-[3px] text-left font-normal",
                    focus === row.id ? "bg-accent-soft" : "bg-paper",
                    row.style === "header" ? "font-semibold" : "",
                  ].join(" ")}
                  style={{ paddingLeft: 12 + row.level * 14 }}
                  title={row.note || undefined}
                >
                  <span className={row.style === "memo" ? "text-ink-2" : ""}>
                    {row.label}
                  </span>
                  {/* Where this line crosses a statement boundary. A reader's
                      first question about a linked cell is where it comes from,
                      so the answer travels with the row rather than living in a
                      legend nobody opens. */}
                  {row.links?.map((link) => (
                    <Link
                      key={`${link.statement}-${link.row}-${link.direction}`}
                      href={`${href}/${
                        { income: "income", cashflow: "cash-flow", balance: "balance-sheet" }[
                          link.statement
                        ]
                      }/#${link.row}`}
                      className="ml-1.5 text-[9.5px] text-model-link no-underline hover:underline"
                      title={`${link.direction === "to" ? "flows to" : "comes from"} ${
                        link.statement
                      } · ${link.note}`}
                    >
                      {link.direction === "to" ? "→" : "←"}
                    </Link>
                  ))}
                </th>
                {grid.periods.map((period, i) => (
                  <Cell
                    key={period.id}
                    cell={row.cells[period.id]}
                    row={row}
                    period={period}
                    filings={grid.filings}
                    boundary={
                      Boolean(period.estimate) && !grid.periods[i - 1]?.estimate
                    }
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {grid.periods.some((p) => !p.complete) && (
        <p className="border-t border-rule px-3 py-1.5 text-[10.5px] text-ink-2">
          <span className="text-negative">*</span> a fiscal year with fewer than
          four quarters reported. Flow lines are the quarters filed so far, not a
          year; growth against it is suppressed rather than shown as a decline.
        </p>
      )}
    </div>
  );
}
