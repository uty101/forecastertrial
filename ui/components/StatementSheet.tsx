"use client";

import { useState } from "react";
import Link from "next/link";
import { Empty, Panel, Sheet } from "@/components/blueprint";
import StatementGrid from "@/components/StatementGrid";
import { useModel } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * One of the three statements, as its own sheet.
 *
 * Three sub-pages rather than one page with three tables, because that is how a
 * model is actually built: `IS`, `BS`, `CF` are separate worksheets and a reader
 * navigates between them following a link. Stacking them on one page turns the
 * cross-statement links into scroll positions, which is exactly the relationship
 * the layout exists to make visible.
 *
 * Quarterly and annual are separate views for the same reason Wall Street Prep
 * gives for keeping them on separate worksheets: commingled, it is too easy to
 * apply SUM(Q1:Q4) to a balance-sheet row, which produces a number that looks
 * like a year of cash generation and is meaningless.
 */

export const STATEMENTS = [
  { key: "income", slug: "income", nav: "Income statement" },
  { key: "cashflow", slug: "cash-flow", nav: "Cash flow" },
  { key: "balance", slug: "balance-sheet", nav: "Balance sheet" },
] as const;

export type StatementKey = (typeof STATEMENTS)[number]["key"];

function Tabs({ active }: { active: StatementKey | "overview" }) {
  const tabs = [
    { slug: "", nav: "Overview", key: "overview" as const },
    ...STATEMENTS.map((s) => ({ slug: s.slug, nav: s.nav, key: s.key })),
  ];
  return (
    <nav className="flex flex-wrap items-center gap-px border-b border-rule">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={`/model/${tab.slug}${tab.slug ? "/" : ""}`}
          className={[
            "tech border-b-2 px-3 py-2 text-[11px] no-underline transition-colors",
            tab.key === active
              ? "border-accent text-ink"
              : "border-transparent text-ink-3 hover:text-ink-2",
          ].join(" ")}
        >
          {tab.nav}
        </Link>
      ))}
    </nav>
  );
}

export function ModelTabs({ active }: { active: StatementKey | "overview" }) {
  return <Tabs active={active} />;
}

function Toggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: ReadonlyArray<{ value: T; label: string }>;
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="flex items-center gap-px">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={[
            "tech border px-3 py-1 text-[11px] transition-colors",
            value === option.value
              ? "border-accent bg-accent-soft text-ink"
              : "border-rule text-ink-3 hover:text-ink-2",
          ].join(" ")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * All three statements on one screen, switched rather than stacked.
 *
 * The sub-pages exist so a cross-statement link has somewhere to land and so a
 * statement can be deep-linked on its own. This is the other half: the model
 * page should show the model, not three cards promising it behind a click.
 *
 * Switched, not stacked, for the same reason the sub-pages exist — three
 * statements scrolling past each other is not how anyone reads one.
 */
export function StatementBrowser() {
  const model = useModel();
  const [statement, setStatement] = useState<StatementKey>("income");
  const [view, setView] = useState<"annual" | "quarter">("annual");

  if (!model?.grids) return null;
  const grid = model.grids[view][statement];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Toggle
          value={statement}
          onChange={setStatement}
          options={STATEMENTS.map((s) => ({ value: s.key, label: s.nav }))}
        />
        <div className="flex items-center gap-3">
          <Toggle
            value={view}
            onChange={setView}
            options={[
              { value: "annual", label: "fiscal years" },
              { value: "quarter", label: "quarters" },
            ]}
          />
          <Link
            href={`/model/${STATEMENTS.find((s) => s.key === statement)!.slug}/`}
            className="tech text-[11px] text-ink-3 no-underline hover:text-accent"
          >
            open as a sheet →
          </Link>
        </div>
      </div>
      <StatementGrid grid={grid} href="/model" />
    </div>
  );
}

export default function StatementSheet({
  statement,
}: {
  statement: StatementKey;
}) {
  const model = useModel();
  const [view, setView] = useState<"annual" | "quarter">("annual");
  const meta = STATEMENTS.find((s) => s.key === statement)!;

  if (!model?.grids) {
    return (
      <Sheet system={meta.nav.toLowerCase()} sheet={sheetOf("/model/")}>
        <Tabs active={statement} />
        <div className="pt-4">
          <Empty
            title="No statements yet"
            detail="The three statements are laid out from reported filings alone — no network, no API key, no model call. Build them from a dossier and they render here."
            command="uv run forecast model --dossier out/acquired/NVDA/2027Q2_2026-08-04"
          />
        </div>
      </Sheet>
    );
  }

  const grid = model.grids[view][statement];
  const first = grid.periods[0];
  const last = grid.periods[grid.periods.length - 1];

  return (
    <Sheet
      system={meta.nav.toLowerCase()}
      readout={[
        `${model.ticker}`,
        `${first?.label ?? "—"} → ${last?.label ?? "—"}`,
      ]}
      sheet={sheetOf("/model/")}
    >
      <div className="space-y-4">
        <Tabs active={statement} />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-px">
            {(["annual", "quarter"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setView(option)}
                className={[
                  "tech border px-3 py-1 text-[11px] transition-colors",
                  view === option
                    ? "border-accent bg-accent-soft text-ink"
                    : "border-rule text-ink-3 hover:text-ink-2",
                ].join(" ")}
              >
                {option === "annual" ? "fiscal years" : "quarters"}
              </button>
            ))}
          </div>
          <p className="max-w-[62ch] text-[11px] leading-relaxed text-ink-2">
            {view === "annual" ? (
              <>
                Income and cash-flow lines are the sum of their four quarters;
                balance-sheet lines are the closing balance. Never both. Which is
                why almost nothing on an annual income statement is{" "}
                <span className="text-model-actual">as reported</span> — we hold
                the quarters, so the year is reconstructed from them.
              </>
            ) : (
              `${grid.periods.length} quarters, as filed. Oldest left.`
            )}
          </p>
        </div>

        <StatementGrid grid={grid} href="/model" />

        {Object.keys(grid.annual_variances ?? {}).length > 0 && (
          <Panel
            label="quarters that do not sum to the filed year"
            hint="surfaced, not repaired"
          >
            <p className="mb-2 text-[12px] leading-relaxed text-ink-2">
              Where the four quarters we hold disagree with the annual figure the
              company itself filed. Not corrected — closing the gap would mean
              inventing a third number — but a line with a variance here is one to
              treat carefully.
            </p>
            <div className="scroll-x">
              <table className="w-full text-[12px]">
                <tbody>
                  {Object.entries(grid.annual_variances).flatMap(([item, years]) =>
                    Object.entries(years).map(([fy, [summed, filed]]) => (
                      <tr
                        key={`${item}-${fy}`}
                        className="border-b border-rule-2 last:border-0"
                      >
                        <td className="py-1 pr-3">{item}</td>
                        <td className="tech py-1 pr-3 text-ink-3">FY{fy}</td>
                        <td className="num py-1 pr-3 text-right">
                          {(summed / 1e6).toLocaleString(undefined, {
                            maximumFractionDigits: 0,
                          })}
                        </td>
                        <td className="num py-1 pr-3 text-right">
                          {(filed / 1e6).toLocaleString(undefined, {
                            maximumFractionDigits: 0,
                          })}
                        </td>
                        <td className="num py-1 text-right font-semibold text-negative">
                          {filed ? `${(((summed - filed) / Math.abs(filed)) * 100).toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </Sheet>
  );
}
