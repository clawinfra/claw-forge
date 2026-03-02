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
 * - Agent mascot (if running)
 * - Left border accent by status
 */

import type { Feature } from "../types";
import { AgentMascot } from "./AgentMascot";

interface FeatureCardProps {
  feature: Feature;
  onClick?: () => void;
  /** IDs of features implicated by the last regression failure */
  implicatedFeatureIds?: number[];
  /** Direct boolean flag — true when this feature is implicated in a regression */
  implicatedInRegression?: boolean;
}

const STATUS_BADGE: Record<Feature["status"], string> = {
  pending: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  queued: "bg-indigo-100 text-indigo-700 dark:bg-indigo-800 dark:text-indigo-200",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200",
  failed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200",
  blocked: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200",
};

const STATUS_BORDER: Record<Feature["status"], string> = {
  pending: "border-l-slate-300 dark:border-l-slate-600",
  queued: "border-l-indigo-400 dark:border-l-indigo-600",
  running: "border-l-blue-500 dark:border-l-blue-500",
  completed: "border-l-emerald-500 dark:border-l-emerald-500",
  failed: "border-l-red-500 dark:border-l-red-500",
  blocked: "border-l-amber-500 dark:border-l-amber-500",
};

const CATEGORY_COLOURS: Record<string, string> = {
  backend: "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-200",
  frontend: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-200",
  testing: "bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-200",
  infra: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-200",
  docs: "bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-200",
  security: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200",
};

function categoryColour(category: string): string {
  return CATEGORY_COLOURS[category.toLowerCase()] ?? "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300";
}

function shortId(id: string): string {
  return id.length > 8 ? `…${id.slice(-6)}` : id;
}

export function FeatureCard({
  feature,
  onClick,
  implicatedFeatureIds = [],
  implicatedInRegression = false,
}: FeatureCardProps) {
  const depCount = feature.depends_on.length;
  const featureNumId = Number(feature.id);
  const isImplicated =
    implicatedInRegression ||
    (implicatedFeatureIds.length > 0 && implicatedFeatureIds.includes(featureNumId));
  const isFixingRegression = (
    feature as Feature & { is_fixing_regression?: boolean }
  ).is_fixing_regression;

  return (
    <div
      onClick={onClick}
      className={`group rounded-lg border-l-4 border bg-white dark:bg-slate-800 p-3 shadow-sm
        hover:shadow-md transition-all duration-200 cursor-pointer
        border-slate-200 dark:border-slate-700
        ${STATUS_BORDER[feature.status]}
        ${feature.status === "failed" ? "border-r-red-200 dark:border-r-red-900" : ""}
        ${feature.status === "running" ? "border-r-blue-200 dark:border-r-blue-900" : ""}
        ${isFixingRegression ? "animate-pulse border-yellow-400 dark:border-yellow-400" : ""}
      `}
    >
      {/* Header: ID + status */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 select-none">
          #{shortId(feature.id)}
        </span>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[feature.status]}`}
        >
          {feature.status}
        </span>
      </div>

      {/* Regression badge */}
      {isImplicated && (
        <span
          className="inline-block ml-1 h-2.5 w-2.5 rounded-full bg-red-500 shrink-0"
          title="Regression detected — click for details"
        />
      )}

      {/* Feature name */}
      <p className="mt-1 text-sm font-semibold text-slate-800 dark:text-slate-100 leading-snug line-clamp-2">
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
        <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
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
          <span className="font-mono text-[10px] text-blue-600 dark:text-blue-400 truncate">
            {shortId(feature.session_id)}
          </span>
        </div>
      )}

      {/* Agent mascot */}
      {feature.status === "running" && <AgentMascot featureId={feature.id} />}

      {/* Error message */}
      {feature.status === "failed" && feature.error_message && (
        <p className="mt-1.5 text-[10px] text-red-600 dark:text-red-400 line-clamp-2 leading-snug">
          {feature.error_message}
        </p>
      )}

      {/* Footer: deps + cost */}
      <div className="mt-2 flex items-center justify-between">
        {depCount > 0 ? (
          <span className="text-[10px] text-slate-400 dark:text-slate-500" title="Dependency count">
            🔗 {depCount} dep{depCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <span />
        )}
        {feature.cost_usd > 0 && (
          <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
            ${feature.cost_usd.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  );
}
