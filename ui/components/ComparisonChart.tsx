"use client";

interface ComparisonChartProps {
  consensus: number;
  forecast: number;
}

export default function ComparisonChart({
  consensus,
  forecast,
}: ComparisonChartProps) {
  const maxVal = Math.max(consensus, forecast) * 1.1;
  const consensusWidth = (consensus / maxVal) * 100;
  const forecastWidth = (forecast / maxVal) * 100;
  const diff = ((forecast - consensus) / consensus) * 100;

  return (
    <div className="space-y-6">
      {/* Consensus Bar */}
      <div>
        <div className="flex justify-between mb-2">
          <span className="text-sm font-semibold text-slate-700">
            Consensus
          </span>
          <span className="text-sm font-semibold text-slate-900">
            ${consensus.toFixed(2)}
          </span>
        </div>
        <div className="w-full bg-slate-200 rounded h-8">
          <div
            className="bg-blue-400 h-8 rounded flex items-center px-3 text-white font-semibold text-sm"
            style={{ width: `${consensusWidth}%` }}
          >
            ${consensus.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Our Forecast Bar */}
      <div>
        <div className="flex justify-between mb-2">
          <span className="text-sm font-semibold text-slate-700">
            Our Forecast
          </span>
          <span
            className={`text-sm font-semibold ${diff > 0 ? "text-green-600" : "text-red-600"}`}
          >
            ${forecast.toFixed(2)} ({diff > 0 ? "+" : ""}
            {diff.toFixed(1)}%)
          </span>
        </div>
        <div className="w-full bg-slate-200 rounded h-8">
          <div
            className={`h-8 rounded flex items-center px-3 text-white font-semibold text-sm ${
              diff > 0 ? "bg-green-500" : "bg-red-500"
            }`}
            style={{ width: `${forecastWidth}%` }}
          >
            ${forecast.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Difference Indicator */}
      <div className="p-4 bg-slate-50 rounded border-l-4 border-slate-300">
        <p className="text-sm text-slate-600">
          We forecast{" "}
          <span
            className={`font-bold ${diff > 0 ? "text-green-600" : "text-red-600"}`}
          >
            {Math.abs(diff).toFixed(1)}% {diff > 0 ? "above" : "below"}
          </span>{" "}
          consensus.
        </p>
      </div>
    </div>
  );
}
