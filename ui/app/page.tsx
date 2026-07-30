"use client";

import { useState } from "react";

import RunBlock from "@/components/RunBlock";
import Schematic from "@/components/Schematic";
import type { BuildComponent, OrgNode, Overlay } from "@/components/OrgChart";
import { useRun, type NodeStatus } from "@/lib/data";
import { useBuild } from "@/lib/build";

/**
 * HOME — the instrument.
 *
 * Not a landing page with a diagram on it. The diagram IS the page: full bleed,
 * live, polling four times a second, with the run block bottom-left and the
 * event tape bottom-right. Nothing to scroll past before the thing you came to
 * see, because on the day this is what will be on the projector for six hours.
 *
 * Everything explanatory lives on the ten sheets behind it. This screen has one
 * job: show the system working, and let anyone point at any part of it and get
 * an answer without the presenter having to narrate.
 */

/**
 * The champion stage fans out per lens (`D_guidance`, `D_margins`, …) but is one
 * part on the schematic. Fold those into it: running if any is running, failed
 * only if all failed — one flaky champion call must not paint the whole stage
 * red when six others succeeded.
 */
function fold(nodes: Record<string, NodeStatus>): Record<string, NodeStatus> {
  const folded = { ...nodes };
  const champions = Object.entries(nodes).filter(([id]) => id.startsWith("D_"));
  if (champions.length) {
    const states = champions.map(([, s]) => s.state);
    folded["D_champion"] = {
      state: states.includes("running")
        ? "running"
        : states.every((s) => s === "failed")
          ? "failed"
          : "done",
      latencyMs: Math.max(...champions.map(([, s]) => s.latencyMs ?? 0)),
    };
  }
  return folded;
}

const OVERLAYS: Array<[Overlay, string]> = [
  ["live", "running"],
  ["build", "built"],
  ["tier", "cost"],
];

export default function Home() {
  const run = useRun();
  const build = useBuild();
  const [overlay, setOverlay] = useState<Overlay>("live");
  const [selected, setSelected] = useState<OrgNode | null>(null);

  const nodes = fold(run.nodes);
  const byComponent: Record<string, BuildComponent> = Object.fromEntries(
    (build?.components ?? []).map((c) => [c.id, c]),
  );
  const detail = selected?.component ? byComponent[selected.component] : undefined;
  const liveDetail = selected?.liveId ? nodes[selected.liveId] : undefined;

  return (
    <div className="relative">
      {/* ---- control rail --------------------------------------------------
          The wordmark and the sheet index live in Nav; repeating them here
          would be two headers arguing. This rail carries only what is specific
          to the instrument: which overlay, and whether anything is moving. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-rule border-b-0 bg-sheet/90 px-3 py-2">
        <span className="text-[10px] tracking-[0.14em] text-ink-3">
          SIGNAL FLOW · POLLING out/events.ndjson @ 4Hz
        </span>

        <span className="ml-auto flex items-center gap-1.5">
          {OVERLAYS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOverlay(key)}
              className={`state-change border px-2.5 py-1 text-[10px] tracking-[0.12em] uppercase ${
                overlay === key
                  ? "border-accent text-accent"
                  : "border-rule text-ink-3 hover:border-ink-3 hover:text-ink-2"
              }`}
            >
              {label}
            </button>
          ))}
        </span>
      </div>

      {/* ---- the instrument ------------------------------------------------ */}
      <div className="border border-rule bg-sheet/60 px-3 pt-3 pb-2">
        <Schematic
          overlay={overlay}
          build={byComponent}
          live={nodes}
          result={run.result}
          selected={selected?.id ?? null}
          onSelect={(part) =>
            setSelected((current) => (current?.id === part.id ? null : part))
          }
        />
      </div>

      {/* ---- readouts ------------------------------------------------------ */}
      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <div className="space-y-3">
          <RunBlock run={run} />

          {/* Hover or click any part; this is where the answer lands, so nobody
              has to be talked through the diagram. */}
          {selected ? (
            <div className="border border-rule bg-sheet/90 px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  style={{
                    color:
                      selected.kind === "agent"
                        ? selected.tier === "deep"
                          ? "var(--color-deep)"
                          : "var(--color-accent)"
                        : selected.kind === "code"
                          ? "var(--color-structure)"
                          : "var(--color-data)",
                    fontSize: 12,
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                  }}
                >
                  {selected.label.toUpperCase()}
                </span>
                <span className="text-[10px] tracking-[0.1em] text-ink-3">
                  {selected.kind === "agent"
                    ? `AGENT · ${(selected.tier ?? "mid").toUpperCase()} TIER`
                    : selected.kind === "code"
                      ? "NOT AN AGENT · DETERMINISTIC"
                      : selected.kind === "data"
                        ? "NOT AN AGENT · FETCHES ONLY"
                        : "THE ARTIFACT"}
                </span>
                {selected.unwired && (
                  <span className="text-[10px] tracking-[0.1em] text-accent">
                    · NOT WIRED INTO run.py
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-2">
                {selected.role ?? selected.sub}
              </p>
              <div className="num mt-2 flex flex-wrap gap-x-3 text-[10.5px] text-ink-3">
                <span>
                  build:{" "}
                  <span className={detail?.state === "built" ? "text-structure" : "text-accent"}>
                    {detail?.state ?? "not tracked"}
                  </span>
                </span>
                {detail?.tests != null && <span>· {detail.tests} tests</span>}
                {liveDetail && (
                  <span>
                    · live: <span className="text-ink-2">{liveDetail.state}</span>
                  </span>
                )}
                {liveDetail?.latencyMs ? <span>· {liveDetail.latencyMs}ms</span> : null}
              </div>
            </div>
          ) : (
            <div className="border border-dashed border-rule px-4 py-3 text-[11px] text-ink-3">
              Click any part for its detail — what it is, whether it is an agent,
              whether a test covers it, and what it did on this run. Works before a
              run too.
            </div>
          )}
        </div>

        {/* ---- event tape ---------------------------------------------------
            The pipeline's only interface to this screen, shown raw. It is the
            cheapest possible proof that nothing here is a canned animation. */}
        <div className="border border-rule bg-sheet/90">
          <div className="flex items-center justify-between border-b border-rule px-3 py-1.5">
            <span className="text-[10px] tracking-[0.14em] text-ink-3">
              EVENT TAPE · out/events.ndjson
            </span>
            <span className="num text-[10px] text-ink-3">{run.events.length}</span>
          </div>
          <div className="max-h-[168px] overflow-y-auto px-3 py-1.5">
            {run.events.length === 0 ? (
              <p className="py-2 text-[11px] text-ink-3">
                Polling four times a second. Start a run:
                <br />
                <code className="mt-1 inline-block text-ink-2">
                  uv run forecast run --ticker NVDA --as-of 2026-08-16
                </code>
              </p>
            ) : (
              run.events
                .slice(-40)
                .reverse()
                .map((event) => (
                  <div
                    key={event.seq}
                    className="num flex gap-2 border-b border-rule-2 py-1 text-[10.5px] last:border-0"
                  >
                    <span className="w-12 shrink-0 text-ink-3">
                      {(event.ts_ms / 1000).toFixed(2)}
                    </span>
                    <span
                      className={`w-20 shrink-0 ${
                        event.type === "node_failed"
                          ? "text-failed"
                          : event.type === "node_done"
                            ? "text-structure"
                            : "text-ink-3"
                      }`}
                    >
                      {event.type}
                    </span>
                    <span className="shrink-0 text-ink">{event.node ?? "—"}</span>
                    <span className="truncate text-ink-3">
                      {Object.entries(event.payload ?? {})
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(" ")}
                    </span>
                  </div>
                ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
