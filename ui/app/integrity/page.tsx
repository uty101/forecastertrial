"use client";

import {
  Callout,
  Disclaimer,
  Empty,
  Lede,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  StageStrip,
  Stat,
  StatusPanel,
  SyntheticBanner,
} from "@/components/blueprint";
import { pct, useResult } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 09 — integrity.
 *
 * The claim this whole system rests on is that no number exists without a
 * source, and that nothing filed after the lock date was visible. Both are
 * enforced in code rather than asserted in a README, and this sheet is where
 * that becomes checkable.
 *
 * The failure count is displayed as prominently as the success count on purpose.
 * "We verify every citation" is only a meaningful sentence if the failures are
 * visible; a sheet that showed only the verified total would be claiming the
 * opposite of what the pipeline does.
 */

const GUARANTEES = [
  {
    n: 1,
    title: "Typed provenance",
    detail: "A Claim cannot be constructed without a source and a verbatim quote",
  },
  {
    n: 2,
    title: "Quote matching",
    detail: "Prose quotes are string-matched against the filing they came from",
  },
  {
    n: 3,
    title: "Point in time",
    detail: "Nothing filed after the lock date is visible, restatements included",
  },
  {
    n: 4,
    title: "Fail closed",
    detail: "A lens that fails either check is dropped, logged and surfaced",
  },
];

export default function IntegrityScreen() {
  const result = useResult();

  if (!result) {
    return (
      <Sheet system="provenance + point-in-time" sheet={sheetOf("/integrity/")}>
        <Empty
          title="No run to audit"
          detail="This sheet reads the citation and evidence counters from out/results.json."
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
  const evidence = (result.trace?.evidence ?? {}) as {
    claims?: number;
    deduped?: number;
  };
  const sources = (result.trace?.sources ?? {}) as {
    sources?: string[];
    answered_by?: Record<string, string>;
    tripped?: string[];
    disagreements?: unknown[];
  };
  const budgets = (result.trace?.budgets ?? {}) as Record<
    string,
    { docs?: number; skipped?: string[] }
  >;

  const verified = citations.verified ?? 0;
  const failed = citations.failed ?? 0;
  const total = verified + failed;
  const rate = total ? verified / total : 0;
  const dropped = Object.entries(f.dropped_lenses ?? {});
  const skipped = Object.entries(budgets).flatMap(([stage, b]) =>
    (b.skipped ?? []).map((s) => [stage, s] as const),
  );

  return (
    <Sheet
      system="provenance + point-in-time"
      readout={[`LOCK DATE ${f.as_of}`, `${verified}/${total} VERIFIED`]}
      sheet={sheetOf("/integrity/")}
      footer={
        <SheetFooter
          cells={[
            ["verification rate", pct(rate, 1)],
            ["lock date", String(f.as_of)],
            ["enforcement", "assert_point_in_time raises, never warns"],
            ["leak test", "tests/test_point_in_time.py tries to leak on purpose"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <SyntheticBanner trace={result.trace} />

        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Lede>
            "We don&rsquo;t invent figures" is a validation error here, not a code-review comment. And a backtest that cannot fail on a leak is not enforcing anything — so there is a test that deliberately tries to leak.
          </Lede>

          <StatusPanel
            title="integrity status"
            state={failed === 0 ? "clean" : "failures present"}
            detail={`${verified} of ${total} citations verified`}
            fraction={rate}
            tone={failed === 0 ? "done" : "running"}
            rows={[
              ["claims in store", evidence.claims ?? "—"],
              ["verified", verified],
              ["failed", failed],
              ["lenses dropped", dropped.length],
            ]}
          />
        </div>

        <StageStrip
          stages={GUARANTEES.map((g) => ({ ...g, state: "done" as const }))}
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Panel label="citations verified">
            <Stat
              label="matched their source"
              value={String(verified)}
              sub="prose quotes found in the filing"
            />
          </Panel>
          {/* Shown as prominently as the success count, on purpose. */}
          <Panel label="citations failed">
            <Stat
              label="not found in source"
              value={String(failed)}
              sub={
                failed === 0
                  ? "none this run"
                  : "each one dropped its lens from the ensemble"
              }
              accent={failed > 0}
            />
          </Panel>
          <Panel label="verification rate">
            <Stat label="of all citations" value={pct(rate, 1)} />
          </Panel>
          <Panel label="evidence depth">
            <Stat
              label="claims available"
              value={String(evidence.claims ?? "—")}
              sub={`${evidence.deduped ?? 0} deduplicated`}
            />
          </Panel>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <Panel
            label="how verification splits"
            hint="the part that is easy to get wrong"
          >
            <dl className="space-y-3 text-[12.5px] leading-relaxed">
              <div>
                <dt className="display text-[13px]">Prose sources</dt>
                <dd className="mt-1 text-ink-2">
                  8-K, 10-Q, 10-K, transcripts. A human wrote sentences, a model
                  quoted one, and the quote must be found in the text. This is
                  where fabrication is possible and where string matching earns
                  its keep — a quote assembled from two different sentences reads
                  perfectly and is not what the company said.
                </dd>
              </div>
              <div>
                <dt className="display text-[13px]">Structured sources</dt>
                <dd className="mt-1 text-ink-2">
                  XBRL, the sponsor feed, FRED. The &ldquo;quote&rdquo; is the
                  tagged fact itself, rendered by the source adapter from a typed
                  response — there is no prose to match. Not a loophole: a model
                  can only cite ids already in the evidence store, and the store
                  is built entirely from adapter output, so the <em>value</em> came
                  from the adapter and never from the model.
                </dd>
              </div>
              <div>
                <dt className="display text-[13px]">Derived figures</dt>
                <dd className="mt-1 text-ink-2">
                  Deliberately in neither set. A derived figure is one this
                  pipeline computed, so it is only as good as its inputs and must
                  be justified by the claims underneath it rather than by its own
                  existence.
                </dd>
              </div>
            </dl>
          </Panel>

          <div className="space-y-3">
            <Panel label="point-in-time enforcement" hint={`lock date ${f.as_of}`}>
              <p className="text-[12.5px] leading-relaxed text-ink-2">
                Every data source method takes{" "}
                <code className="font-mono text-[11.5px]">as_of</code> and must not
                return anything filed after it.{" "}
                <code className="font-mono text-[11.5px]">
                  assert_point_in_time
                </code>{" "}
                raises rather than warning, and the loader never routes around a
                violation — a leaking source is a bug to fix, not a transient
                failure to fall back from.
              </p>
              <ul className="dashed mt-3 space-y-1.5 pt-3 text-[12px] text-ink-2">
                <li>
                  <strong className="text-ink">Restatements too.</strong>{" "}
                  A figure for a historical period, published after the lock date,
                  is still a leak. XBRL&rsquo;s{" "}
                  <code className="font-mono text-[11px]">filed</code> field is
                  what catches it — not the period label.
                </li>
                <li>
                  <strong className="text-ink">Consensus.</strong> Historical
                  cases use the estimate as it stood at that quarter&rsquo;s report
                  date, which is the bar the company actually faced.
                </li>
                <li>
                  <strong className="text-ink">Macro.</strong> FRED series
                  are revised for months, so every request pins{" "}
                  <code className="font-mono text-[11px]">realtime_start</code> to
                  the lock date.
                </li>
                <li>
                  <strong className="text-ink">The cache.</strong>{" "}
                  <code className="font-mono text-[11px]">as_of</code> is in the
                  cache key, so a cached fetch can never be replayed across a
                  point-in-time boundary.
                </li>
              </ul>
            </Panel>
            <Callout label="the test that matters" tone="accent">
              <code className="font-mono text-[11.5px]">
                tests/test_point_in_time.py
              </code>{" "}
              deliberately tries to leak, including the subtle case — a
              restatement of a historical period published after the lock. A
              backtest that cannot fail this way is not enforcing anything, and
              its numbers mean nothing.
            </Callout>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <Panel label="source resolution" hint="which source answered each call">
            {!sources.answered_by ? (
              <p className="text-[12.5px] text-ink-2">
                No source report recorded for this run.
              </p>
            ) : (
              <>
                <table className="w-full text-[12px]">
                  <tbody>
                    {Object.entries(sources.answered_by).map(([what, who]) => (
                      <tr
                        key={what}
                        className="border-b border-rule-2 last:border-0"
                      >
                        <td className="py-1 pr-3 font-mono text-[11px] text-ink-2">
                          {what}
                        </td>
                        <td className="py-1 text-right font-semibold">{who}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(sources.tripped ?? []).length > 0 && (
                  <p className="mt-2.5 text-[12px] text-failed">
                    Circuit breaker tripped: {sources.tripped!.join(", ")} — three
                    failures and a source is down for the run.
                  </p>
                )}
                {(sources.disagreements ?? []).length > 0 && (
                  <p className="mt-2 text-[12px] text-accent">
                    {sources.disagreements!.length} source disagreement(s)
                    recorded. Two sources disagreeing on consensus usually means a
                    GAAP/non-GAAP basis mismatch — a finding, not an error.
                  </p>
                )}
              </>
            )}
          </Panel>

          <Panel
            label="what acquisition skipped"
            hint="silent truncation reads as 'we covered everything'"
          >
            {skipped.length === 0 ? (
              <p className="text-[12.5px] text-ink-2">
                Nothing skipped — every ranked target was within budget this run.
              </p>
            ) : (
              <ul className="space-y-1.5 text-[12px]">
                {skipped.map(([stage, what], i) => (
                  <li key={`${stage}-${i}`} className="flex gap-2">
                    <span className="tech shrink-0 text-ink-3">
                      {stage}
                    </span>
                    <span className="text-ink-2">{what}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="dashed mt-3 pt-3 text-[11.5px] text-ink-3">
              Every acquirer has a ranked target list and a hard budget. When the
              budget is spent it returns what it has and logs what it dropped,
              because silent truncation reads as complete coverage when it was not.
            </p>
          </Panel>
        </div>

        {dropped.length > 0 && (
          <Panel label="lenses dropped by these checks">
            <ul className="space-y-2">
              {dropped.map(([lens, why]) => (
                <li key={lens} className="text-[12.5px]">
                  <span className="display text-[13px] text-failed">
                    {lens.replace("_", " ")}
                  </span>
                  <span className="text-ink-2"> — {String(why)}</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        <div className="flex flex-wrap gap-2">
          <Pill tone={failed === 0 ? "good" : "bad"}>
            {failed === 0
              ? "all citations verified"
              : `${failed} citation${failed === 1 ? "" : "s"} failed — shown, not hidden`}
          </Pill>
          <Pill tone="good">point-in-time enforced in code</Pill>
          <Pill tone="neutral">both bases carried</Pill>
        </div>

        <Disclaimer>
          A high verification rate says the quotes match their sources. It does not
          say the sources are right, that the model read them correctly, or that
          the forecast is good — those are separate questions, answered on the
          method sheet. What this sheet establishes is narrower and worth having:
          every figure is auditable back to a filing and a date.
        </Disclaimer>
      </div>
    </Sheet>
  );
}
