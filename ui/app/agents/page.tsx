"use client";

import { useEffect, useState } from "react";

import {
  Callout,
  Display,
  Empty,
  Green,
  Panel,
  Pill,
  Sheet,
  SheetFooter,
  Stat,
  StatusPanel,
} from "@/components/blueprint";
import { sheetOf } from "@/lib/sheets";

/**
 * SHEET 07 — the roster.
 *
 * Read from `agents.json`, which the CLI generates from the prompt files
 * themselves. That indirection is the point: a roster maintained by hand drifts
 * from what actually runs, and then the sheet is confidently describing a system
 * that no longer exists. Prompt version numbers come along for the ride, so a
 * backtest number can always be traced to the prompts that produced it.
 */

interface AgentRow {
  id: string;
  layer: string;
  tier: string;
  version: number | null;
  model: string;
  description: string;
}

interface AgentsPayload {
  agents: AgentRow[];
  tiers: Record<string, string>;
  prepared_companies: number;
}

const TIER_NOTE: Record<string, string> = {
  none: "no model at all — pure arithmetic, cannot hallucinate",
  cheap: "retrieval and extraction",
  mid: "the lenses and the advocate",
  deep: "one call, highest leverage",
};

export default function AgentsScreen() {
  const [data, setData] = useState<AgentsPayload | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    void fetch("/agents.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("none"))))
      .then((payload) => setData(payload as AgentsPayload))
      .catch(() => setMissing(true));
  }, []);

  if (missing || !data) {
    return (
      <Sheet system="agent roster" sheet={sheetOf("/agents/")}>
        <Empty
          title="No roster generated"
          detail="The roster is read from the prompt files rather than maintained by hand, so it cannot drift from what actually runs. Generate it and stage it into the served directory."
          command="uv run forecast agents --json out/agents.json"
        />
      </Sheet>
    );
  }

  const byLayer = data.agents.reduce<Record<string, AgentRow[]>>((acc, agent) => {
    (acc[agent.layer] ??= []).push(agent);
    return acc;
  }, {});
  const tierCounts = data.agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.tier] = (acc[a.tier] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <Sheet
      system="agent roster"
      readout={[`${data.agents.length} AGENTS`, `${Object.keys(byLayer).length} LAYERS`]}
      sheet={sheetOf("/agents/")}
      footer={
        <SheetFooter
          cells={[
            ["source", "read from llm/prompts/*.yaml"],
            ["deterministic", `${tierCounts["none"] ?? 0} agent with no model`],
            ["expensive calls", `${tierCounts["deep"] ?? 0} per run`],
            ["prepared companies", String(data.prepared_companies)],
          ]}
        />
      }
    >
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-[1fr_270px]">
          <Display kicker="Eleven agents, each with a reason to exist. Read from the prompt files themselves — a roster maintained by hand drifts from what actually runs, and then this sheet is confidently describing a system that no longer exists.">
            One system.
            <br />
            <Green>Eleven specialists.</Green>
          </Display>

          <StatusPanel
            title="roster status"
            state="in sync"
            detail="generated from the prompts"
            fraction={1}
            tone="done"
            rows={[
              ["agents", data.agents.length],
              ["no model", tierCounts["none"] ?? 0],
              ["cheap tier", tierCounts["cheap"] ?? 0],
              ["mid tier", tierCounts["mid"] ?? 0],
              ["deep tier", tierCounts["deep"] ?? 0],
            ]}
          />
        </div>

        {Object.entries(byLayer).map(([layer, agents], i) => (
          <Panel key={layer} label={layer} index={i + 1}>
            <div className="scroll-x">
              <table className="w-full min-w-[620px] text-[12.5px]">
                <thead>
                  <tr className="label border-b border-rule">
                    <th className="pb-1.5 text-left">agent</th>
                    <th className="pb-1.5 text-left">tier</th>
                    <th className="pb-1.5 text-left">model</th>
                    <th className="pb-1.5 text-right">prompt v</th>
                    <th className="pb-1.5 pl-4 text-left">what makes it different</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr
                      key={agent.id}
                      className="border-b border-rule-2 last:border-0"
                    >
                      <td className="py-2 pr-3">
                        <span className="display text-[13px]">
                          {agent.id.replace("lens_", "").replace("_", " ")}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        {agent.tier === "none" ? (
                          <Pill tone="accent">no model</Pill>
                        ) : agent.tier === "deep" ? (
                          <Pill tone="warn">{agent.tier}</Pill>
                        ) : (
                          <Pill tone="neutral">{agent.tier}</Pill>
                        )}
                      </td>
                      <td className="tech py-2 pr-3">{agent.model}</td>
                      <td className="num py-2 pr-3 text-right">
                        {agent.version ?? "—"}
                      </td>
                      <td className="py-2 pl-4 leading-snug text-ink-2">
                        {agent.description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        ))}

        <div className="grid gap-3 md:grid-cols-2">
          <Panel label="model tiering" hint="tokens are a variable cost, allocated by leverage">
            <dl className="space-y-2.5">
              {(["none", "cheap", "mid", "deep"] as const).map((tier) => (
                <div key={tier} className="flex items-baseline gap-3">
                  <dt className="tech w-14 shrink-0 text-ink-3">{tier}</dt>
                  <dd className="text-[12.5px]">
                    <span className="num font-semibold">
                      {tierCounts[tier] ?? 0}
                    </span>{" "}
                    <span className="text-ink-2">
                      {tier === "none" ? "" : `× ${data.tiers[tier]} — `}
                      {TIER_NOTE[tier]}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>

          <div className="space-y-3">
            <Callout label="why one agent has no model" tone="accent">
              The Mechanical lens is FX translation, diluted share count, net
              interest and calendar effects — four things that move a quarterly
              EPS number, are fully disclosed, are pure arithmetic, and change
              <em> after</em> consensus is set. It cannot hallucinate, and it will
              be working while every model stage is still flaky.
            </Callout>
            <Callout label="why only one deep call">
              The judge is the highest-leverage decision in the system, so it gets
              the expensive model — once. Everything cheaper sits upstream of it,
              and λ is plain code.
            </Callout>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="agents" value={String(data.agents.length)} />
          <Stat
            label="deterministic"
            value={String(tierCounts["none"] ?? 0)}
            sub="no model, cannot hallucinate"
            accent
          />
          <Stat
            label="expensive calls"
            value={String(tierCounts["deep"] ?? 0)}
            sub="per run"
          />
          <Stat
            label="prepared names"
            value={String(data.prepared_companies)}
            sub="warm start; others derive from the 10-K"
          />
        </div>
      </div>
    </Sheet>
  );
}
