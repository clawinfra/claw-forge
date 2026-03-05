/**
 * ActivityLogPanel — collapsible bottom panel showing real-time WebSocket events.
 */
import { useEffect, useRef, useState } from "react";
import { Copy, ChevronDown, ChevronUp } from "lucide-react";
import type { ActivityLogEntry, WsEvent } from "../types";

interface ActivityLogPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  entries: ActivityLogEntry[];
}

const EVENT_BADGE: Record<WsEvent["type"], { bg: string; label: string }> = {
  agent_started: { bg: "bg-blue-500", label: "AGENT START" },
  agent_completed: { bg: "bg-emerald-500", label: "AGENT DONE" },
  agent_log: { bg: "bg-cyan-500", label: "AGENT" },
  feature_update: { bg: "bg-purple-500", label: "FEATURE" },
  cost_update: { bg: "bg-amber-500", label: "COST" },
  pool_update: { bg: "bg-slate-400", label: "POOL" },
  regression_started: { bg: "bg-yellow-500", label: "REGRESSION" },
  regression_result: { bg: "bg-orange-500", label: "REGRESSION" },
};

function formatTimestamp(d: Date): string {
  return d.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ActivityLogPanel({
  isOpen,
  onToggle,
  entries,
}: ActivityLogPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isPaused, setIsPaused] = useState(false);

  useEffect(() => {
    if (!isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, isPaused]);

  const copyAll = () => {
    const text = entries
      .map(
        (e) =>
          `[${formatTimestamp(e.timestamp)}] [${e.type}] ${e.message}`,
      )
      .join("\n");
    void navigator.clipboard.writeText(text);
  };

  return (
    <div
      className={`border-t border-slate-200 dark:border-slate-700 bg-slate-900 dark:bg-slate-950
        transition-all duration-300 ${isOpen ? "h-52" : "h-0"} overflow-hidden`}
    >
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-slate-800 dark:bg-slate-900 border-b border-slate-700">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-2 text-xs font-medium text-slate-300 hover:text-white transition-colors"
        >
          {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          Activity Log ({entries.length})
        </button>
        <div className="flex items-center gap-2">
          <span
            className={`text-[10px] ${isPaused ? "text-amber-400" : "text-slate-500"}`}
          >
            {isPaused ? "⏸ Paused" : "▶ Live"}
          </span>
          <button
            type="button"
            onClick={copyAll}
            className="p-1 text-slate-400 hover:text-white transition-colors"
            title="Copy all"
          >
            <Copy size={12} />
          </button>
        </div>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        className="h-[calc(100%-32px)] overflow-y-auto px-4 py-1 font-mono text-xs"
        onMouseEnter={() => setIsPaused(true)}
        onMouseLeave={() => setIsPaused(false)}
      >
        {entries.length === 0 ? (
          <p className="text-slate-600 py-4 text-center">
            Waiting for events…
          </p>
        ) : (
          entries.map((entry) => {
            const badge = EVENT_BADGE[entry.type] ?? {
              bg: "bg-slate-500",
              label: entry.type,
            };
            return (
              <div
                key={entry.id}
                className="flex items-start gap-2 py-0.5 leading-relaxed"
              >
                <span className="text-slate-500 shrink-0">
                  {formatTimestamp(entry.timestamp)}
                </span>
                <span
                  className={`${badge.bg} text-white px-1.5 py-0 rounded text-[9px] font-bold shrink-0 mt-0.5`}
                >
                  {badge.label}
                </span>
                <span className="text-slate-300">{entry.message}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
