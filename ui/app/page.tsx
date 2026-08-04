"use client";

import { useState } from "react";

import OrgChart, {
  AGENT_ROLES,
  KIND_COUNTS,
  type BuildComponent,
  type Kind,
  type OrgNode,
  type Overlay,
} from "@/components/OrgChart";
import RunBlock from "@/components/RunBlock";
import Schematic from "@/components/Schematic";
import { Panel, Pill, Stat } from "@/components/blueprint";
import { useBuild } from "@/lib/build";
import { useRun, type NodeStatus } from "@/lib/data";

/**
 * SHEET 01 — the system, and the run going through it.
 *
 * This used to be two tabs. "System" drew the parts with build state painted on
 * them; "Live run" drew the same parts with live state painted on them. They
 * were never two screens — they were one screen and an overlay switch, and
 * splitting them guaranteed that the diagram in front of you was the wrong one
 * for whatever you wanted to ask next. Someone watching a run who wondered
 * "is that box even tested?" had to leave the run to find out.
 *
 * So: one drawing, three overlays, and everything that reads off it underneath.
 * The overlay defaults to `live`, because the common case is a run in progress.
 *
 * The gates panel is the part that matters and it stays at the bottom. Almost
 * everything is BUILT; the question the accuracy prize turns on is what has been
 * MEASURED, and those are reported separately so the screen cannot imply the
 * thesis has been demonstrated when it has not.
 */

/**
 * The champion stage fans out per lens (`E_guidance`, `E_margins`, …) but is one
 * part on the drawing. Fold those into it: running if any is running, failed
 * only if all failed — one flaky champion call must not paint the whole stage
 * red when six others succeeded.
 */
function fold(nodes: Record<string, NodeStatus>): Record<string, NodeStatus> {
  const folded = { ...nodes };
  const champions = Object.entries(nodes).filter(([id]) => id.startsWith("D_"));
  if (champions.length) {
    const states = champions.map(([, s]) => s.state);
    folded["F_champion"] = {
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

const KIND_NOTE: Record<Kind, string> = {
  agent: "reasons with a model, and is why the audit layers exist",
  code: "deterministic — no model, cannot hallucinate",
  data: "fetches and stages, makes no judgment",
  output: "the artifact, not a component",
};

type View = "schematic" | "org";

const VIEWS: Array<[View, string, string]> = [
  ["schematic", "Signal flow", "how evidence moves, and what each conductor carries"],
  ["org", "Reporting chain", "the same parts as a hierarchy, eight ranks deep"],
];

const OVERLAYS: Array<[Overlay, string, string]> = [
  ["live", "Running", "state from the event log, four times a second"],
  ["build", "Built", "what exists, and what a test actually covers"],
  ["tier", "Cost", "which model tier each part runs on"],
];

export default function SystemAndRun() {
  const run = useRun();
  const build = useBuild();
  const [view, setView] = useState<View>("schematic");
  const [overlay, setOverlay] = useState<Overlay>("live");
  const [selected, setSelected] = useState<OrgNode | null>(null);

  const nodes = fold(run.nodes);
  const byComponent: Record<string, BuildComponent> = Object.fromEntries(
    (build?.components ?? []).map((c) => [c.id, c]),
  );

  const totals = build?.totals;
  const gates = build?.gates ?? [];
  const gatesPassed = totals?.gates_passed ?? 0;
  const gatesTotal = totals?.gates_total ?? 0;

  const detail = selected?.component ? byComponent[selected.component] : undefined;
  const liveDetail = selected?.liveId ? nodes[selected.liveId] : undefined;

  return (
    <div className="space-y-3">
      {/* ---- control rail -------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-rule border-b-0 bg-sheet/90 px-3 py-2">
        <span className="text-[10px] tracking-[0.14em] text-ink-3">
          POLLING out/events.ndjson @ 4Hz
        </span>

        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          {VIEWS.map(([key, label, hint]) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              title={hint}
              className={`state-change border px-2.5 py-1 text-[10px] tracking-[0.12em] uppercase ${
                view === key
                  ? "border-ink text-ink"
                  : "border-rule text-ink-3 hover:border-ink-3 hover:text-ink-2"
              }`}
            >
              {label}
            </button>
          ))}

          <span className="mx-1 h-4 w-px bg-rule" />

          {OVERLAYS.map(([key, label, hint]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOverlay(key)}
              title={hint}
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

      {/* ---- the drawing --------------------------------------------------- */}
      <div className="!mt-0 border border-rule bg-sheet/60 px-3 pt-3 pb-2">
        {view === "schematic" ? (
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
        ) : (
          <OrgChart
            overlay={overlay}
            build={byComponent}
            live={nodes}
            selected={selected?.id ?? null}
            onSelect={(node) =>
              setSelected((current) => (current?.id === node.id ? null : node))
            }
          />
        )}
      </div>

      {/* ---- readouts ------------------------------------------------------ */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <div className="space-y-3">
          <RunBlock run={run} />

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
                {selected.role ?? selected.sub} — {KIND_NOTE[selected.kind]}.
              </p>
              <div className="num mt-2 flex flex-wrap gap-x-3 text-[10.5px] text-ink-3">
                <span>
                  build:{" "}
                  <span
                    className={
                      detail?.state === "built" ? "text-structure" : "text-accent"
                    }
                  >
                    {detail?.state ?? "not tracked"}
                  </span>
                </span>
                {detail?.tests != null && <span>· {detail.tests} tests</span>}
                <span>
                  · live:{" "}
                  <span className="text-ink-2">
                    {selected.liveId ? (liveDetail?.state ?? "idle") : "not executable"}
                  </span>
                </span>
                {liveDetail?.latencyMs ? <span>· {liveDetail.latencyMs}ms</span> : null}
                {liveDetail?.error && (
                  <span className="text-failed">· {liveDetail.error}</span>
                )}
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
            The pipeline's only interface to this screen, shown raw. The cheapest
            possible proof that nothing here is a canned animation. */}
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

      {/* ---- built is not measured ----------------------------------------- */}
      <Panel
        label="gates — built is not the same as measured"
        hint="the rows that decide whether a number is a finding or an assertion"
      >
        {!build ? (
          <p className="text-[12px] text-ink-2">
            <code className="text-[11.5px]">build.json</code> not staged. Generate
            it with{" "}
            <code className="text-[11.5px]">
              forecast status --json out/build.json
            </code>{" "}
            — it is derived from the repository, so it cannot go out of date with
            what actually exists.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {gates.map((gate) => (
              <li
                key={gate.id}
                className="flex flex-wrap items-start gap-3 border-b border-rule-2 pb-2.5 last:border-0 last:pb-0"
              >
                <span className="w-14 shrink-0">
                  <Pill tone={gate.passed ? "good" : "warn"}>
                    {gate.passed ? "pass" : "open"}
                  </Pill>
                </span>
                <span className="min-w-[220px] flex-1">
                  <span className="text-[12.5px] font-semibold text-ink">
                    {gate.label}
                  </span>
                  <span className="mt-0.5 block text-[12px] text-ink-2">
                    {gate.detail}
                  </span>
                </span>
                {!gate.passed && (
                  <span className="max-w-md flex-1 text-[11.5px] leading-snug text-ink-3">
                    blocks: {gate.blocks}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="components built"
          value={`${totals?.built ?? 0}/${totals?.components ?? 0}`}
          sub="with a test encoding their failure modes"
        />
        <Stat
          label="untested"
          value={String(totals?.partial ?? 0)}
          sub="wired and working, but nothing tests how they fail"
          accent={(totals?.partial ?? 0) > 0}
        />
        <Stat
          label="agents"
          value={String(AGENT_ROLES)}
          sub={`${KIND_COUNTS.code} deterministic · ${KIND_COUNTS.data} data — not agents`}
        />
        <Stat
          label="gates passed"
          value={`${gatesPassed}/${gatesTotal}`}
          sub={
            gatesPassed === gatesTotal
              ? "the thesis is measured"
              : "the thesis is still asserted"
          }
          accent={gatesPassed < gatesTotal}
        />
      </div>
    </div>
  );
}
