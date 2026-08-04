"use client";

import {
  Callout,
  Empty,
  Lede,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import {
  money,
  pct,
  signedPct,
  useModel,
  useResult,
  usd4,
  type QuarterCheck,
} from "@/lib/data";
import { ModelTabs, STATEMENTS } from "@/components/StatementSheet";
import { sheetOf } from "@/lib/sheets";
import Link from "next/link";

/**
 * SHEET 04 — the model.
 *
 * Rendered as actual statements rather than a cell dump, because judges
 * recognise an income statement and do not recognise a dependency graph.
 *
 * Every figure declares whether it is SOURCED — hover reveals the verbatim quote
 * and the filing. That is the provenance design made visible: a cell that traces
 * to a filing looks different from one that doesn't, on the sheet, without
 * anyone having to take it on trust.
 */

interface Row {
  key: string;
  label: string;
  unit: string;
  value: number;
  is_input: boolean;
  sourced: boolean;
  source_uri?: string | null;
  quote?: string | null;
  note?: string | null;
}

function Statement({
  title,
  rows,
  index,
}: {
  title: string;
  rows: Row[];
  index: number;
}) {
  return (
    <Panel label={title} index={index}>
      <div className="scroll-x">
        <table className="w-full text-[12.5px]">
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className="border-b border-rule-2 last:border-0"
                title={row.quote ?? row.note ?? undefined}
              >
                <td className="py-1.5 pr-3">
                  <span className={row.is_input ? "" : "font-semibold"}>
                    {row.label}
                  </span>
                </td>
                <td className="py-1.5 pr-2 text-right">
                  {row.sourced ? (
                    row.source_uri ? (
                      <a
                        href={row.source_uri}
                        target="_blank"
                        rel="noreferrer"
                        className="tech text-structure hover:underline"
                      >
                        sourced
                      </a>
                    ) : (
                      <span className="tech text-structure">sourced</span>
                    )
                  ) : row.is_input ? (
                    <span className="tech text-accent" title={row.note ?? undefined}>
                      noted
                    </span>
                  ) : (
                    <span className="tech text-ink-3">derived</span>
                  )}
                </td>
                <td className="num py-1.5 text-right font-semibold">
                  {row.unit === "USD/share"
                    ? usd4(row.value)
                    : row.unit === "fraction"
                      ? `${(row.value * 100).toFixed(1)}%`
                      : money(row.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/**
 * Stage D's self-check, and the most useful number on this sheet.
 *
 * Each past quarter is modelled from its OWN reported revenue — the one input a
 * forecast would have had to supply — so everything else comes from quarters
 * before it. What comes back is therefore the model's structural error, cleanly
 * separated from any lens's forecasting error, and it is a measurement rather
 * than an assertion.
 *
 * The bias column matters as much as the error. A model that is 4% out in both
 * directions is noisy; one that is 4% low every quarter has a broken link, and
 * the absolute figure alone cannot tell you which.
 */
function Reproduction({
  checks,
  median,
  bias,
  skipped,
}: {
  checks: QuarterCheck[];
  median: number | null;
  bias: number | null;
  skipped: string[];
}) {
  return (
    <Panel
      label="reproduction check"
      hint="each quarter modelled from its own reported revenue"
    >
      {checks.length === 0 ? (
        <p className="text-[12.5px] leading-relaxed text-ink-2">
          No quarter could be reproduced. Every attempt is listed below with its
          reason — an unreproducible model is a finding, not a blank.
        </p>
      ) : (
        <div className="scroll-x">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-rule text-left tech text-ink-3">
                <th className="py-1.5 pr-3 font-normal">quarter</th>
                <th className="py-1.5 pr-3 text-right font-normal">modelled</th>
                <th className="py-1.5 pr-3 text-right font-normal">reported</th>
                <th className="py-1.5 text-right font-normal">error</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((check) => (
                <tr
                  key={check.period}
                  className="border-b border-rule-2 last:border-0"
                >
                  <td className="py-1.5 pr-3 tech">{check.period}</td>
                  <td className="num py-1.5 pr-3 text-right">
                    {usd4(check.modelled_eps)}
                  </td>
                  <td className="num py-1.5 pr-3 text-right">
                    {usd4(check.actual_eps)}
                  </td>
                  <td className="num py-1.5 text-right font-semibold">
                    {check.eps_error == null ? (
                      <span className="tech text-ink-3">no comparable EPS</span>
                    ) : (
                      signedPct(check.eps_error)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {median != null && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Stat label="median abs error" value={pct(median)} />
          <Stat label="bias" value={signedPct(bias)} accent={
            bias != null && median != null && Math.abs(bias) > median * 0.75
          } />
        </div>
      )}

      {skipped.length > 0 && (
        // As prominent as what worked. A quarter dropped without a reason makes
        // the median look better than it is.
        <div className="mt-3 border-t border-rule-2 pt-2">
          <p className="tech mb-1 text-ink-3">not reproduced</p>
          <ul className="space-y-1 text-[11.5px] leading-relaxed text-ink-2">
            {skipped.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

const RATIO_LABELS: Record<string, string> = {
  gross_margin: "gross margin",
  opex_pct_revenue: "opex / revenue",
  da_pct_revenue: "D&A / revenue",
  capex_pct_revenue: "capex / revenue",
  tax_rate: "effective tax rate",
};

function RatioBase({
  ratios,
  notes,
}: {
  ratios: Record<string, number>;
  notes: Record<string, string>;
}) {
  const shown = Object.keys(RATIO_LABELS).filter((k) => k in ratios);
  return (
    <Panel label="ratio base" hint="medians a projection moves">
      <table className="w-full text-[12.5px]">
        <tbody>
          {shown.map((key) => (
            <tr
              key={key}
              className="border-b border-rule-2 last:border-0"
              // The window each median was taken over. A median with no window
              // is an assertion; the note is what makes it arguable.
              title={notes[key] ?? notes[key.replace("_pct_revenue", "")] ?? undefined}
            >
              <td className="py-1.5 pr-3">{RATIO_LABELS[key]}</td>
              <td className="num py-1.5 text-right font-semibold">
                {(ratios[key] * 100).toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export default function ModelScreen() {
  const result = useResult();
  // Stage D is deterministic and free, so the sheet renders from `model.json`
  // alone when no forecast run exists. Requiring a seven-lens run to look at a
  // three-statement model would make the cheapest stage the hardest to see.
  const model = useModel();

  if (!result && !model) {
    return (
      <Sheet system="three-statement model" sheet={sheetOf("/model/")}>
        <Empty
          title="No model yet"
          detail="The three-statement model is built deterministically from a dossier — no network, no API key, no model call. Build one and it renders here without a forecast run."
          command="uv run forecast model --dossier out/acquired/NVDA/2027Q2_2026-08-04"
        />
      </Sheet>
    );
  }

  const f = result?.forecast ?? null;
  // The run's copy wins when there is one — it is the model the forecast was
  // actually built on. `model.json` is what a standalone stage-D run wrote, and
  // is the only source when no forecast exists.
  const statements = ((result?.trace?.statements as {
    income_statement?: Row[];
    cash_flow?: Row[];
    balance_sheet?: Row[];
  } | null) ?? model?.statements ?? null);
  const bridge = (result?.trace?.bridge ?? null) as Array<{
    label: string;
    per_share: number;
    source_uri?: string | null;
    quote?: string | null;
    recurring?: boolean;
    quarters_recurring?: number;
  }> | null;
  const balance =
    (result?.trace?.balance_check as string | undefined) ?? model?.balance_detail;
  const evidence = (result?.trace?.evidence ?? {}) as {
    claims?: number;
    deduped?: number;
  };
  const citations = (result?.trace?.citations ?? {}) as {
    verified?: number;
    failed?: number;
  };
  const balanced = balance ? !balance.includes("DOES NOT") : null;
  // A stage-D-only sheet still has a company and a quarter to name; what it does
  // not have is a locked as-of, because nothing was forecast.
  const readout: [string, string] = f
    ? [`${f.ticker} ${f.period}`, `LOCKED ${f.as_of}`]
    : [
        `${model?.ticker ?? "—"} ${model?.forecast_period ?? ""}`.trim(),
        `BASE ${model?.base_period ?? "—"}`,
      ];

  return (
    <Sheet
      system="three-statement model"
      readout={readout}
      sheet={sheetOf("/model/")}
      footer={
        <SheetFooter
          cells={[
            ["engine", "topological sort, ~150 lines, no model"],
            ["balance", balanced === null ? "not built" : balanced ? "ties" : "DOES NOT TIE"],
            [
              "own error",
              model?.median_abs_eps_error == null
                ? "not measured"
                : `${pct(model.median_abs_eps_error)} median abs`,
            ],
            ["basis", "both carried; consensus is non-GAAP"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <ModelTabs active="overview" />
        <SyntheticBanner trace={result?.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Lede>
            A model built by a language model is a model you cannot trust. The links between the statements are pure arithmetic, so they are code — and the balance check is a hard gate, not a warning.
          </Lede>

          <StatusPanel
            title="model status"
            state={
              balanced === null ? "not built" : balanced ? "balanced" : "unbalanced"
            }
            detail={balanced ? "assets = liabilities + equity" : undefined}
            fraction={balanced ? 1 : balanced === false ? 0.3 : 0}
            tone={balanced ? "done" : balanced === false ? "failed" : "idle"}
            rows={[
              ["base quarter", model?.base_period ?? "—"],
              ["projecting", model?.forecast_period ?? "—"],
              ["quarters reproduced", model?.checks.length ?? "—"],
              ["claims in store", evidence.claims ?? "—"],
              ["citations failed", citations.failed ?? "—"],
            ]}
          />
        </div>

        {model?.grids && (
          // The three statements are their own sheets, because that is how a
          // model is built: separate worksheets, and a reader navigates between
          // them following a link. Stacking them on one page would turn the
          // cross-statement links into scroll positions.
          <div className="grid gap-3 sm:grid-cols-3">
            {STATEMENTS.map((s) => {
              const g = model.grids!.annual[s.key];
              return (
                <Link
                  key={s.key}
                  href={`/model/${s.slug}/`}
                  className="group border border-rule bg-paper-2 px-4 py-3 no-underline transition-colors hover:border-accent"
                >
                  <div className="text-[13px] font-semibold text-ink group-hover:text-accent">
                    {s.nav}
                  </div>
                  <div className="tech mt-1 text-[10.5px] text-ink-3">
                    {g.rows.filter((r) => r.style !== "header").length} lines ·{" "}
                    {g.periods.length} fiscal years ·{" "}
                    {model.grids!.quarter[s.key].periods.length} quarters
                  </div>
                  <div className="tech mt-0.5 text-[10.5px] text-ink-3">
                    {g.periods[0]?.label} → {g.periods[g.periods.length - 1]?.label}
                  </div>
                </Link>
              );
            })}
          </div>
        )}

        {model && (
          <div className="grid gap-3 lg:grid-cols-[320px_minmax(0,1fr)]">
            <RatioBase ratios={model.ratios} notes={model.notes} />
            <Reproduction
              checks={model.checks}
              median={model.median_abs_eps_error}
              bias={model.bias}
              skipped={model.skipped}
            />
          </div>
        )}

        {!statements ? (
          <Empty
            title="This run did not build a three-statement model"
            detail="The model is assembled when acquisition returns enough linked inputs — revenue, margins, working capital movements, capex and share count. On a thin evidence set the pipeline forecasts without it rather than inventing the missing lines."
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {statements.income_statement && (
              <Statement
                title="income statement"
                rows={statements.income_statement}
                index={1}
              />
            )}
            {statements.cash_flow && (
              <Statement title="cash flow" rows={statements.cash_flow} index={2} />
            )}
            {statements.balance_sheet && (
              <Statement
                title="balance sheet"
                rows={statements.balance_sheet}
                index={3}
              />
            )}
          </div>
        )}

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Panel
            label="GAAP ↔ non-GAAP bridge"
            hint="the median DJIA gap was 31% in one recent quarter"
          >
            {!bridge ? (
              <p className="text-[12.5px] leading-relaxed text-ink-2">
                No verified bridge for this run. The forecast is reported on
                non-GAAP only, and{" "}
                <code className="font-mono text-[11.5px]">eps_gaap</code> is left
                null rather than converted with an assumed ratio — if we do not
                have this company&rsquo;s reconciling items we do not know its
                gap, and assuming the sector median is how a forecast ends up
                confidently 31% wrong.
              </p>
            ) : (
              <div className="scroll-x">
                <table className="w-full text-[12.5px]">
                  <tbody>
                    {bridge.map((item, i) => (
                      <tr
                        key={`${item.label}-${i}`}
                        className="border-b border-rule-2 last:border-0"
                        title={item.quote ?? undefined}
                      >
                        <td className="py-1.5 pr-3">{item.label}</td>
                        <td className="py-1.5 pr-3">
                          {item.recurring && (
                            <Pill tone="warn">
                              recurring {item.quarters_recurring}q — not unusual
                            </Pill>
                          )}
                        </td>
                        <td className="num py-1.5 text-right font-semibold">
                          {usd4(item.per_share)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <div className="space-y-3">
            <Callout label="the trap that kills silently" tone="accent">
              Consensus is non-GAAP. XBRL is GAAP. Forecast one and get scored on
              the other and every company misses by 12–30% in the same direction
              every quarter — which looks like bad modelling rather than a flag
              set wrong.
            </Callout>
            <Panel label="provenance">
              <div className="grid grid-cols-2 gap-3">
                <Stat label="claims" value={String(evidence.claims ?? "—")} />
                <Stat
                  label="failed cites"
                  value={String(citations.failed ?? "—")}
                  accent={(citations.failed ?? 0) > 0}
                />
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </Sheet>
  );
}
