"use client";

import { useState } from "react";

import LensConstellation from "@/components/LensConstellation";
import {
  Callout,
  Display,
  Empty,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  StageStrip,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import { eps, pct, useResult } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";
import type { LensOutput } from "@/lib/types";

/**
 * SHEET 03 — the reasoning trace. The sheet that wins on substance.
 *
 * Each lens expands to its thesis AND its counterargument, because the cases
 * were argued against before anything was compared. Every claim is listed by id.
 *
 * FAILED CITATIONS ARE SHOWN, NOT HIDDEN. "We verify every citation" is only a
 * meaningful statement if the failures are visible; a sheet that quietly omitted
 * them would be claiming the opposite of what it does.
 */

/** The challenge process, in the system's own terms. */
const PROCESS = [
  {
    n: 1,
    title: "Argue",
    detail: "Each case developed into its strongest honest form",
  },
  {
    n: 2,
    title: "Attack",
    detail: "The same case argued against, hard and in good faith",
  },
  {
    n: 3,
    title: "Survive",
    detail: "Self-reported confidence replaced by what held up",
  },
  {
    n: 4,
    title: "Weigh",
    detail: "Judged on materiality and evidence quality — never on count",
  },
];

export default function ReasoningScreen() {
  const result = useResult();
  const [open, setOpen] = useState<string | null>(null);

  if (!result) {
    return (
      <Sheet system="lens + challenge trace" sheet={sheetOf("/reasoning/")}>
        <Empty
          title="No reasoning trace yet"
          detail="This sheet reads the lens outputs from out/results.json."
          command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
        />
      </Sheet>
    );
  }

  const f = result.forecast;
  const citations = (result.trace?.citations ?? {}) as {
    verified?: number;
    failed?: number;
  };
  const dropped = (f.dropped_lenses ?? {}) as Record<string, string>;
  const droppedList = Object.entries(dropped);
  const lenses = (f.lenses ?? []) as LensOutput[];
  const challenged = lenses.filter((l) => l.counterargument).length;

  return (
    <Sheet
      system="lens + challenge trace"
      readout={[`${f.ticker} ${f.period}`, `LOCKED ${f.as_of}`]}
      sheet={sheetOf("/reasoning/")}
      footer={
        <SheetFooter
          cells={[
            ["lenses kept", `${lenses.length} of 7`],
            ["challenged", `${challenged} argued against`],
            ["citations", `${citations.verified ?? 0} verified · ${citations.failed ?? 0} failed`],
            ["aggregation", "impact-weighted, never vote-weighted"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <SyntheticBanner trace={result.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Display kicker="Every case is argued properly and then argued against, before anything is compared. Comparing raw findings and taking the plurality rewards the finding that is easiest to reach, not the one that matters.">
            Then every case
            <br />
            <Green>gets attacked.</Green>
          </Display>

          <StatusPanel
            title="challenge status"
            state={challenged === lenses.length ? "complete" : "partial"}
            detail={`${lenses.length} cases · ${droppedList.length} dropped`}
            fraction={lenses.length ? challenged / lenses.length : 0}
            tone={challenged === lenses.length ? "done" : "running"}
            rows={[
              ["cases in review", lenses.length],
              ["argued against", challenged],
              ["citations verified", citations.verified ?? 0],
              ["citations failed", citations.failed ?? 0],
            ]}
          />
        </div>

        <StageStrip stages={PROCESS.map((p) => ({ ...p, state: "done" as const }))} />

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Panel
            label="the ensemble"
            hint="seven lenses, one edge each — to the judge, never to each other"
          >
            <LensConstellation lenses={lenses} dropped={dropped} />
          </Panel>

          <div className="space-y-3">
            <Callout label="why no mesh" tone="accent">
              The obvious way to draw a multi-agent system is every agent
              debating every other. That is the architecture this one was
              designed <em>against</em>: lenses that see each other converge, and
              converging rebuilds consensus, which scores zero. Diversity is the
              asset.
            </Callout>
            <Callout label="what agreement is worth">
              Very little. The lenses read overlapping source documents, so their
              errors are correlated — five agreeing is about as likely to be
              wrong as one. Six lenses on a weak signal lose to one carrying the
              company&rsquo;s own guidance with a quote.
            </Callout>
            {result.trace?.judge_rationale ? (
              <Panel label="the judge" hint="one expensive call">
                <p className="text-[12.5px] leading-relaxed">
                  {String(result.trace.judge_rationale)}
                </p>
              </Panel>
            ) : null}
          </div>
        </div>

        <div className="space-y-2.5">
          {lenses.map((lens, i) => {
            const isOpen = open === lens.lens;
            return (
              <Panel key={lens.lens} className="!p-0">
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : lens.lens)}
                  className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-3.5 py-3 text-left"
                >
                  <span className="tech font-semibold text-accent">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="display text-[16px]">
                    {lens.lens.replace("_", " ")}
                  </span>
                  {lens.model_used ? (
                    <Pill tone="neutral">{lens.model_used}</Pill>
                  ) : (
                    <Pill tone="accent">no model — pure arithmetic</Pill>
                  )}
                  <span className="num display ml-auto text-[18px]">
                    {eps(lens.eps)}
                  </span>
                  <span className="num tech w-28 text-right text-ink-2">
                    survived {pct(lens.confidence, 0)}
                  </span>
                  <span className="tech w-4 text-right text-ink-3">
                    {isOpen ? "−" : "+"}
                  </span>
                </button>

                {isOpen && (
                  <div className="space-y-3.5 border-t border-rule px-3.5 py-3.5">
                    <div>
                      <div className="label">its analysis</div>
                      <p className="mt-1.5 text-[13px] leading-relaxed">
                        {lens.reasoning}
                      </p>
                    </div>

                    {lens.thesis && (
                      <div className="border-l-2 border-structure bg-structure-soft px-3 py-2.5">
                        <div className="label text-structure">
                          thesis, developed
                        </div>
                        <p className="mt-1.5 text-[13px] leading-relaxed">
                          {lens.thesis}
                        </p>
                      </div>
                    )}

                    {lens.counterargument ? (
                      <div className="border-l-2 border-accent bg-accent-soft px-3 py-2.5">
                        <div className="label text-accent">
                          argued against
                        </div>
                        <p className="mt-1.5 whitespace-pre-line text-[13px] leading-relaxed text-ink-2">
                          {lens.counterargument}
                        </p>
                      </div>
                    ) : (
                      <Callout label="not developed" tone="accent">
                        This case was never attacked, so its confidence is
                        self-reported and should be discounted.
                      </Callout>
                    )}

                    <div>
                      <div className="label">evidence cited</div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {(lens.claim_ids ?? []).map((id: string) => (
                          <code
                            key={id}
                            className="border border-rule bg-paper-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2"
                          >
                            {id}
                          </code>
                        ))}
                      </div>
                    </div>

                    {(lens.reconcile_errors ?? []).length > 0 && (
                      <div className="border-l-2 border-failed bg-accent-soft px-3 py-2.5">
                        <div className="label text-failed">
                          reconciliation failures
                        </div>
                        <ul className="mt-1.5 list-inside list-disc text-[12.5px] text-failed">
                          {lens.reconcile_errors!.map((error: string) => (
                            <li key={error}>{error}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <p className="tech text-ink-3">
                      {(lens.input_tokens ?? 0).toLocaleString()} in ·{" "}
                      {(lens.output_tokens ?? 0).toLocaleString()} out ·{" "}
                      {((lens.latency_ms ?? 0) / 1000).toFixed(1)}s · run{" "}
                      {lens.run_index ?? 0}
                    </p>
                  </div>
                )}
              </Panel>
            );
          })}
        </div>

        {/* Dropped lenses look intentional — because a dropped lens IS
            intentional. The judge was told it was missing. */}
        {droppedList.length > 0 && (
          <Panel
            label="dropped lenses"
            hint="excluded from the ensemble, and the judge was told they were missing"
          >
            <ul className="space-y-2">
              {droppedList.map(([lens, why]) => (
                <li key={lens} className="text-[12.5px]">
                  <span className="display text-[13px] text-failed">
                    {lens.replace("_", " ")}
                  </span>
                  <span className="text-ink-2"> — {String(why)}</span>
                </li>
              ))}
            </ul>
            <p className="dashed mt-3 pt-3 text-[11.5px] text-ink-3">
              An ensemble that silently shrinks is an ensemble whose weights no
              longer mean anything. Absent information is not agreement.
            </p>
          </Panel>
        )}
      </div>
    </Sheet>
  );
}
