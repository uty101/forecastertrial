"use client";

interface EventStreamMonitorProps {
  events: any[];
}

export default function EventStreamMonitor({
  events,
}: EventStreamMonitorProps) {
  return (
    <div className="bg-slate-900 text-slate-100 font-mono text-sm rounded p-4 max-h-64 overflow-y-auto">
      {events.length === 0 ? (
        <p className="text-slate-500">Waiting for events...</p>
      ) : (
        events.map((event, idx) => (
          <div key={idx} className="mb-2 pb-2 border-b border-slate-700">
            <span className="text-blue-400">
              [{event.timestamp || new Date().toISOString()}]
            </span>{" "}
            <span className="text-green-400">{event.event_type}</span>
            {event.stage && (
              <span className="text-yellow-400"> {event.stage}</span>
            )}
            {event.message && (
              <span className="text-slate-300"> {event.message}</span>
            )}
          </div>
        ))
      )}
    </div>
  );
}
