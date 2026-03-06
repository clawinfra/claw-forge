/**
 * TaskDetailModal — full-screen modal for viewing task details.
 * Triggered by long-press on mobile. Shows full description + output/error.
 */
import { useEffect, useRef } from "react";
import { X, Clock, Coins, AlertCircle, FileText, Layers } from "lucide-react";
import type { Feature } from "../types";

interface TaskDetailModalProps {
  feature: Feature | null;
  onClose: () => void;
}

const STATUS_COLOR: Record<Feature["status"], string> = {
  pending: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  queued: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  paused: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  blocked: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
};

function formatTime(ts: string | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function TaskDetailModal({ feature, onClose }: TaskDetailModalProps) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!feature) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [feature, onClose]);

  if (!feature) return null;

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-[100] bg-black/50 flex items-end sm:items-center justify-center"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose();
      }}
      data-testid="task-detail-modal"
    >
      <div className="bg-white dark:bg-slate-800 w-full sm:max-w-lg sm:rounded-2xl rounded-t-2xl max-h-[85vh] overflow-y-auto shadow-2xl animate-slide-up">
        {/* Header */}
        <div className="sticky top-0 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-3 flex items-start justify-between z-10">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLOR[feature.status]}`}>
                {feature.status}
              </span>
              {feature.category && (
                <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  {feature.category}
                </span>
              )}
            </div>
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 leading-snug">
              {feature.name}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-2 p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300
              rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all shrink-0"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4 space-y-4">
          {/* Description */}
          {feature.description && (
            <div>
              <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                <FileText size={12} />
                Description
              </h4>
              <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
                {feature.description}
              </p>
            </div>
          )}

          {/* Steps */}
          {feature.steps && feature.steps.length > 0 && (
            <div>
              <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                <Layers size={12} />
                Steps ({feature.steps.length})
              </h4>
              <ol className="space-y-1">
                {feature.steps.map((step, i) => (
                  <li
                    key={i}
                    className="flex gap-2 text-sm text-slate-600 dark:text-slate-300"
                  >
                    <span className="text-slate-400 font-mono text-xs shrink-0 mt-0.5">
                      {i + 1}.
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Error output */}
          {feature.error_message && (
            <div>
              <h4 className="flex items-center gap-1.5 text-xs font-semibold text-red-500 uppercase tracking-wider mb-1.5">
                <AlertCircle size={12} />
                Error Output
              </h4>
              <pre className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-48">
                {feature.error_message}
              </pre>
            </div>
          )}

          {/* Timeline */}
          <div>
            <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
              <Clock size={12} />
              Timeline
            </h4>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Created</span>
                <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                  {formatTime(feature.created_at)}
                </span>
              </div>
              {feature.started_at && (
                <div className="flex justify-between">
                  <span className="text-slate-500 dark:text-slate-400">Started</span>
                  <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                    {formatTime(feature.started_at)}
                  </span>
                </div>
              )}
              {feature.completed_at && (
                <div className="flex justify-between">
                  <span className="text-slate-500 dark:text-slate-400">Completed</span>
                  <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                    {formatTime(feature.completed_at)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Cost */}
          {feature.cost_usd > 0 && (
            <div>
              <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                <Coins size={12} />
                Cost & Tokens
              </h4>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Input tokens</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {feature.input_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Output tokens</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {feature.output_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between font-medium">
                  <span className="text-slate-600 dark:text-slate-300">Total Cost</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200">
                    ${feature.cost_usd.toFixed(4)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Progress */}
          {feature.progress !== undefined && feature.status === "running" && (
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-slate-500 dark:text-slate-400 font-semibold uppercase">Progress</span>
                <span className="text-xs font-mono text-slate-600 dark:text-slate-300">{feature.progress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-300"
                  style={{ width: `${feature.progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
