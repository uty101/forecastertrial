"use client";

import { useModel } from "@/lib/data";
import type { RunState } from "@/lib/data";

/**
 * The run block, bottom-left of the instrument.
 *
 * One dense monospaced readout of everything you would otherwise have to hunt
 * for on three different screens: what is being forecast, what it cost, and
 * where the answer landed relative to the Street. Three lines, no headings —
 * headings on a nine-value block cost more space than they buy.
 *
 * It shows a run id because on the day there will be more than one run and the
 * question "is this the one you just started" needs answering in one glance.
 */
export default function RunBlock({ run }: { run: RunState }) {
  const model = useModel();
  const forecast = run.result?.forecast;
  const elapsed = (run.events.at(-1)?.ts_ms ?? 0) / 1000;
  const tokens =
    (forecast?.total_input_tokens ?? 0) + (forecast?.total_output_tokens ?? 0);

  /** Stable, short, and derived from the run rather than random — the same run
   *  replayed gets the same id, which is the whole point of replay mode. */
  const id = forecast
    ? `${forecast.ticker}${forecast.period}${forecast.as_of}`
        .split("")
        .reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)
        .toString(16)
        .slice(0, 6)
    : "------";

  const kept = forecast?.lenses.length ?? 0;
  const dropped = Object.keys(forecast?.droppee_lenses ?? {}).length;
  const lambda = forecast?.lambda_decision.value;

  const state = run.finished
    ? ["COMPLETE", "var(--color-structure)"]
    : run.started
      ? ["EXECUTING", "var(--color-accent)"]
      : ["WAITING", "var(--color-ink-3)"];

  return (
    <div className="plate border border-rule bg-sheet/90 px-4 py-3 backdrop-blur-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px]">
        <span style={{ color: state[1], fontWeight: 700, letterSpacing: "0.1em" }}>
          {state[0]}
        </span>
        <span className="text-ink-3">RUN</span>
        <span className="num text-ink">{id}</span>
        <span className="text-ink-3">·</span>
        <span className="text-ink">{forecast?.ticker ?? "—"}</span>
        <span className="text-ink-3">·</span>
        <span className="num text-ink">{forecast?.period ?? "—"}</span>
        <span className="text-ink-3">·</span>
        <span className="text-ink-3">AS_OF</span>
        <span className="num text-ink">{forecast?.as_of ?? "—"}</span>
        {/* The reporting cadence, on the first line of the run readout.
            Everything on every screen used to say "quarter" — correct for a US
            filer and wrong for most of the world. A half read as a quarter
            understates every flow by half and nothing on screen would say so,
            so the inference is stated where it cannot be missed. */}
        {model?.cadence && (
          <>
            <span className="text-ink-3">·</span>
            <span
              className="text-ink-2"
              title={model.cadence.describe}
              style={{
                color:
                  model.cadence.frequency === "quarterly"
                    ? "var(--color-ink-2)"
                    : "var(--color-consensus)",
              }}
            >
              {model.cadence.label.toUpperCase()}
            </span>
          </>
        )}
        {run.source === "replay" && (
          <span className="text-consensus">· REPLAY, ORIGINAL PACING</span>
        )}
      </div>

      <div className="num mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2">
        <span>{tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : tokens} tok</span>
        <span className="text-ink-3">·</span>
        <span>${(forecast?.total_cost_usd ?? 0).toFixed(2)}</span>
        <span className="text-ink-3">·</span>
        <span>{elapsed.toFixed(1)}s</span>
        <span className="text-ink-3">·</span>
        <span>{run.claims} claims</span>
        <span className="text-ink-3">·</span>
        <span>{run.events.length} events</span>
      </div>

      <div className="num mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        <span className="text-ink-3">λ</span>
        <span className="text-structure">{lambda == null ? "—" : lambda.toFixed(2)}</span>
        <span className="text-ink-3">·</span>
        <span className="text-ink-3">forecast</span>
        <span className="text-accent">
          {forecast ? forecast.eps_non_gaap.toFixed(2) : "—"}
        </span>
        <span className="text-ink-3">·</span>
        <span className="text-ink-3">street</span>
        <span className="text-consensus">
          {forecast ? forecast.consensus.eps.toFixed(2) : "—"}
        </span>
        <span className="text-ink-3">·</span>
        <span className="text-ink-3">baseline</span>
        <span className="text-ink-2">
          {forecast ? forecast.baseline_eps.toFixed(2) : "—"}
        </span>
        <span className="text-ink-3">·</span>
        <span className={dropped ? "text-failed" : "text-ink-2"}>
          {kept}/{kept + dropped} lenses
        </span>
      </div>
    </div>
  );
}
