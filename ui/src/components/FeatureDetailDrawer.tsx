/**
 * FeatureDetailDrawer — right-side slide-in drawer with full feature details.
 */
import { useEffect, useRef } from "react";
import {
  X,
  Clock,
  Play,
  CheckCircle2,
  AlertCircle,
  Link,
  Copy,
  Hash,
  Layers,
  Coins,
  FileText,
  Zap,
  ArrowUpDown,
  ScrollText,
} from "lucide-react";
import type { Feature } from "../types";

interface FeatureDetailDrawerProps {
  feature: Feature | null;
  onClose: () => void;
  onSelectFeature: (featureId: string) => void;
  allFeatures: Feature[];
}

const STATUS_BADGE_STYLE: Record<Feature["status"], string> = {
  pending: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  queued: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
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

export function FeatureDetailDrawer({
  feature,
  onClose,
  onSelectFeature,
  allFeatures,
}: FeatureDetailDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    if (feature) {
      document.addEventListener("mousedown", handleClick);
    }
    return () => document.removeEventListener("mousedown", handleClick);
  }, [feature, onClose]);

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
  };

  return (
    <>
      {/* Backdrop */}
      {feature && (
        <div className="fixed inset-0 z-[80] bg-black/20 transition-opacity duration-200" />
      )}

      {/* Drawer */}
      <div
        ref={drawerRef}
        className={`fixed top-0 right-0 h-full w-[400px] max-w-[90vw] z-[90]
          bg-white dark:bg-slate-800 shadow-2xl border-l border-slate-200 dark:border-slate-700
          transform transition-transform duration-300 ease-out overflow-y-auto
          ${feature ? "translate-x-0" : "translate-x-full"}`}
      >
        {feature && (
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-start justify-between p-5 border-b border-slate-200 dark:border-slate-700">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Hash size={14} className="text-slate-400 shrink-0" />
                  <span className="text-xs font-mono text-slate-400 truncate">
                    {feature.id}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100 leading-snug">
                  {feature.name}
                </h3>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="ml-2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300
                  rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 p-5 space-y-5 overflow-y-auto">
              {/* Status + Category + Priority */}
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${STATUS_BADGE_STYLE[feature.status]}`}
                >
                  {feature.status}
                </span>
                {(feature.category || feature.plugin_name) && (
                  <span className="rounded-full px-3 py-1 text-xs font-medium bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                    {feature.category || feature.plugin_name}
                  </span>
                )}
                {feature.priority !== undefined && feature.priority !== 0 && (
                  <span className="flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300">
                    <ArrowUpDown size={10} />
                    P{feature.priority}
                  </span>
                )}
              </div>

              {/* Description — only if different from the name */}
              {feature.description && feature.description !== feature.name && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                    <FileText size={12} />
                    Description
                  </h4>
                  <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                    {feature.description}
                  </p>
                </div>
              )}

              {/* Timestamps */}
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  <Clock size={12} />
                  Timeline
                </h4>
                <div className="space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Created</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                      {formatTime(feature.created_at)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Started</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                      {formatTime(feature.started_at)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Completed</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">
                      {formatTime(feature.completed_at)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Steps */}
              {feature.steps && feature.steps.length > 0 && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
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

              {/* Dependencies */}
              {feature.depends_on.length > 0 && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                    <Link size={12} />
                    Dependencies ({feature.depends_on.length})
                  </h4>
                  <div className="space-y-1">
                    {feature.depends_on.map((depId) => {
                      const dep = allFeatures.find((f) => f.id === depId);
                      return (
                        <button
                          key={depId}
                          type="button"
                          onClick={() => onSelectFeature(depId)}
                          className="flex items-center gap-2 w-full text-left px-2 py-1.5 rounded-md
                            hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors group"
                        >
                          <span className="text-xs font-mono text-slate-400 truncate">
                            {depId.length > 8 ? `…${depId.slice(-6)}` : depId}
                          </span>
                          {dep && (
                            <span className="text-xs text-slate-600 dark:text-slate-300 truncate group-hover:text-forge-600">
                              {dep.name}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Token usage */}
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  <Coins size={12} />
                  Cost & Tokens
                </h4>
                <div className="space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Input tokens</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">
                      {feature.input_tokens.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Output tokens</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">
                      {feature.output_tokens.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between font-medium">
                    <span className="text-slate-600 dark:text-slate-300">Cost</span>
                    <span className="font-mono text-slate-800 dark:text-slate-200">
                      ${feature.cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Error message */}
              {feature.error_message && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-red-500 uppercase tracking-wider mb-2">
                    <AlertCircle size={12} />
                    Error
                  </h4>
                  <div className="relative group">
                    <pre className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words">
                      {feature.error_message}
                    </pre>
                    <button
                      type="button"
                      onClick={() => copyToClipboard(feature.error_message ?? "")}
                      className="absolute top-2 right-2 p-1 rounded bg-red-100 dark:bg-red-900
                        text-red-500 opacity-0 group-hover:opacity-100 transition-opacity
                        hover:bg-red-200 dark:hover:bg-red-800"
                      title="Copy error"
                    >
                      <Copy size={12} />
                    </button>
                  </div>
                </div>
              )}

              {/* Result output */}
              {feature.result_json && Object.keys(feature.result_json).length > 0 && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                    <Zap size={12} />
                    Result
                  </h4>
                  <div className="space-y-2">
                    {Object.entries(feature.result_json).map(([key, val]) => {
                      if (val === null || val === undefined) return null;
                      const label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                      if (typeof val === "object") {
                        return (
                          <div key={key} className="relative group">
                            <p className="text-[10px] font-semibold text-slate-400 dark:text-slate-500 mb-0.5">{label}</p>
                            <pre className="text-xs text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words">
                              {JSON.stringify(val, null, 2)}
                            </pre>
                            <button
                              type="button"
                              onClick={() => copyToClipboard(JSON.stringify(val, null, 2))}
                              className="absolute top-6 right-2 p-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity"
                              title="Copy"
                            >
                              <Copy size={10} />
                            </button>
                          </div>
                        );
                      }
                      const strVal = String(val);
                      const isLong = strVal.length > 120;
                      return (
                        <div key={key} className={isLong ? "relative group" : "flex items-start gap-2 justify-between"}>
                          <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
                          {isLong ? (
                            <>
                              <pre className="mt-0.5 text-xs text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words">
                                {strVal}
                              </pre>
                              <button
                                type="button"
                                onClick={() => copyToClipboard(strVal)}
                                className="absolute top-0 right-0 p-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Copy"
                              >
                                <Copy size={10} />
                              </button>
                            </>
                          ) : (
                            <span className="text-xs font-medium text-slate-700 dark:text-slate-200 text-right max-w-[60%] break-words">
                              {typeof val === "boolean" ? (val ? "Yes" : "No") : strVal}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Agent session */}
              {feature.session_id && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                    <Play size={12} />
                    Agent Session
                  </h4>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-slate-600 dark:text-slate-300 truncate">
                      {feature.session_id}
                    </span>
                    <button
                      type="button"
                      onClick={() => copyToClipboard(feature.session_id ?? "")}
                      className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 transition-colors"
                      title="Copy session ID"
                    >
                      <Copy size={12} />
                    </button>
                  </div>
                </div>
              )}

              {/* Progress */}
              {feature.progress !== undefined && feature.status === "running" && (
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                    <CheckCircle2 size={12} />
                    Progress
                  </h4>
                  <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all duration-300"
                      style={{ width: `${feature.progress}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-500 dark:text-slate-400 mt-1 block">
                    {feature.progress}%
                  </span>
                </div>
              )}

              {/* Task metadata footer */}
              <div className="pt-3 border-t border-slate-100 dark:border-slate-700">
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  <ScrollText size={12} />
                  Metadata
                </h4>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="text-slate-400 dark:text-slate-500">Task ID</span>
                    <span className="font-mono text-slate-500 dark:text-slate-400 truncate ml-4">{feature.id}</span>
                  </div>
                  {(feature.plugin_name || feature.category) && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 dark:text-slate-500">Plugin</span>
                      <span className="font-mono text-slate-500 dark:text-slate-400">{feature.plugin_name || feature.category}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-slate-400 dark:text-slate-500">Priority</span>
                    <span className="font-mono text-slate-500 dark:text-slate-400">{feature.priority}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
