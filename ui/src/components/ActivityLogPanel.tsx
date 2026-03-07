/**
 * ActivityLogPanel — collapsible bottom panel showing real-time WebSocket events.
 *
 * Agent log entries are rendered with role-specific badges (LLM, TOOL, OK, DONE)
 * and a dimmed task-name tag for quick visual scanning.
 * The panel height is resizable by dragging the top edge; size persists in localStorage.
 */
import { useEffect, useRef, useState } from "react";
import { Copy, ChevronDown, ChevronUp } from "lucide-react";
import type { ActivityLogEntry, WsEvent } from "../types";

interface ActivityLogPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  entries: ActivityLogEntry[];
}

/* ── Badge config for system-level events ─────────────────────────────────── */

const EVENT_BADGE: Record<WsEvent["type"], { bg: string; label: string }> = {
  agent_started: { bg: "bg-blue-500", label: "AGENT START" },
  agent_completed: { bg: "bg-emerald-500", label: "AGENT DONE" },
  agent_log: { bg: "bg-cyan-500", label: "AGENT" }, // fallback; overridden per-role
  feature_update: { bg: "bg-purple-500", label: "FEATURE" },
  cost_update: { bg: "bg-amber-500", label: "COST" },
  pool_update: { bg: "bg-slate-400", label: "POOL" },
  regression_started: { bg: "bg-yellow-500", label: "REGRESSION" },
  regression_result: { bg: "bg-orange-500", label: "REGRESSION" },
};

/* ── Role-specific badges for agent_log events ────────────────────────────── */

const ROLE_BADGE: Record<string, { bg: string; label: string }> = {
  assistant:    { bg: "bg-blue-600",    label: "LLM" },
  tool_use:     { bg: "bg-amber-600",   label: "TOOL" },
  tool_result:  { bg: "bg-teal-600",    label: "OK" },
  result:       { bg: "bg-emerald-600", label: "DONE" },
  error:        { bg: "bg-red-600",     label: "ERR" },
};

/* ── Role-specific text color for the content column ─────────────────────── */

const ROLE_TEXT: Record<string, string> = {
  assistant:    "text-blue-300",
  tool_use:     "text-amber-300",
  tool_result:  "text-teal-300",
  result:       "text-emerald-300",
  error:        "text-red-400",
};

/* ── Per-agent label colors (cycles when > 8 agents) ─────────────────────── */

const AGENT_COLORS = [
  "text-violet-400",
  "text-sky-400",
  "text-rose-400",
  "text-lime-400",
  "text-orange-400",
  "text-pink-400",
  "text-cyan-400",
  "text-yellow-400",
];

/* ── Log level styling ────────────────────────────────────────────────────── */

const LEVEL_STYLE: Record<string, { color: string; icon: string }> = {
  info:    { color: "text-slate-500", icon: "·" },
  warning: { color: "text-yellow-400", icon: "▲" },
  error:   { color: "text-red-400", icon: "✖" },
};

const MIN_HEIGHT = 80;
const DEFAULT_HEIGHT = 160;

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
  const [panelHeight, setPanelHeight] = useState<number>(() => {
    const saved = localStorage.getItem("activityLogHeight");
    return saved ? parseInt(saved, 10) : DEFAULT_HEIGHT;
  });
  const dragState = useRef<{ startY: number; startHeight: number } | null>(null);

  useEffect(() => {
    if (!isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, isPaused]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragState.current) return;
      const maxHeight = window.innerHeight * 0.8;
      const delta = dragState.current.startY - e.clientY;
      const newHeight = Math.min(maxHeight, Math.max(MIN_HEIGHT, dragState.current.startHeight + delta));
      setPanelHeight(newHeight);
    };
    const onMouseUp = (e: MouseEvent) => {
      if (!dragState.current) return;
      const maxHeight = window.innerHeight * 0.8;
      const delta = dragState.current.startY - e.clientY;
      const finalHeight = Math.min(maxHeight, Math.max(MIN_HEIGHT, dragState.current.startHeight + delta));
      localStorage.setItem("activityLogHeight", String(finalHeight));
      dragState.current = null;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const onDragHandleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragState.current = { startY: e.clientY, startHeight: panelHeight };
    document.body.style.userSelect = "none";
    document.body.style.cursor = "ns-resize";
  };

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
      className="border-t border-slate-200 dark:border-slate-700 bg-slate-900 dark:bg-slate-950 overflow-hidden transition-[height] duration-300"
      style={{ height: isOpen ? panelHeight : 0 }}
    >
      {/* Drag handle */}
      <div
        className="h-1 cursor-ns-resize bg-slate-700 hover:bg-slate-500 active:bg-blue-500 transition-colors shrink-0"
        onMouseDown={onDragHandleMouseDown}
        title="Drag to resize"
      />

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
        className="h-[calc(100%-36px)] overflow-y-auto px-4 py-1 font-mono text-xs"
        onMouseEnter={() => setIsPaused(true)}
        onMouseLeave={() => setIsPaused(false)}
      >
        {entries.length === 0 ? (
          <p className="text-slate-600 py-4 text-center">
            Waiting for events…
          </p>
        ) : (
          entries.map((entry) => {
            // Use role-specific badge for agent_log; fall back to event badge
            const badge =
              entry.type === "agent_log" && entry.role
                ? ROLE_BADGE[entry.role] ?? EVENT_BADGE.agent_log
                : EVENT_BADGE[entry.type] ?? { bg: "bg-slate-500", label: entry.type };

            const contentColor =
              entry.type === "agent_log" && entry.role
                ? ROLE_TEXT[entry.role] ?? "text-slate-300"
                : "text-slate-300";

            const lvl = entry.level ?? "info";
            const levelStyle = LEVEL_STYLE[lvl] ?? LEVEL_STYLE.info;
            const rowBg = lvl === "error" ? "bg-red-950/30" : lvl === "warning" ? "bg-yellow-950/20" : "";

            return (
              <div
                key={entry.id}
                className={`flex items-start gap-2 py-0.5 leading-relaxed ${rowBg}`}
              >
                {/* Level indicator */}
                <span className={`${levelStyle.color} shrink-0 w-3 text-center`} title={lvl}>
                  {levelStyle.icon}
                </span>

                {/* Timestamp */}
                <span className="text-slate-500 shrink-0">
                  {formatTimestamp(entry.timestamp)}
                </span>

                {/* Role / event badge */}
                <span
                  className={`${badge.bg} text-white px-1.5 py-0 rounded text-[9px] font-bold shrink-0 mt-0.5 min-w-[36px] text-center`}
                >
                  {badge.label}
                </span>

                {/* Agent label + model + task name (agent_log only) */}
                {entry.agentIndex !== undefined && (
                  <span
                    className={`shrink-0 font-semibold text-[10px] ${AGENT_COLORS[(entry.agentIndex - 1) % AGENT_COLORS.length]}`}
                  >
                    agent #{entry.agentIndex}
                    {entry.model && (
                      <span className="text-slate-500 font-normal ml-1 italic">{entry.model}</span>
                    )}
                    {entry.taskName && (
                      <span className="text-slate-400 font-normal ml-1">{entry.taskName}</span>
                    )}
                  </span>
                )}

                {/* Content */}
                <span className={`${contentColor} break-words min-w-0`}>
                  {entry.message}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
