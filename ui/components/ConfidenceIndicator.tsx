"use client";

interface ConfidenceIndicatorProps {
  confidence: number; // 0-100
}

export default function ConfidenceIndicator({
  confidence,
}: ConfidenceIndicatorProps) {
  const getColor = (conf: number) => {
    if (conf >= 75) return "text-green-600";
    if (conf >= 60) return "text-yellow-600";
    return "text-red-600";
  };

  const getBackgroundColor = (conf: number) => {
    if (conf >= 75) return "bg-green-100";
    if (conf >= 60) return "bg-yellow-100";
    return "bg-red-100";
  };

  const getTrafficLight = (conf: number) => {
    if (conf >= 75) return "🟢";
    if (conf >= 60) return "🟡";
    return "🔴";
  };

  return (
    <div className="space-y-4">
      {/* Confidence Gauge */}
      <div className={`p-6 rounded ${getBackgroundColor(confidence)}`}>
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-semibold text-slate-700">
            Confidence Score
          </span>
          <span className={`text-4xl font-bold ${getColor(confidence)}`}>
            {confidence.toFixed(0)}%
          </span>
        </div>

        {/* Progress Bar */}
        <div className="w-full bg-slate-300 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all duration-300 ${
              confidence >= 75
                ? "bg-green-500"
                : confidence >= 60
                  ? "bg-yellow-500"
                  : "bg-red-500"
            }`}
            style={{ width: `${confidence}%` }}
          />
        </div>
      </div>

      {/* Status Indicators */}
      <div className="space-y-2 text-sm">
        <div className="flex items-center">
          <span className="text-lg mr-2">{getTrafficLight(confidence)}</span>
          <span className="text-slate-700">
            {confidence >= 75
              ? "High confidence: Multiple lenses agree"
              : confidence >= 60
                ? "Medium confidence: Some lens disagreement"
                : "Low confidence: Limited evidence"}
          </span>
        </div>
      </div>

      {/* Breakdown */}
      <div className="p-3 bg-slate-50 rounded text-xs text-slate-600 space-y-1">
        <p>• Based on lens ensemble agreement</p>
        <p>• Adjusted for data staleness</p>
        <p>• Considers consensus dispersion</p>
      </div>
    </div>
  );
}
