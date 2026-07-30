"use client";

import { useEffect, useState } from "react";

import OrgChart, {
  AGENT_ROLES,
  KIND_COUNTS,
  NODES,
  type BuildComponent,
  type Kind,
  type OrgNode,
  type Overlay,
} from "@/components/OrgChart";
import {
  Callout,
  Display,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
} from "@/components/blueprint";
import { pct, useRun } from "@/lib/data";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 10 — the system. One sheet that answers three questions about the same
 * hierarchy: what is built, what is running, and what each part costs.
 *
 * The build overlay is driven by `build.json`, which the CLI DERIVES from the
 * repository — module imports, test coverage, the golden file, the case set, and
 * whether `FITTED_BETA_MEASURED` is still False. A hand-kept checklist rots the
 * moment someone lands a change without editing it, and then the status board is
 * the least trustworthy thing in the repo.
 *
 * The gate list is the part that matters. Almost everything is BUILT; the
 * question the accuracy prize turns on is what has been MEASURED, and those are
 * reported separately so the sheet cannot imply the thesis has been demonstrated
 * when it has not.
 */

interface BuildPayload {
  components: BuildComponent[];
  gates: Array<{
    id: string;
    label: string;
    passed: boolean;
    detail: string;
    blocks: string;
  }>;
  totals: {
    components: number;
    built: number;
    partial: number;
    missing: number;
    tests: number;
    gates_passed: number;
    gates_total: number;
  };
}

const KIND_NOTE: Record<Kind, string> = {
  agent: "reasons with a model, and is why the audit layers exist",
  code: "deterministic — no model, cannot hallucinate",
  data: "fetches and stages, makes no judgment",
  output: "the artifact, not a component",
};

const OVERLAYS: Array<[Overlay, string, string]> = [
  ["build", "Built", "what exists and what a test actually covers"],
  ["live", "Running", "state from the event log, four times a second"],
  ["tier", "Cost", "which model tier each part runs on"],
];

export default function SystemScreen() {
  const [overlay, setOverlay] = useState<Overlay>("build");
  const [build, setBuild] = useState<BuildPayload | null>(null);
  const [selected, setSelected] = useState<OrgNode | null>(null);
  const run = useRun();

  useEffect(() => {
    void fetch("/build.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setBuild(data as BuildPayload))
      .catch(() => setBuild(null));
  }, []);

  // The champion stage fans out per lens in the event log but is one rank on the
  // chart; each champion box reads its own lens's D_ event, so no folding needed.
  const byComponent: Record<string, BuildComponent> = Object.fromEntries(
    (build?.components ?? []).map((c) => [c.id, c]),
  );

  const totals = build?.totals;
  const gates = build?.gates ?? [];
  const gatesPassed = totals?.gates_passed ?? 0;
  const gatesTotal = totals?.gates_total ?? 0;

  const liveDone = Object.values(run.nodes).filter((n) => n.state === "done").length;
  const liveRunning = Object.values(run.nodes).filter(
    (n) => n.state === "running",
  ).length;

  const detail = selected?.component ? byComponent[selected.component] : undefined;

  return (
    <Sheet
      system="system overview"
      readout={
        overlay === "live"
          ? [`${liveDone} NODES DONE`, run.finished ? "RUN COMPLETE" : "AWAITING RUN"]
          : [
              `${totals?.built ?? 0}/${totals?.components ?? 0} BUILT`,
              `${gatesPassed}/${gatesTotal} GATES PASSED`,
            ]
      }
      sheet={sheetOf("/system/")}
      footer={
        <SheetFooter
          cells={[
            ["ranks", "8 — output down to sources"],
            // Derived from the chart, which is in turn checked against the
            // prompt files. The old hand-written "11" counted the Mechanical
            // lens as an agent; it has no prompt and no model.
            ["agents", `${AGENT_ROLES} — one prompt file each`],
            [
              "not agents",
              `${KIND_COUNTS.code} deterministic · ${KIND_COUNTS.data} data`,
            ],
            ["audits", "3 layers with a veto — 2 of them pure code"],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Display kicker="Eight ranks, from the deliverable down to the data sources. Solid lines are reporting lines. Dashed lines are the verification layers, which audit the chain and contribute no estimate of their own.">
            The whole system,
            <br />
            <Green>on one sheet.</Green>
          </Display>

          <StatusPanel
            title={overlay === "live" ? "run status" : "build status"}
            state={
              overlay === "live"
                ? run.finished
                  ? "complete"
                  : liveRunning > 0
                    ? "active"
                    : "waiting"
                : gatesPassed === gatesTotal
                  ? "measured"
                  : "built, not measured"
            }
            detail={
              overlay === "live"
                ? `${liveRunning} running`
                : `${gatesPassed} of ${gatesTotal} gates passed`
            }
            fraction={
              overlay === "live"
                ? liveDone / 19
                : gatesTotal
                  ? gatesPassed / gatesTotal
                  : 0
            }
            tone={
              overlay === "live"
                ? run.finished
                  ? "done"
                  : liveRunning > 0
                    ? "running"
                    : "idle"
                : gatesPassed === gatesTotal
                  ? "done"
                  : "running"
            }
            rows={[
              ["components", totals?.components ?? "—"],
              ["built + tested", totals?.built ?? "—"],
              ["untested", totals?.partial ?? "—"],
              ["tests", totals?.tests ?? "—"],
            ]}
          />
        </div>

        {/* Three questions, one hierarchy. */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1">overlay:</span>
          {OVERLAYS.map(([key, label, hint]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOverlay(key)}
              title={hint}
              className={`state-change border px-3 py-1.5 text-[12.5px] ${
                overlay === key
                  ? "border-accent bg-accent-soft font-semibold text-accent"
                  : "border-rule text-ink-2 hover:border-ink-3"
              }`}
            >
              {label}
            </button>
          ))}
          <span className="tech ml-2 text-ink-3">
            {OVERLAYS.find(([k]) => k === overlay)?.[2]}
          </span>
        </div>

        <Panel
          label="reporting chain"
          hint="click any box for its detail"
          right={
            <span className="tech text-ink-3">
              {overlay === "build" && !build ? "build.json not staged" : ""}
            </span>
          }
        >
          <OrgChart
            overlay={overlay}
            build={byComponent}
            live={run.nodes}
            selected={selected?.id ?? null}
            onSelect={(node) =>
              setSelected((current) => (current?.id === node.id ? null : node))
            }
          />

          <div className="dashed mt-3 flex flex-wrap gap-4 pt-3">
            {overlay === "build" &&
              (
                [
                  ["built", "built, with a test that encodes its failure modes"],
                  ["partial", "built and wired, but nothing tests how it fails"],
                  ["missing", "does not import"],
                ] as const
              ).map(([state, label]) => (
                <span key={state} className="tech flex items-center gap-2">
                  <span
                    className={`inline-block h-3 w-5 border ${
                      state === "built"
                        ? "border-structure bg-structure-soft"
                        : state === "partial"
                          ? "border-accent bg-accent-soft"
                          : "border-failed bg-paper-2"
                    }`}
                  />
                  {label}
                </span>
              ))}
            {overlay === "live" &&
              (
                [
                  ["idle", "waiting"],
                  ["running", "running"],
                  ["done", "complete"],
                  ["failed", "dropped, with a reason"],
                ] as const
              ).map(([state, label]) => (
                <span key={state} className="tech flex items-center gap-2">
                  <span
                    className={`inline-block h-3 w-5 border ${
                      state === "done"
                        ? "border-structure bg-structure-soft"
                        : state === "running"
                          ? "border-accent bg-accent-soft"
                          : state === "failed"
                            ? "border-failed bg-accent-soft"
                            : "border-idle bg-paper-2"
                    }`}
                  />
                  {label}
                </span>
              ))}
            {overlay === "tier" && (
              <>
                <span className="tech flex items-center gap-2">
                  <span className="inline-block h-3 w-5 border border-structure bg-structure-soft" />
                  no model — cannot hallucinate
                </span>
                <span className="tech flex items-center gap-2">
                  <span className="inline-block h-3 w-5 border border-idle bg-paper-2" />
                  cheap — extraction
                </span>
                <span className="tech flex items-center gap-2">
                  <span className="inline-block h-3 w-5 border border-accent bg-accent-soft" />
                  mid — lenses + advocate
                </span>
                <span className="tech flex items-center gap-2">
                  <span className="inline-block h-3 w-5 border border-accent-2 bg-accent" />
                  deep — one judge call
                </span>
              </>
            )}
            <span className="tech ml-auto text-ink-3">
              dashed border = audits the chain, no estimate of its own
            </span>
          </div>
        </Panel>

        {selected && (
          <Panel label={`selected — ${selected.label}`}>
            <div className="grid gap-4 sm:grid-cols-4">
              {/* First cell, deliberately: agent or not is the first thing
                  anyone should learn about a box on this chart. */}
              <div>
                <div className="label">kind</div>
                <p className="mt-1 text-[12.5px]">
                  <Pill tone={selected.kind === "agent" ? "warn" : "good"}>
                    {selected.kind === "agent" ? "agent" : "not an agent"}
                  </Pill>
                  <span className="ml-2 text-ink-2">{KIND_NOTE[selected.kind]}</span>
                  {selected.unwired && (
                    <span className="mt-1 block text-accent">
                      built and tested, but run.py never calls it
                    </span>
                  )}
                </p>
              </div>
              <div>
                <div className="label">role</div>
                <p className="mt-1 text-[12.5px]">
                  {selected.role ?? selected.sub ?? "—"}
                </p>
              </div>
              <div>
                <div className="label">build state</div>
                <p className="mt-1 text-[12.5px]">
                  {detail ? (
                    <>
                      <Pill
                        tone={
                          detail.state === "built"
                            ? "good"
                            : detail.state === "partial"
                              ? "warn"
                              : "bad"
                        }
                      >
                        {detail.state}
                      </Pill>
                      <span className="ml-2 text-ink-2">{detail.detail}</span>
                    </>
                  ) : (
                    "not a tracked component"
                  )}
                </p>
              </div>
              <div>
                <div className="label">live state</div>
                <p className="mt-1 text-[12.5px]">
                  {selected.liveId
                    ? (run.nodes[selected.liveId]?.state ?? "idle")
                    : "not an executable node"}
                  {run.nodes[selected.liveId ?? ""]?.error && (
                    <span className="ml-2 text-failed">
                      {run.nodes[selected.liveId!]!.error}
                    </span>
                  )}
                </p>
              </div>
            </div>
          </Panel>
        )}

        {/* The part that actually matters. */}
        <Panel
          label="gates — built is not the same as measured"
          hint="the only rows that decide whether a number is a finding or an assertion"
          index={1}
        >
          {!build ? (
            <p className="text-[12.5px] text-ink-2">
              <code className="font-mono text-[11.5px]">build.json</code> not staged.
              Generate it with{" "}
              <code className="font-mono text-[11.5px]">
                forecast status --json out/build.json
              </code>{" "}
              — it is derived from the repo, so it is never out of date with what
              actually exists.
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
                    <span className="display text-[13px]">{gate.label}</span>
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
          <Stat label="tests" value={String(totals?.tests ?? 0)} />
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

        <div className="grid gap-3 lg:grid-cols-3">
          <Callout label="what the chart is claiming" tone="accent">
            An org chart implies hierarchy, so the hierarchy is the real one. λ
            sits above the judge because it makes the final call; the judge sits
            above the champions because it weighs their cases; each champion pairs
            with exactly one lens. Nothing here is arranged for looks.
          </Callout>
          <Callout label="why the lens rank has no peer links">
            In an org chart, siblings with no horizontal edges read as roles that
            do not coordinate. That is exactly right. Lenses that see each other
            converge, and converging rebuilds consensus — which scores zero.
          </Callout>
          <Callout label="why built ≠ done" tone="structure">
            {gatesPassed === gatesTotal
              ? "Every gate is passing: the coefficients are fitted, the baseline is scored and determinism is proven."
              : `${gatesTotal - gatesPassed} gate(s) still open. Almost everything is built; what remains is measurement, and a board that showed only green components would be implying otherwise.`}
          </Callout>
        </div>

        <p className="tech text-ink-3">
          {NODES.length} boxes · 8 ranks · derived from build.json and
          events.ndjson, never hand-maintained
        </p>
      </div>
    </Sheet>
  );
}
