"use client";

import { useEffect, useState } from "react";

interface NarrativeData {
  title: string;
  thesis: string;
  our_forecast: string;
  consensus_context: string;
  our_case: Record<
    string,
    {
      evidence: string;
      quote?: string;
      impact: string;
    }
  >;
  risks: string[];
  narrative: string;
}

export default function NarrativePage() {
  const [narrative, setNarrative] = useState<NarrativeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchNarrative = async () => {
      try {
        const response = await fetch("/out/forecast.json");
        const data = await response.json();
        if (data.narrative) {
          setNarrative(data.narrative);
        }
      } catch (err) {
        console.error("Failed to load narrative:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchNarrative();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-white">
        <p className="text-lg text-gray-600">Loading narrative...</p>
      </div>
    );
  }

  if (!narrative) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-white">
        <p className="text-lg text-gray-600">No narrative available yet</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      {/* Print-friendly layout */}
      <div className="max-w-3xl mx-auto p-12 print:p-8">
        {/* Header */}
        <div className="mb-12 print:mb-8">
          <h1 className="text-4xl print:text-3xl font-bold text-slate-900 mb-4">
            {narrative.title}
          </h1>
          <p className="text-xl print:text-lg text-blue-600 font-semibold mb-2">
            {narrative.our_forecast}
          </p>
          <p className="text-lg print:text-base text-slate-700 italic">
            {narrative.thesis}
          </p>
        </div>

        {/* Consensus Context */}
        <div className="mb-10 print:mb-6 pb-6 print:pb-4 border-b-2 border-slate-200">
          <h2 className="text-xl print:text-lg font-bold text-slate-900 mb-3">
            Why Consensus Moved
          </h2>
          <p className="text-slate-700 leading-relaxed">
            {narrative.consensus_context}
          </p>
        </div>

        {/* Our Case */}
        <div className="mb-10 print:mb-6">
          <h2 className="text-xl print:text-lg font-bold text-slate-900 mb-6 print:mb-4">
            Why We Differ
          </h2>
          <div className="space-y-6 print:space-y-4">
            {Object.entries(narrative.our_case).map(([key, value]) => (
              <div
                key={key}
                className="p-4 print:p-3 bg-blue-50 rounded-lg border-l-4 border-blue-500"
              >
                <p className="font-semibold text-slate-900 mb-2">
                  {value.evidence}
                </p>
                {value.quote && (
                  <p className="text-sm text-slate-700 italic mb-2 pl-3 border-l-2 border-blue-300">
                    "{value.quote}"
                  </p>
                )}
                <p className="text-sm font-semibold text-blue-600">
                  {value.impact}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Risks */}
        <div className="mb-10 print:mb-6 pb-6 print:pb-4 border-b-2 border-slate-200">
          <h2 className="text-xl print:text-lg font-bold text-slate-900 mb-4 print:mb-3">
            What Could Be Wrong
          </h2>
          <ul className="space-y-2 print:space-y-1">
            {narrative.risks.map((risk, idx) => (
              <li key={idx} className="flex items-start text-slate-700">
                <span className="text-red-500 font-bold mr-3 print:mr-2">
                  •
                </span>
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Full Narrative */}
        <div className="mb-10 print:mb-6">
          <h2 className="text-xl print:text-lg font-bold text-slate-900 mb-4 print:mb-3">
            Full Analysis
          </h2>
          <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">
            {narrative.narrative}
          </p>
        </div>

        {/* Footer */}
        <div className="pt-6 print:pt-4 border-t border-slate-300 text-xs text-slate-600">
          <p>
            Generated for Agents vs Wall Street competition • August 16, 2026
          </p>
        </div>
      </div>
    </div>
  );
}
