"use client";

import {
  Callout,
  Empty,
  Panel,
  Sheet,
  SheetFooter,
  Stat,
} from "@/components/blueprint";
import { ModelTabs } from "@/components/StatementSheet";
import { pct, signedPct, useModel, type DcfInput } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 04.4 — the valuation.
 *
 * Ordered against the grain on purpose. Every DCF ever presented leads with a
 * fair value and buries the assumptions in a tab nobody opens; this leads with
 * the REVERSE figure — the growth today's price requires — and treats the fair
 * value as a secondary read.
 *
 * That ordering is the honest one for this project. A fair value asserts we know
 * the company better than the market. The reverse figure asserts nothing: it
 * takes the price as given and states what it implies, which is a claim about
 * consensus, and consensus is the thing the whole system exists to find
 * structural weakness in.
 *
 * Every input is coloured by whether it was MEASURED from filings, taken from a
 * MARKET rate, or ASSUMED. Beta is assumed and says so — it needs a regression
 * against an index return series this system does not carry.
 */

const PROVENANCE: Record<DcfInput["provenance"], { cls: string; label: string }> = {
  measured: { cls: "text-model-actual", label: "measured from filings" },
  market: { cls: "text-model-link", label: "a market rate at the lock date" },
  assumed: { cls: "text-consensus", label: "assumed — not measured" },
};

const ASSUMPTION_LABELS: Record<string, string> = {
  risk_free: "Risk-free rate",
  equity_risk_premium: "Equity risk premium",
  beta: "Beta",
  cost_of_debt: "Cost of debt, pre-tax",
  tax_rate: "Effective tax rate",
  revenue_growth: "Revenue growth, year 1",
  ebit_margin: "Operating margin",
  da_pct: "D&A / revenue",
  capex_pct: "Capex / revenue",
  nwc_pct: "Working capital / revenue",
  terminal_growth: "Terminal growth",
};

const bn = (v: number) =>
  `${v < 0 ? "(" : ""}${Math.abs(v / 1e9).toLocaleString(undefined, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  })}${v < 0 ? ")" : ""}`;

const usd = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toFixed(2)}`;

export default function DcfPage() {
  const model = useModel();

  if (!model) {
    return (
      <Sheet system="discounted cash flow" sheet={sheetOf("/model/")}>
        <ModelTabs active="dcf" />
        <div className="pt-4">
          <Empty
            title="No valuation yet"
            detail="The DCF is built from the same filings as the three statements — no network, no API key, no model call."
            command="uv run forecast model --dossier out/acquired/NVDA/2027Q2_2026-08-04"
          />
        </div>
      </Sheet>
    );
  }

  const dcf = model.dcf;
  if (!dcf) {
    return (
      <Sheet system="discounted cash flow" sheet={sheetOf("/model/")}>
        <div className="space-y-4">
          <ModelTabs active="dcf" />
          <Empty
            title="No valuation for this company"
            // A missing DCF is a finding, not a blank. The reason is the content.
            detail={model.dcf_note || "The history is too thin to build one."}
          />
        </div>
      </Sheet>
    );
  }

  const rows = dcf.rows;
  const terminalHeavy = dcf.terminal_share > 0.75;

  return (
    <Sheet
      system="discounted cash flow"
      readout={[
        `${dcf.ticker}`,
        `WACC ${pct(dcf.wacc, 2)} · g ${pct(dcf.terminal_growth, 1)}`,
      ]}
      sheet={sheetOf("/model/")}
      footer={
        <SheetFooter
          cells={[
            ["wacc", pct(dcf.wacc, 2)],
            ["terminal", `${pct(dcf.terminal_share, 0)} of EV`],
            [
              "implied growth",
              dcf.implied_growth != null ? pct(dcf.implied_growth, 1) : "—",
            ],
            ["method", "unlevered FCF, Gordon terminal"],
          ]}
        />
      }
    >
      <div className="space-y-5">
        <ModelTabs active="dcf" />

        {/* The reverse DCF, first and largest. It is the only figure here that
            makes no claim about fair value. */}
        <Panel label="reverse DCF" hint="what today's price requires">
          {dcf.implied_growth != null ? (
            <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
              <div>
                <div className="num text-[42px] leading-none font-semibold text-accent">
                  {pct(dcf.implied_growth, 1)}
                </div>
                <div className="tech mt-1 text-[10.5px] text-ink-3">
                  year-one revenue growth, fading to {pct(dcf.terminal_growth, 1)}
                </div>
              </div>
              <p className="max-w-[52ch] text-[12.5px] leading-relaxed text-ink-2">
                {dcf.implied_note}
              </p>
            </div>
          ) : (
            <p className="text-[12.5px] leading-relaxed text-ink-2">
              {dcf.implied_note}
            </p>
          )}
        </Panel>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
          <Panel
            label="free cash flow"
            hint={`${dcf.forecast_years} years, ${
              dcf.mid_year ? "mid-year discounting" : "year-end discounting"
            }`}
          >
            <div className="scroll-x">
              <table className="min-w-full text-[11.5px]">
                <thead>
                  <tr className="border-b border-rule tech text-[10px] text-ink-3">
                    <th className="py-1.5 pr-3 text-left font-normal">$bn</th>
                    {rows.map((row) => (
                      <th
                        key={row.year}
                        className="num px-2 py-1.5 text-right font-normal"
                      >
                        {row.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {/* The growth row is what shows this is a projection and not an
                      extrapolation: it fades to the terminal rate by the final
                      year, so the handover to the Gordon formula is continuous. */}
                  <tr className="italic text-ink-2">
                    <td className="py-1 pr-3">growth</td>
                    {rows.map((row) => (
                      <td key={row.year} className="num px-2 py-1 text-right">
                        {pct(row.growth, 1)}
                      </td>
                    ))}
                  </tr>
                  {(
                    [
                      ["Revenue", "revenue", false],
                      ["EBIT", "ebit", false],
                      ["NOPAT", "nopat", false],
                      ["+ D&A", "da", false],
                      ["− Capex", "capex", true],
                      ["− ΔWorking capital", "delta_nwc", true],
                      ["Free cash flow", "fcf", false],
                    ] as const
                  ).map(([label, key, negate]) => (
                    <tr
                      key={key}
                      className={
                        key === "fcf"
                          ? "border-t border-rule font-semibold"
                          : "border-b border-rule-2"
                      }
                    >
                      <td className="py-1 pr-3">{label}</td>
                      {rows.map((row) => (
                        <td key={row.year} className="num px-2 py-1 text-right">
                          {bn(negate ? -Math.abs(row[key]) : row[key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr className="italic text-ink-2">
                    <td className="py-1 pr-3">discount factor</td>
                    {rows.map((row) => (
                      <td key={row.year} className="num px-2 py-1 text-right">
                        {row.discount_factor.toFixed(3)}
                      </td>
                    ))}
                  </tr>
                  <tr className="border-t border-rule border-b-[3px] border-double font-semibold">
                    <td className="py-1 pr-3">Present value</td>
                    {rows.map((row) => (
                      <td key={row.year} className="num px-2 py-1 text-right">
                        {bn(row.present_value)}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="space-y-3">
            <Panel label="bridge to equity" hint="$bn except per share">
              <table className="w-full text-[12px]">
                <tbody>
                  {(
                    [
                      ["PV of forecast cash flow", bn(dcf.pv_explicit), false],
                      ["PV of terminal value", bn(dcf.pv_terminal), false],
                      ["Enterprise value", bn(dcf.enterprise_value), true],
                      ["Less: net debt", bn(-dcf.net_debt), false],
                      ["Equity value", bn(dcf.equity_value), true],
                      [
                        "Diluted shares",
                        (dcf.shares / 1e6).toLocaleString(undefined, {
                          maximumFractionDigits: 0,
                        }),
                        false,
                      ],
                    ] as const
                  ).map(([label, figure, strong]) => (
                    <tr
                      key={label}
                      className={
                        strong
                          ? "border-t border-rule font-semibold"
                          : "border-b border-rule-2"
                      }
                    >
                      <td className="py-1 pr-3">{label}</td>
                      <td className="num py-1 text-right">{figure}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <Stat label="value per share" value={usd(dcf.value_per_share)} />
                <Stat
                  label="market price"
                  value={usd(dcf.market_price)}
                  sub={dcf.upside != null ? signedPct(dcf.upside) : undefined}
                />
              </div>
            </Panel>

            <Panel
              label="terminal value"
              hint={`${pct(dcf.terminal_share, 0)} of enterprise value`}
            >
              <p className="text-[12px] leading-relaxed text-ink-2">
                {terminalHeavy ? (
                  <>
                    Most of the answer is the perpetuity. At this share the{" "}
                    {dcf.forecast_years} projected years are close to decoration
                    and the model is really one Gordon-growth division — read the
                    sensitivity grid, not the point estimate.
                  </>
                ) : (
                  <>
                    The projected years carry {pct(1 - dcf.terminal_share, 0)} of
                    enterprise value, so the explicit forecast is doing real work
                    rather than dressing a perpetuity calculation.
                  </>
                )}
              </p>
            </Panel>
          </div>
        </div>

        {/* Provenance. The only thing separating a DCF from a number-shaped
            opinion, and normally buried in a tab nobody opens. */}
        <div className="grid gap-3 lg:grid-cols-[340px_minmax(0,1fr)]">
          <Panel label="assumptions" hint="measured, market, or invented">
            <table className="w-full text-[12px]">
              <tbody>
                {Object.entries(ASSUMPTION_LABELS)
                  .filter(([key]) => key in dcf.assumptions)
                  .map(([key, label]) => {
                    const input = dcf.assumptions[key];
                    const style = PROVENANCE[input.provenance];
                    return (
                      <tr
                        key={key}
                        className="border-b border-rule-2 last:border-0"
                        title={`${style.label} — ${input.note}`}
                      >
                        <td className="py-1 pr-3">{label}</td>
                        <td className={`num py-1 pr-3 text-right ${style.cls}`}>
                          {key === "beta"
                            ? input.value.toFixed(2)
                            : pct(input.value, 2)}
                        </td>
                        <td className="tech py-1 text-right text-[9.5px] text-ink-3">
                          {input.provenance}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            <div className="tech mt-2 flex gap-3 border-t border-rule-2 pt-2 text-[10px]">
              <span className="text-model-actual">measured</span>
              <span className="text-model-link">market</span>
              <span className="text-consensus">assumed</span>
            </div>
          </Panel>

          <Panel
            label="sensitivity"
            hint="value per share across WACC and terminal growth"
          >
            <div className="scroll-x">
              <table className="min-w-full text-[11.5px]">
                <thead>
                  <tr className="border-b border-rule tech text-[10px] text-ink-3">
                    <th className="py-1.5 pr-3 text-left font-normal">
                      WACC ╲ g
                    </th>
                    {dcf.sensitivity.growth_steps.map((step) => (
                      <th key={step} className="num px-2 py-1.5 text-right font-normal">
                        {pct(dcf.terminal_growth + step, 2)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dcf.sensitivity.values.map((row, i) => (
                    <tr key={i} className="border-b border-rule-2 last:border-0">
                      <td className="num py-1 pr-3 tech text-ink-3">
                        {pct(dcf.wacc + dcf.sensitivity.wacc_steps[i], 2)}
                      </td>
                      {row.map((cell, j) => {
                        const centre =
                          dcf.sensitivity.wacc_steps[i] === 0 &&
                          dcf.sensitivity.growth_steps[j] === 0;
                        const above =
                          cell != null &&
                          dcf.market_price != null &&
                          cell > dcf.market_price;
                        return (
                          <td
                            key={j}
                            className={[
                              "num px-2 py-1 text-right",
                              centre ? "bg-accent-soft font-semibold text-ink" : "",
                              cell == null
                                ? "text-ink-3"
                                : above
                                  ? "text-structure"
                                  : "text-negative",
                            ].join(" ")}
                            // The blank cells are where WACC crosses terminal
                            // growth and the denominator inverts. A number there
                            // would be nonsense with the same weight as the rest.
                            title={
                              cell == null
                                ? "WACC at or below terminal growth — the Gordon denominator inverts"
                                : undefined
                            }
                          >
                            {cell == null ? "—" : usd(cell)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 border-t border-rule-2 pt-2 text-[11px] leading-relaxed text-ink-2">
              Green is above the market price, red below. Move the discount rate
              100bp and the answer moves 15–25%, which is why a point estimate on
              its own overstates what the method can do.
            </p>
          </Panel>
        </div>

        {dcf.warnings.length > 0 && (
          <Callout label="what this valuation is resting on" tone="accent">
            <ul className="space-y-1.5">
              {dcf.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </Callout>
        )}

        <Callout label="what a DCF is not doing here" tone="ink">
          This system is scored on a quarterly EPS number, and nothing on this
          sheet moves it. The forward valuation is the weaker half — it asserts we
          know the company better than the market does, and we do not. The reverse
          figure asserts nothing: it takes the price as given and states what
          growth it requires, which is a claim about consensus, and consensus is
          what the rest of the pipeline exists to find structural weakness in.
        </Callout>
      </div>
    </Sheet>
  );
}
