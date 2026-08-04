/**
 * Reading the pipeline's output.
 *
 * There is no API. The Python process appends JSON lines to out/events.ndjson
 * and writes out/results.json; this polls those files. No server to crash
 * mid-demo, no ports, no CORS.
 *
 * REPLAY MODE IS THE DEMO FALLBACK, and it is better than a video because it IS
 * the real interface: `?replay=nvda` streams a recorded event log at its
 * original pacing through this identical code path. If the live run dies on
 * stage you change one URL and nobody notices.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import type { Event, Forecast } from "./types";

export type NodeState = "idle" | "running" | "done" | "failed";

export interface NodeStatus {
  state: NodeState;
  latencyMs?: number;
  error?: string;
  payload?: Record<string, unknown>;
}

export interface RunState {
  events: Event[];
  nodes: Record<string, NodeStatus>;
  claims: number;
  started: boolean;
  finished: boolean;
  /** Null until the run finishes; the live view works entirely off events. */
  result: RunResult | null;
  source: "live" | "replay" | "waiting";
}

export interface RunResult {
  forecast: Forecast;
  trace: Record<string, unknown>;
}

const POLL_MS = 250;

/** Fold the event log into per-node state. Pure, so replay and live agree. */
export function reduceEvents(events: Event[]): Omit<RunState, "result" | "source"> {
  const nodes: Record<string, NodeStatus> = {};
  let claims = 0;
  let started = false;
  let finished = false;

  for (const event of events) {
    switch (event.type) {
      case "run_start":
        started = true;
        break;
      case "run_done":
        finished = true;
        break;
      case "claim_added":
        claims += Number(event.payload?.n ?? 0);
        break;
      case "node_start":
        if (event.node) nodes[event.node] = { state: "running" };
        break;
      case "node_done":
        if (event.node)
          nodes[event.node] = {
            state: "done",
            latencyMs: Number(event.payload?.latency_ms ?? 0),
            payload: event.payload,
          };
        break;
      case "node_failed":
        if (event.node)
          nodes[event.node] = {
            state: "failed",
            latencyMs: Number(event.payload?.latency_ms ?? 0),
            error: String(event.payload?.error ?? "failed"),
            payload: event.payload,
          };
        break;
    }
  }
  return { events, nodes, claims, started, finished };
}

function parseNdjson(text: string): Event[] {
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      try {
        return JSON.parse(line) as Event;
      } catch {
        // A partially-written final line is normal: we are polling a file the
        // pipeline is still appending to. Skip it; the next poll gets it whole.
        return null;
      }
    })
    .filter((e): e is Event => e !== null);
}

/**
 * Poll the event log and the result file.
 *
 * `?replay=<name>` reads a recorded log from /replays/<name>.ndjson and streams
 * it at its original pacing using each event's own ts_ms.
 */
export function useRun(): RunState {
  const [events, setEvents] = useState<Event[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);
  const [source, setSource] = useState<RunState["source"]>("waiting");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const replay = new URLSearchParams(window.location.search).get("replay");

    if (replay) {
      setSource("replay");
      let cancelled = false;

      void (async () => {
        const [logRes, resultRes] = await Promise.all([
          fetch(`/replays/${replay}.ndjson`),
          fetch(`/replays/${replay}.json`).catch(() => null),
        ]);
        if (cancelled || !logRes.ok) return;

        const recorded = parseNdjson(await logRes.text());
        // Original pacing, from the events themselves, so a replay runs at the
        // speed the run actually took rather than an arbitrary one.
        for (let i = 0; i < recorded.length; i++) {
          const at = recorded[i].ts_ms;
          timers.current.push(
            setTimeout(() => setEvents(recorded.slice(0, i + 1)), at),
          );
        }
        if (resultRes?.ok) {
          const payload = (await resultRes.json()) as RunResult;
          const last = recorded[recorded.length - 1]?.ts_ms ?? 0;
          timers.current.push(setTimeout(() => setResult(payload), last));
        }
      })();

      return () => {
        cancelled = true;
        timers.current.forEach(clearTimeout);
        timers.current = [];
      };
    }

    let alive = true;
    const tick = async () => {
      try {
        const res = await fetch(`/events.ndjson?t=${Date.now()}`, {
          cache: "no-store",
        });
        if (res.ok && alive) {
          setEvents(parseNdjson(await res.text()));
          setSource("live");
        }
      } catch {
        /* the file may not exist yet — that is the waiting state, not an error */
      }
      try {
        const res = await fetch(`/results.json?t=${Date.now()}`, {
          cache: "no-store",
        });
        if (res.ok && alive) setResult((await res.json()) as RunResult);
      } catch {
        /* not finished yet */
      }
    };

    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return { ...reduceEvents(events), result, source };
}

/** Static fetch for the screens that do not need the live stream. */
export function useResult(): RunResult | null {
  const [result, setResult] = useState<RunResult | null>(null);
  useEffect(() => {
    const replay = new URLSearchParams(window.location.search).get("replay");
    const url = replay ? `/replays/${replay}.json` : "/results.json";
    void fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setResult(data as RunResult))
      .catch(() => setResult(null));
  }, []);
  return result;
}

/**
 * Stage D's output, from `out/model.json`.
 *
 * Fetched separately from `results.json` on purpose. The model stage is
 * deterministic and free — `forecast model --dossier ...` builds it with no
 * network, no API key and no model call — so the sheet has to be able to render
 * it when no forecast run exists at all. Requiring a full seven-lens run to look
 * at a three-statement model would make the cheapest stage the hardest to see.
 */
export interface StatementRow {
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

export interface QuarterCheck {
  period: string;
  modelled_eps: number | null;
  actual_eps: number | null;
  modelled_net_income: number | null;
  actual_net_income: number | null;
  eps_error: number | null;
  balanced: boolean;
}

/**
 * The reported history laid out as three statements.
 *
 * Keys are short and empty fields are dropped, and the filing a figure came out
 * of is referenced by index into a per-statement table rather than repeated on
 * every cell — a 10-Q has one accession and sixty rows read out of it. Spelling
 * it all out cost 1.9 MB on a file the sheet fetches on load.
 */
export interface GridCell {
  /** The value. Null and absent both mean "not reported". */
  v: number | null;
  /** What the cell CONTAINS, which is what sets its colour. Absent = derived. */
  o?: "actual" | "derived" | "link";
  /** Index into the statement's `filings` table. */
  s?: number;
  /** How this figure was arrived at, when that is not obvious. */
  n?: string;
}

export interface GridLink {
  statement: "income" | "cashflow" | "balance";
  row: string;
  direction: "from" | "to";
  note: string;
}

export interface GridRow {
  id: string;
  label: string;
  style: "header" | "line" | "subtotal" | "total" | "memo" | "check";
  level: number;
  unit: "usd" | "pct" | "days" | "shares" | "per_share" | "ratio";
  note?: string;
  links?: GridLink[];
  cells: Record<string, GridCell>;
}

export interface GridPeriod {
  id: string;
  label: string;
  kind: "quarter" | "annual";
  fy: number;
  fp: string;
  quarters: number;
  complete: boolean;
  /** A projected column. The A/E boundary is the single most important division
   *  on a model sheet — a reader has to know without looking twice where the
   *  filings stop and the assumptions start. */
  estimate?: boolean;
}

export interface GridPayload {
  statement: string;
  title: string;
  ticker: string;
  periods: GridPeriod[];
  rows: GridRow[];
  filings: Array<{ uri: string | null; filed: string | null; form: string | null }>;
  annual_variances: Record<string, Record<string, [number, number]>>;
}

export type GridSet = Record<"income" | "cashflow" | "balance", GridPayload>;

/**
 * The valuation.
 *
 * `provenance` is the field that matters. A DCF where the reader cannot tell the
 * measured inputs from the invented ones is a number-shaped opinion, and the
 * sheet colours every assumption by which it is.
 */
export interface DcfInput {
  value: number;
  provenance: "measured" | "assumed" | "market";
  note: string;
}

export interface DcfYear {
  year: number;
  label: string;
  growth: number;
  revenue: number;
  ebit: number;
  nopat: number;
  da: number;
  capex: number;
  delta_nwc: number;
  fcf: number;
  discount_factor: number;
  present_value: number;
}

export interface DcfPayload {
  ticker: string;
  wacc: number;
  cost_of_equity: number | null;
  terminal_growth: number;
  forecast_years: number | null;
  mid_year: boolean | null;
  rows: DcfYear[];
  terminal_value: number;
  pv_terminal: number;
  pv_explicit: number;
  terminal_share: number;
  enterprise_value: number;
  net_debt: number;
  equity_value: number;
  shares: number;
  value_per_share: number;
  market_price: number | null;
  upside: number | null;
  /** The reverse DCF: the growth the current price requires. The only output
   *  here that makes no claim about fair value. */
  implied_growth: number | null;
  implied_note: string;
  sensitivity: {
    wacc_steps: number[];
    growth_steps: number[];
    values: Array<Array<number | null>>;
  };
  assumptions: Record<string, DcfInput>;
  warnings: string[];
}

export interface ModelPayload {
  ticker: string;
  base_period: string;
  forecast_period: string;
  balanced: boolean;
  balance_detail: string;
  statements: {
    income_statement?: StatementRow[];
    cash_flow?: StatementRow[];
    balance_sheet?: StatementRow[];
  };
  ratios: Record<string, number>;
  notes: Record<string, string>;
  checks: QuarterCheck[];
  median_abs_eps_error: number | null;
  bias: number | null;
  skipped: string[];
  /** Quarterly and annual are separate layouts, not one table with a toggle —
   *  commingling them is how the SUM(Q1:Q4) rule gets applied to a balance
   *  sheet, which produces a plausible number that means nothing. */
  grids?: Record<"quarter" | "annual", GridSet>;
  /** Absent when the history is too thin to build one honestly; `dcf_note` then
   *  says why, because a missing valuation is a finding rather than a blank. */
  dcf?: DcfPayload | null;
  dcf_note?: string;
  base_fiscal_year?: number | null;
  /** The forecast side: linked, balance-checked fiscal years with every driver
   *  held at its historical level. Articulation without a view. */
  projected?: ProjectedYear[];
}

export interface ProjectedYear {
  fy: number;
  label: string;
  balanced: boolean;
  balance_residual: number;
  income: Record<string, number>;
  cashflow: Record<string, number>;
  balance: Record<string, number>;
  drivers: Record<string, { value: number; origin: string; note: string }>;
}

export function useModel(): ModelPayload | null {
  const [model, setModel] = useState<ModelPayload | null>(null);
  useEffect(() => {
    void fetch(`/model.json?t=${Date.now()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setModel(data as ModelPayload))
      // No model.json is a legitimate state — nothing has been built yet — so
      // it is an empty sheet with the command on it, not an error.
      .catch(() => setModel(null));
  }, []);
  return model;
}

// --------------------------------------------------------------------------- //
// formatting
// --------------------------------------------------------------------------- //

export const eps = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toFixed(2)}`;

export const eps4 = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toFixed(4)}`;

export const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;

export const signedPct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export const money = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export const usd4 = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toFixed(4)}`;

/**
 * Recharts' tooltip formatter receives a `ValueType` — string | number | array —
 * not a number. Wrapping the numeric formatters here keeps every chart's call
 * site readable and type-safe rather than casting at each one.
 */
export const tooltip =
  (format: (n: number) => string) =>
  (value: unknown): string =>
    typeof value === "number" ? format(value) : String(value ?? "—");
