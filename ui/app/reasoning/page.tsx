"use client";

import { useState } from "react";

import { Card, Empty, Pill, SyntheticBanner } from "@/components/ui";
import { eps, pct, useResult } from "@/lib/data";
import type { LensOutput } from "@/lib/types";

/**
 * Screen 3 — the reasoning trace. This is the screen that wins on substance.
 *
 * Each lens expands to its thesis AND its counterargument, because the cases
 * were argued against before anything was compared. Every claim is listed by id.
 *
 * FAILED CITATIONS ARE SHOWN IN RED, NOT HIDDEN. That is the whole point: "we
 * verify every citation" is only a meaningful statement if the failures are
 * visible, and a screen that quietly omitted them would be claiming the
 * opposite of what it does.
 */
export default function ReasoningScreen() {
  const result = useResult();
  const [open, setOpen] = useState<string | null>(null);

  if (!result) {
    return (
      <Empty
        title="No reasoning trace yet"
        detail="This screen reads the lens outputs from out/results.json."
        command="uv run forecast run --ticker NVDA --as-of 2026-08-16"
      />
    );
  }

  const f = result.forecast;
  const citations = (result.trace?.citations ?? {}) as {
    verified?: number;
    failed?: number;
  };
  const dropped = Object.entries(f.dropped_lenses ?? {});

  return (
    <div className="space-y-4">
      <SyntheticBanner trace={result.trace} />
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[17px] font-semibold tracking-tight">Reasoning trace</h1>
        <p className="text-[12.5px] text-[--color-ink-2]">
          {f.lenses?.length ?? 0} lenses survived, {dropped.length} dropped
        </p>
        <div className="ml-auto flex gap-2">
          <Pill tone="good">{citations.verified ?? 0} citations verified</Pill>
          {(citations.failed ?? 0) > 0 ? (
            <Pill tone="bad">{citations.failed} failed</Pill>
          ) : (
            <Pill tone="neutral">0 failed</Pill>
          )}
        </div>
      </div>

      {result.trace?.judge_rationale ? (
        <Card
          title="The judge"
          hint="impact-weighted, never vote-weighted — one expensive call"
        >
          <p className="text-[14px] leading-relaxed">
            {String(result.trace.judge_rationale)}
          </p>
        </Card>
      ) : null}

      <div className="space-y-3">
        {(f.lenses ?? []).map((lens: LensOutput) => {
          const isOpen = open === lens.lens;
          return (
            <Card key={lens.lens}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : lens.lens)}
                className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 text-left"
              >
                <span className="text-[14px] font-semibold">{lens.lens}</span>
                {lens.model_used ? (
                  <Pill tone="neutral">{lens.model_used}</Pill>
                ) : (
                  <Pill tone="accent">no model — pure arithmetic</Pill>
                )}
                <span className="num ml-auto text-[15px] font-semibold">
                  {eps(lens.eps)}
                </span>
                <span className="num w-24 text-right text-[12.5px] text-[--color-ink-2]">
                  conf {pct(lens.confidence, 0)}
                </span>
                <span className="w-4 text-right text-[--color-ink-3]">
                  {isOpen ? "−" : "+"}
                </span>
              </button>

              {isOpen && (
                <div className="mt-4 space-y-4 border-t border-[--color-line] pt-4">
                  <div>
                    <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-[--color-ink-3]">
                      Its analysis
                    </h3>
                    <p className="mt-1.5 text-[13.5px] leading-relaxed">
                      {lens.reasoning}
                    </p>
                  </div>

                  {lens.thesis && (
                    <div>
                      <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-[--color-ink-3]">
                        Thesis, developed
                      </h3>
                      <p className="mt-1.5 text-[13.5px] leading-relaxed">
                        {lens.thesis}
                      </p>
                    </div>
                  )}

                  {lens.counterargument ? (
                    <div className="rounded-lg bg-[--color-street-soft] p-3">
                      <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-[--color-ink-3]">
                        Argued against
                      </h3>
                      <p className="mt-1.5 whitespace-pre-line text-[13.5px] leading-relaxed text-[--color-ink-2]">
                        {lens.counterargument}
                      </p>
                    </div>
                  ) : (
                    <p className="text-[12.5px] text-amber-700 dark:text-amber-400">
                      Not developed — this case was never attacked, so its confidence
                      is self-reported and should be discounted.
                    </p>
                  )}

                  <div>
                    <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-[--color-ink-3]">
                      Evidence cited
                    </h3>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {(lens.claim_ids ?? []).map((id: string) => (
                        <code
                          key={id}
                          className="rounded bg-[--color-street-soft] px-1.5 py-0.5 font-mono text-[11.5px] text-[--color-ink-2]"
                        >
                          {id}
                        </code>
                      ))}
                    </div>
                  </div>

                  {(lens.reconcile_errors ?? []).length > 0 && (
                    <div className="rounded-lg border border-red-300 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
                      <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-red-700 dark:text-red-300">
                        Reconciliation failures
                      </h3>
                      <ul className="mt-1.5 list-inside list-disc text-[13px] text-red-700 dark:text-red-300">
                        {lens.reconcile_errors!.map((error: string) => (
                          <li key={error}>{error}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p className="text-[12px] text-[--color-ink-3]">
                    <span className="num">
                      {(lens.input_tokens ?? 0).toLocaleString()}
                    </span>{" "}
                    in ·{" "}
                    <span className="num">
                      {(lens.output_tokens ?? 0).toLocaleString()}
                    </span>{" "}
                    out ·{" "}
                    <span className="num">
                      {((lens.latency_ms ?? 0) / 1000).toFixed(1)}s
                    </span>{" "}
                    · run {lens.run_index ?? 0}
                  </p>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {/* Dropped lenses look intentional — greyed, with the reason — because a
          dropped lens IS intentional. The judge was told it was missing. */}
      {dropped.length > 0 && (
        <Card
          title="Dropped lenses"
          hint="excluded from the ensemble, and the judge was told they were missing"
        >
          <ul className="space-y-2">
            {dropped.map(([lens, why]) => (
              <li key={lens} className="text-[13px]">
                <span className="font-semibold text-[--color-ink-2]">{lens}</span>
                <span className="text-[--color-ink-3]"> — {String(why)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t border-[--color-line] pt-3 text-[12.5px] text-[--color-ink-3]">
            An ensemble that silently shrinks is an ensemble whose weights no longer
            mean anything. Absent information is not agreement.
          </p>
        </Card>
      )}
    </div>
  );
}
