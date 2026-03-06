/**
 * FeatureCard — one card per spec feature, showing all pipeline stages inline.
 *
 * Each feature maps to 1–3 tasks (coding → testing → reviewer).
 * The card shows a compact stage strip with icon + mini progress bar per stage.
 * The card's Kanban column is driven by the group's effectiveStatus.
 *
 * Touch features:
 * - Tap to expand output on mobile (replaces hover)
 * - Long-press (500ms) opens task detail modal
 * - Haptic feedback on status change / drag
 */

import { useEffect, useRef, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import type { Feature, FeatureGroup } from "../types";
import { AgentMascot } from "./AgentMascot";
import { useLongPress } from "../hooks/useLongPress";
import { useMobileDetect } from "../hooks/useMobileDetect";
import { triggerHaptic } from "../utils/haptic";

interface FeatureCardProps {
  group: FeatureGroup;
  onClick?: () => void;
  /** IDs of features implicated by the last regression failure */
  implicatedFeatureIds?: number[];
  /** Called when user selects a quick command action */
  onQuickCommand?: (commandId: string, args: Record<string, unknown>) => void;
  /** Called on long-press — opens task detail modal */
  onLongPress?: (feature: Feature) => void;
  /** Called to stop the currently running task in this group */
  onStop?: (taskId: string) => void;
  /** True while a stop request is in-flight for any task in this group */
  isStopping?: boolean;
}

const STATUS_BADGE: Record<string, string> = {
  pending: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  queued: "bg-indigo-100 text-indigo-700 dark:bg-indigo-800 dark:text-indigo-200",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200",
  paused: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-200",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200",
  failed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200",
  blocked: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200",
};

const STATUS_BORDER: Record<string, string> = {
  pending: "border-l-slate-300 dark:border-l-slate-600",
  queued: "border-l-indigo-400 dark:border-l-indigo-600",
  running: "border-l-blue-500 dark:border-l-blue-500",
  paused: "border-l-purple-400 dark:border-l-purple-500",
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

const STAGE_BAR_COLOR: Record<string, string> = {
  completed: "bg-emerald-500",
  running: "bg-blue-500",
  failed: "bg-red-500",
  blocked: "bg-amber-400",
  paused: "bg-purple-400",
  pending: "",
  queued: "",
};

const STAGE_LABEL_COLOR: Record<string, string> = {
  completed: "text-emerald-600 dark:text-emerald-400",
  running: "text-blue-600 dark:text-blue-400",
  failed: "text-red-500 dark:text-red-400",
  blocked: "text-amber-600 dark:text-amber-400",
  paused: "text-purple-600 dark:text-purple-400",
  pending: "text-slate-400 dark:text-slate-500",
  queued: "text-slate-400 dark:text-slate-500",
};

function stageBarWidth(task: Feature): string {
  if (task.status === "completed" || task.status === "failed" || task.status === "blocked") {
    return "100%";
  }
  if (task.status === "running") {
    return `${task.progress ?? 35}%`;
  }
  return "0%";
}

function categoryColour(category: string): string {
  return (
    CATEGORY_COLOURS[category.toLowerCase()] ??
    "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300"
  );
}

function shortId(id: string): string {
  return id.length > 8 ? `…${id.slice(-6)}` : id;
}

/** Single row in the pipeline strip: icon + mini bar + status label */
function StageRow({ task, icon }: { task: Feature; icon: string }) {
  const barColor = STAGE_BAR_COLOR[task.status] ?? "";
  const isRunning = task.status === "running";
  const label =
    isRunning && task.progress !== undefined ? `${task.progress}%` : task.status;

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] w-4 text-center shrink-0 select-none">{icon}</span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor} ${
            isRunning ? "animate-pulse" : ""
          }`}
          style={{ width: stageBarWidth(task) }}
        />
      </div>
      <span
        className={`text-[9px] font-medium w-[52px] text-right shrink-0 tabular-nums ${
          STAGE_LABEL_COLOR[task.status] ?? STAGE_LABEL_COLOR.pending
        }`}
      >
        {label}
      </span>
    </div>
  );
}

export function FeatureCard({
  group,
  onClick,
  implicatedFeatureIds = [],
  onQuickCommand,
  onLongPress,
  onStop,
  isStopping = false,
}: FeatureCardProps) {
  const [quickMenuOpen, setQuickMenuOpen] = useState(false);
  const [tapped, setTapped] = useState(false);
  const isMobile = useMobileDetect();
  const prevStatusRef = useRef(group.effectiveStatus);

  const isDraggable =
    group.effectiveStatus === "failed" || group.effectiveStatus === "blocked";

  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: group.id,
    data: { status: group.effectiveStatus },
    disabled: !isDraggable,
  });

  const depCount = group.depends_on.length;
  const isImplicated =
    implicatedFeatureIds.length > 0 &&
    implicatedFeatureIds.includes(Number(group.id));

  // The currently running task within this group (for stop button + mascot)
  const runningTask = [group.coding, group.testing, group.reviewer].find(
    (t) => t?.status === "running",
  );

  // Haptic feedback on effective status change
  useEffect(() => {
    if (prevStatusRef.current !== group.effectiveStatus) {
      triggerHaptic(50);
      prevStatusRef.current = group.effectiveStatus;
    }
  }, [group.effectiveStatus]);

  const longPressHandlers = useLongPress({
    duration: 500,
    onLongPress: () => {
      if (onLongPress) onLongPress(group.coding);
    },
    onTap: () => {
      if (isMobile) setTapped((v) => !v);
      if (onClick) onClick();
    },
  });

  const showExpanded = isMobile && tapped;

  const stages: { task: Feature; icon: string }[] = [
    { task: group.coding, icon: group.coding.plugin_name === "bugfix" ? "🐛" : "💻" },
    ...(group.testing ? [{ task: group.testing, icon: "🧪" }] : []),
    ...(group.reviewer ? [{ task: group.reviewer, icon: "📋" }] : []),
  ];

  return (
    <div
      ref={setNodeRef}
      onClick={isMobile ? undefined : onClick}
      {...(isMobile ? longPressHandlers : {})}
      {...listeners}
      {...attributes}
      style={{
        transform: CSS.Transform.toString(transform),
        opacity: isDragging ? 0.5 : undefined,
      }}
      className={`group rounded-lg border-l-4 border bg-white dark:bg-slate-800 p-3 shadow-sm
        hover:shadow-md transition-all duration-200 touch-manipulation
        border-slate-200 dark:border-slate-700
        ${isDraggable ? (isDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer"}
        ${STATUS_BORDER[group.effectiveStatus] ?? STATUS_BORDER.pending}
        ${group.effectiveStatus === "running" ? "border-r-blue-200 dark:border-r-blue-900" : ""}
        ${group.effectiveStatus === "failed" ? "border-r-red-200 dark:border-r-red-900" : ""}
        ${showExpanded ? "ring-2 ring-forge-500/50" : ""}
      `}
      data-testid="feature-card"
    >
      {/* Header: short ID + status badge + controls */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 select-none">
          #{shortId(group.id)}
        </span>
        <div className="flex items-center gap-1">
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              STATUS_BADGE[group.effectiveStatus] ?? STATUS_BADGE.pending
            }`}
          >
            {isStopping ? "stopping…" : group.effectiveStatus}
          </span>

          {/* Stop button */}
          {group.effectiveStatus === "running" && onStop && runningTask && (
            <button
              type="button"
              title="Stop task"
              disabled={isStopping}
              className="text-red-400 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300
                disabled:opacity-40 transition-colors text-[10px] leading-none px-0.5"
              onClick={(e) => {
                e.stopPropagation();
                onStop(runningTask.id);
              }}
            >
              ■
            </button>
          )}

          {/* Quick actions */}
          {onQuickCommand && (
            <div className="relative">
              <button
                type="button"
                title="Quick actions"
                className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-600
                  dark:hover:text-slate-200 transition-opacity text-xs leading-none px-0.5"
                onClick={(e) => {
                  e.stopPropagation();
                  setQuickMenuOpen((v) => !v);
                }}
              >
                ⚡
              </button>
              {quickMenuOpen && (
                <div
                  className="absolute right-0 top-5 z-20 bg-white dark:bg-slate-800 rounded-lg
                    shadow-lg border border-slate-200 dark:border-slate-700 py-1 min-w-max"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    className="w-full text-left px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200
                      hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                    onClick={() => {
                      onQuickCommand("create-bug-report", {
                        feature_id: Number(group.coding.id),
                      });
                      setQuickMenuOpen(false);
                    }}
                  >
                    🐛 Create Bug Report
                  </button>
                  <button
                    type="button"
                    className="w-full text-left px-3 py-1.5 text-xs text-slate-700 dark:text-slate-200
                      hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                    onClick={() => {
                      onQuickCommand("review-pr", {});
                      setQuickMenuOpen(false);
                    }}
                  >
                    📋 Review PR
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
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
        {group.name}
      </p>

      {/* Category badge */}
      {group.category && (
        <span
          className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${categoryColour(group.category)}`}
        >
          {group.category}
        </span>
      )}

      {/* Pipeline stage strip */}
      <div className="mt-2 space-y-1">
        {stages.map(({ task, icon }) => (
          <StageRow key={task.id} task={task} icon={icon} />
        ))}
      </div>

      {/* Agent mascot */}
      {runningTask && <AgentMascot featureId={runningTask.id} />}

      {/* Error message — first failed stage */}
      {group.effectiveStatus === "failed" &&
        (() => {
          const failedTask = [group.reviewer, group.testing, group.coding].find(
            (t) => t?.status === "failed" && t.error_message,
          );
          return failedTask?.error_message ? (
            <p className="mt-1.5 text-[10px] text-red-600 dark:text-red-400 line-clamp-2 leading-snug">
              {failedTask.error_message}
            </p>
          ) : null;
        })()}

      {/* Tap-to-expand (mobile only) */}
      {showExpanded && (
        <div
          className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700 space-y-1.5 animate-fade-in"
          data-testid="card-expanded"
        >
          {group.coding.description && (
            <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
              {group.coding.description}
            </p>
          )}
          {runningTask?.session_id && (
            <p className="text-[10px] font-mono text-blue-500 dark:text-blue-400 truncate">
              Agent: {runningTask.session_id}
            </p>
          )}
          {group.cost_usd > 0 && (
            <p className="text-[10px] text-slate-400">
              Tokens: {group.input_tokens.toLocaleString()} in /{" "}
              {group.output_tokens.toLocaleString()} out
            </p>
          )}
        </div>
      )}

      {/* Footer: dep count + total cost */}
      <div className="mt-2 flex items-center justify-between">
        {depCount > 0 ? (
          <span
            className="text-[10px] text-slate-400 dark:text-slate-500"
            title="Cross-feature dependencies"
          >
            🔗 {depCount} dep{depCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <span />
        )}
        {group.cost_usd > 0 && (
          <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
            ${group.cost_usd.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  );
}
