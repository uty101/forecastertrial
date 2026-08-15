"use client";

import { useEffect, useState } from "react";
import EventStreamMonitor from "@/components/EventStreamMonitor";
import ComparisonChart from "@/components/ComparisonChart";
import ConfidenceIndicator from "@/components/ConfidenceIndicator";
import styles from "@/app/globals.css";

interface ForecastState {
  ticker: string;
  asOf: string;
  stage: string;
  stageIndex: number;
  totalStages: number;
  elapsedSeconds: number;
  costSoFar: number;
  costBudget: number;
  consensusEps: number | null;
  forecastEps: number | null;
  keyDrivers: Array<{ lens: string; impact: number; description: string }>;
  confidence: number | null;
  status: "running" | "complete" | "error";
  errorMessage?: string;
}

interface Forecast {
  ticker: string;
  asOf: string;
  consensusEps: number;
  forecastEps: number;
  consensusOpInc: number;
  forecastOpInc: number;
  confidencePercent: number;
}

const STAGES = [
  "ACQUIRE",
  "STRUCTURE",
  "MODEL",
  "ANALYSE",
  "RECONCILE",
  "CHALLENGE",
  "JUDGE",
  "POSITION",
  "OUTPUT",
];

export default function LiveDashboard() {
  const [forecastState, setForecastState] = useState<ForecastState | null>(
    null,
  );
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [selectedLens, setSelectedLens] = useState<string | null>(null);

  // Poll events.ndjson for real-time updates
  useEffect(() => {
    let lastPosition = 0;
    let startTime = Date.now();

    const pollEvents = async () => {
      try {
        const response = await fetch("/out/events.ndjson");
        const text = await response.text();
        const lines = text.split("\n").filter(Boolean);

        const newEvents = lines
          .slice(Math.max(0, lastPosition))
          .map((line) => {
            try {
              return JSON.parse(line);
            } catch {
              return null;
            }
          })
          .filter(Boolean);

        if (newEvents.length > 0) {
          setEvents((prev) => [...prev, ...newEvents]);
          lastPosition = lines.length;

          // Parse latest event for state updates
          const latest = newEvents[newEvents.length - 1];
          if (
            latest.event_type === "stage_started" ||
            latest.event_type === "stage_complete"
          ) {
            const stageIndex = STAGES.indexOf(
              latest.stage?.toUpperCase() || "",
            );
            setForecastState((prev) => ({
              ...(prev || {
                ticker: latest.ticker || "UNKNOWN",
                asOf: latest.as_of || new Date().toISOString().split("T")[0],
                stage: "",
                stageIndex: 0,
                totalStages: STAGES.length,
                elapsedSeconds: 0,
                costSoFar: 0,
                costBudget: 1.5,
                consensusEps: null,
                forecastEps: null,
                keyDrivers: [],
                confidence: null,
                status: "running",
              }),
              stage: latest.stage || "",
              stageIndex: Math.max(0, stageIndex),
              elapsedSeconds: Math.floor((Date.now() - startTime) / 1000),
              costSoFar: latest.cost_so_far || 0,
              ticker: latest.ticker || "UNKNOWN",
            }));
          }

          if (latest.event_type === "forecast_produced") {
            setForecast(latest.forecast);
            setForecastState((prev) =>
              prev
                ? {
                    ...prev,
                    forecastEps: latest.forecast?.forecastEps,
                    consensusEps: latest.forecast?.consensusEps,
                    confidence: latest.forecast?.confidencePercent,
                    status: "complete",
                  }
                : null,
            );
          }

          if (latest.event_type === "lens_complete") {
            setForecastState((prev) =>
              prev
                ? {
                    ...prev,
                    keyDrivers: [
                      ...prev.keyDrivers,
                      {
                        lens: latest.lens_name,
                        impact: latest.impact_bps || 0,
                        description: latest.description || "",
                      },
                    ],
                  }
                : null,
            );
          }

          if (latest.event_type === "error") {
            setForecastState((prev) =>
              prev
                ? {
                    ...prev,
                    status: "error",
                    errorMessage: latest.message,
                  }
                : null,
            );
          }
        }
      } catch (err) {
        // File may not exist yet
        console.debug("Polling events...");
      }
    };

    const interval = setInterval(pollEvents, 1000);
    pollEvents(); // Initial poll
    return () => clearInterval(interval);
  }, []);

  if (!forecastState) {
    return (
      <div className="p-8 text-center">
        <p className="text-lg text-gray-600">
          Waiting for pipeline to start...
        </p>
      </div>
    );
  }

  const progressPercent =
    (forecastState.stageIndex / forecastState.totalStages) * 100;
  const epsDiff =
    forecastState.consensusEps && forecastState.forecastEps
      ? ((forecastState.forecastEps - forecastState.consensusEps) /
          forecastState.consensusEps) *
        100
      : 0;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-slate-900 mb-2">
            Forecast: {forecastState.ticker}
          </h1>
          <p className="text-lg text-slate-600">As of {forecastState.asOf}</p>
        </div>

        {/* Status Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {/* Stage Progress */}
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm text-slate-600 font-semibold mb-2">STAGE</p>
            <p className="text-2xl font-bold text-slate-900 mb-3">
              {forecastState.stage} ({forecastState.stageIndex + 1}/
              {forecastState.totalStages})
            </p>
            <div className="w-full bg-slate-200 rounded-full h-2">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Elapsed Time */}
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm text-slate-600 font-semibold mb-2">ELAPSED</p>
            <p className="text-2xl font-bold text-slate-900">
              {Math.floor(forecastState.elapsedSeconds / 60)}m{" "}
              {forecastState.elapsedSeconds % 60}s
            </p>
          </div>

          {/* Cost */}
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm text-slate-600 font-semibold mb-2">COST</p>
            <p className="text-2xl font-bold text-slate-900">
              ${forecastState.costSoFar.toFixed(2)} / $
              {forecastState.costBudget.toFixed(2)}
            </p>
          </div>

          {/* EPS Diff */}
          {forecastState.forecastEps && (
            <div className="bg-white rounded-lg shadow p-6">
              <p className="text-sm text-slate-600 font-semibold mb-2">
                FORECAST DIFF
              </p>
              <p
                className={`text-2xl font-bold ${epsDiff > 0 ? "text-green-600" : "text-red-600"}`}
              >
                {epsDiff > 0 ? "+" : ""}
                {epsDiff.toFixed(1)}%
              </p>
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Forecast Numbers */}
          <div className="lg:col-span-2 bg-white rounded-lg shadow p-8">
            <h2 className="text-xl font-bold text-slate-900 mb-6">
              EPS Forecast
            </h2>

            {forecastState.consensusEps && forecastState.forecastEps ? (
              <div className="space-y-6">
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <p className="text-sm text-slate-600 font-semibold mb-2">
                      CONSENSUS
                    </p>
                    <p className="text-4xl font-bold text-slate-900">
                      ${forecastState.consensusEps.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-slate-600 font-semibold mb-2">
                      OUR FORECAST
                    </p>
                    <p
                      className={`text-4xl font-bold ${epsDiff > 0 ? "text-green-600" : "text-red-600"}`}
                    >
                      ${forecastState.forecastEps.toFixed(2)}
                    </p>
                  </div>
                </div>

                <ComparisonChart
                  consensus={forecastState.consensusEps}
                  forecast={forecastState.forecastEps}
                />
              </div>
            ) : (
              <p className="text-slate-500 italic">
                Waiting for model to complete...
              </p>
            )}
          </div>

          {/* Confidence */}
          <div className="bg-white rounded-lg shadow p-8">
            <h2 className="text-xl font-bold text-slate-900 mb-6">
              Confidence
            </h2>
            {forecastState.confidence !== null ? (
              <ConfidenceIndicator confidence={forecastState.confidence} />
            ) : (
              <p className="text-slate-500 italic">Calculating...</p>
            )}
          </div>
        </div>

        {/* Key Drivers */}
        {forecastState.keyDrivers.length > 0 && (
          <div className="bg-white rounded-lg shadow p-8 mb-8">
            <h2 className="text-xl font-bold text-slate-900 mb-6">
              Key Drivers
            </h2>
            <div className="space-y-4">
              {forecastState.keyDrivers
                .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                .slice(0, 5)
                .map((driver) => (
                  <div
                    key={driver.lens}
                    className="flex items-center justify-between p-4 bg-slate-50 rounded cursor-pointer hover:bg-slate-100 transition"
                    onClick={() => setSelectedLens(driver.lens)}
                  >
                    <div>
                      <p className="font-semibold text-slate-900">
                        {driver.lens}
                      </p>
                      <p className="text-sm text-slate-600">
                        {driver.description}
                      </p>
                    </div>
                    <div className="text-right">
                      <p
                        className={`text-lg font-bold ${driver.impact > 0 ? "text-green-600" : "text-red-600"}`}
                      >
                        {driver.impact > 0 ? "+" : ""}
                        {driver.impact} bps
                      </p>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Event Stream */}
        <div className="bg-white rounded-lg shadow p-8">
          <h2 className="text-xl font-bold text-slate-900 mb-6">Event Log</h2>
          <EventStreamMonitor events={events.slice(-10)} />
        </div>

        {/* Error Display */}
        {forecastState.status === "error" && (
          <div className="mt-8 bg-red-50 border-l-4 border-red-600 p-6 rounded">
            <p className="text-red-900 font-semibold">Error</p>
            <p className="text-red-700">{forecastState.errorMessage}</p>
          </div>
        )}
      </div>
    </div>
  );
}
