/**
 * FeatureCard — individual feature card for the Kanban board.
 *
 * Shows:
 * - Feature ID + name
 * - Category badge
 * - Dependency count
 * - Agent session ID (if running)
 * - Progress bar (if progress is set)
 * - Cost in USD
 */

import type { Feature } from "../types";

interface FeatureCardProps {
  feature: Feature;
}

const STATUS_BADGE: Record<Feature["status"], string> = {
  pending: "bg-slate-100 text-slate-600",
  queued: "bg-indigo-100 text-indigo-700",
  running: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  blocked: "bg-amber-100 text-amber-700",
};

const CATEGORY_COLOURS: Record<string, string> = {
  backend: "bg-violet-100 text-violet-700",
  frontend: "bg-cyan-100 text-cyan-700",
  testing: "bg-teal-100 text-teal-700",
  infra: "bg-orange-100 text-orange-700",
  docs: "bg-pink-100 text-pink-700",
  security: "bg-red-100 text-red-700",
};

function categoryColour(category: string): string {
  return CATEGORY_COLOURS[category.toLowerCase()] ?? "bg-slate-100 text-slate-600";
}

function shortId(id: string): string {
  return id.length > 8 ? `…${id.slice(-6)}` : id;
}

export function FeatureCard({ feature }: FeatureCardProps) {
  const depCount = feature.depends_on.length;

  return (
    <div
      className={`group rounded-lg border bg-white p-3 shadow-sm hover:shadow-md transition-shadow
        ${feature.status === "failed" ? "border-red-200" : "border-slate-200"}
        ${feature.status === "completed" ? "border-emerald-200" : ""}
        ${feature.status === "running" ? "border-blue-300" : ""}
      `}
    >
      {/* Header: ID + status */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-mono text-slate-400 select-none">
          #{shortId(feature.id)}
        </span>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[feature.status]}`}
        >
          {feature.status}
        </span>
      </div>

      {/* Feature name */}
      <p className="mt-1 text-sm font-semibold text-slate-800 leading-snug line-clamp-2">
        {feature.name}
      </p>

      {/* Category badge */}
      {feature.category && (
        <span
          className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${categoryColour(feature.category)}`}
        >
          {feature.category}
        </span>
      )}

      {/* Progress bar (when running) */}
      {feature.status === "running" && feature.progress !== undefined && (
        <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-300"
            style={{ width: `${feature.progress}%` }}
          />
        </div>
      )}

      {/* Agent session ID */}
      {feature.session_id && feature.status === "running" && (
        <div className="mt-1.5 flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="font-mono text-[10px] text-blue-600 truncate">
            {shortId(feature.session_id)}
          </span>
        </div>
      )}

      {/* Error message */}
      {feature.status === "failed" && feature.error_message && (
        <p className="mt-1.5 text-[10px] text-red-600 line-clamp-2 leading-snug">
          {feature.error_message}
        </p>
      )}

      {/* Footer: deps + cost */}
      <div className="mt-2 flex items-center justify-between">
        {depCount > 0 ? (
          <span className="text-[10px] text-slate-400" title="Dependency count">
            🔗 {depCount} dep{depCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <span />
        )}
        {feature.cost_usd > 0 && (
          <span className="text-[10px] font-mono text-slate-400">
            ${feature.cost_usd.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  );
}
