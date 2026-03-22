/**
 * claw-forge Kanban UI — main application component.
 *
 * Columns: Pending | In Progress | Passing | Failed | Blocked
 *
 * Header:
 *   - Project name + dark mode toggle
 *   - Provider pool status dots
 *   - Overall progress bar (X/Y passing)
 *   - Live agent count
 *   - Cost sparkline
 *   - Activity log toggle
 *   - Keyboard shortcuts help
 *
 * Real-time updates via WebSocket (ws://localhost:8420/ws).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  DragOverlay,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Sun,
  Moon,
  Terminal,
  HelpCircle,
  GitBranch,
  LayoutGrid,
  Inbox,
  Zap,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { gsap } from "gsap";
import { FeatureCard } from "./components/FeatureCard";
import { RegressionHealthBar } from "./components/RegressionHealthBar";
import { ProgressBar } from "./components/ProgressBar";
import { ProviderPoolStatus } from "./components/ProviderPoolStatus";
import { FilterBar } from "./components/FilterBar";
import { FeatureDetailDrawer } from "./components/FeatureDetailDrawer";
import { ActivityLogPanel } from "./components/ActivityLogPanel";
import { DependencyGraph } from "./components/DependencyGraph";
import { CostSparkline } from "./components/CostSparkline";
import { CelebrationOverlay } from "./components/CelebrationOverlay";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { ShortcutsModal } from "./components/ShortcutsModal";
import { ToastContainer } from "./components/ToastContainer";
import { CommandPalette } from "./components/CommandPalette";
import { CommandsPanel } from "./components/CommandsPanel";
import { ExecutionDrawer } from "./components/ExecutionDrawer";
import { TaskDetailModal } from "./components/TaskDetailModal";
import { FAB } from "./components/FAB";
import { useFeatures } from "./hooks/useFeatures";
import { usePoolStatus } from "./hooks/usePoolStatus";
import { useDarkMode } from "./hooks/useDarkMode";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { useWebSocket } from "./hooks/useWebSocket";
import { useTouchGestures } from "./hooks/useTouchGestures";
import { useMobileDetect } from "./hooks/useMobileDetect";
import { fetchSession, fetchSessions, fetchCommands, executeCommand, patchTaskStatus, stopTask, stopAllRunning, resumeTask, resumeAllPaused } from "./api";
import { KANBAN_COLUMNS } from "./types";
import type {
  Command,
  Execution,
  Feature,
  FeatureStatus,
  FilterState,
  ViewMode,
} from "./types";

// ── Query client ──────────────────────────────────────────────────────────────

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// ── Board ─────────────────────────────────────────────────────────────────────

/** Derive project summary stats from features. */
function useSummary(features: Feature[]) {
  return useMemo(() => {
    const passing = features.filter((f) => f.status === "completed").length;
    const failing = features.filter((f) => f.status === "failed").length;
    const running = features.filter((f) => f.status === "running").length;
    const blocked = features.filter((f) => f.status === "blocked").length;
    const totalCost = features.reduce((s, f) => s + (f.cost_usd ?? 0), 0);
    return { passing, failing, running, blocked, totalCost, total: features.length };
  }, [features]);
}

/** Filter features based on search, category, and status filters. */
function applyFilters(features: Feature[], filters: FilterState): Feature[] {
  return features.filter((f) => {
    if (
      filters.search &&
      !f.name.toLowerCase().includes(filters.search.toLowerCase())
    ) {
      return false;
    }
    if (
      filters.category !== "All" &&
      f.category.toLowerCase() !== filters.category.toLowerCase()
    ) {
      return false;
    }
    if (filters.statuses.size > 0) {
      const activeStatuses = new Set<FeatureStatus>(filters.statuses);
      if (activeStatuses.has("pending")) activeStatuses.add("queued");
      if (!activeStatuses.has(f.status)) return false;
    }
    return true;
  });
}

// ── PendingDropColumn ─────────────────────────────────────────────────────────

interface PendingDropColumnProps {
  col: (typeof KANBAN_COLUMNS)[number];
  cards: Feature[];
  colIdx: number;
  setColumnRef: (el: HTMLDivElement | null, idx: number) => void;
  isMobile: boolean;
  featuresLoading: boolean;
  setSelectedFeatureId: (id: string) => void;
  setLongPressFeature: (f: Feature) => void;
  implicatedFeatureIds: string[];
}

function PendingDropColumn({
  col,
  cards,
  colIdx,
  setColumnRef,
  isMobile,
  featuresLoading,
  setSelectedFeatureId,
  setLongPressFeature,
  implicatedFeatureIds,
}: PendingDropColumnProps) {
  const { isOver, setNodeRef } = useDroppable({ id: "pending" });

  return (
    <div
      ref={(el) => {
        setNodeRef(el);
        setColumnRef(el, colIdx);
      }}
      className={`flex flex-col rounded-xl border transition-colors duration-200
        ${col.colorClass} ${col.darkColorClass}
        ${isMobile ? "w-full min-w-0" : "min-w-[240px] w-64 flex-shrink-0"}
        ${isOver ? "ring-2 ring-blue-400 ring-dashed bg-blue-50 dark:bg-blue-950/30" : ""}`}
      data-testid={`kanban-column-${col.id}`}
    >
      {/* Column header */}
      <div
        className={`flex items-center justify-between px-3 py-2 rounded-t-xl transition-colors duration-200
          ${col.headerClass} ${col.darkHeaderClass}`}
      >
        <span className="text-sm font-semibold">{col.label}</span>
        <span className="text-xs font-bold bg-white/50 dark:bg-black/20 rounded-full px-2 py-0.5">
          {cards.length}
        </span>
      </div>

      {/* Cards */}
      <div
        className={`flex flex-col gap-2 p-2 overflow-y-auto ${
          isMobile ? "max-h-[calc(100vh-340px)]" : "max-h-[calc(100vh-280px)]"
        }`}
      >
        {isOver && (
          <div className="rounded-lg border-2 border-dashed border-blue-400 py-3 text-center text-xs text-blue-500 dark:text-blue-400">
            Drop here to retry
          </div>
        )}
        {featuresLoading
          ? Array.from({ length: 3 }, (_, i) => (
              <div
                key={i}
                className="h-20 rounded-lg bg-white/60 dark:bg-slate-700/40 animate-pulse"
              />
            ))
          : (
            <AnimatePresence initial={false}>
              {cards.map((feature) => (
                <FeatureCard
                  key={feature.id}
                  feature={feature}
                  onClick={() => setSelectedFeatureId(feature.id)}
                  onLongPress={(f) => setLongPressFeature(f)}
                  implicatedFeatureIds={implicatedFeatureIds}
                />
              ))}
            </AnimatePresence>
          )}
        {!featuresLoading && cards.length === 0 && !isOver && (
          <div className="px-2 py-6 text-center">
            <Inbox
              size={24}
              className="mx-auto text-slate-300 dark:text-slate-600 mb-1"
            />
            <p className="text-xs text-slate-400 dark:text-slate-500 italic">
              Nothing here
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── KanbanBoard ───────────────────────────────────────────────────────────────

interface KanbanBoardProps {
  sessionId: string;
}

function KanbanBoard({ sessionId }: KanbanBoardProps) {
  const qc = useQueryClient();
  const {
    data: features,
    isLoading: featuresLoading,
    error: featuresError,
  } = useFeatures(sessionId);
  const { data: poolData, isLoading: poolLoading } = usePoolStatus();
  const providers = useMemo(() => poolData?.providers ?? [], [poolData?.providers]);
  const modelAliases = useMemo(() => poolData?.model_aliases ?? {}, [poolData?.model_aliases]);
  const { data: sessionData } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetchSession(sessionId),
    staleTime: 60_000,
  });

  const allFeatures = useMemo(() => features ?? [], [features]);

  // Active executions for the ExecutionDrawer (declared before useWebSocket so callback can reference it)
  const [activeExecutions, setActiveExecutions] = useState<Execution[]>([]);

  // Command event handler for WebSocket command_output / command_done events
  const handleCommandEvent = useCallback((event: Record<string, unknown>) => {
    if (event.type === "command_output") {
      const exec_id = event.execution_id as string;
      const line = event.line as string;
      setActiveExecutions((prev) =>
        prev.map((ex) =>
          ex.execution_id === exec_id
            ? { ...ex, output: [...ex.output, line] }
            : ex,
        ),
      );
    } else if (event.type === "command_done") {
      const exec_id = event.execution_id as string;
      const exit_code = event.exit_code as number;
      const duration_ms = event.duration_ms as number;
      setActiveExecutions((prev) =>
        prev.map((ex) =>
          ex.execution_id === exec_id
            ? {
                ...ex,
                status: exit_code === 0 ? "done" : "failed",
                exit_code,
                duration_ms,
              }
            : ex,
        ),
      );
    }
  }, []);

  // Regression implicated feature IDs — declared before useWebSocket so the
  // setter can be passed as onRegressionResult callback
  const [implicatedFeatureIds, setImplicatedFeatureIds] = useState<string[]>([]);


  // Shared WebSocket
  const {
    connectionStatus,
    activityLog,
    costHistory,
    toasts,
    reconnectCountdown,
    forceReconnect,
    addToast,
    removeToast,
    regressionIsRunning,
    regressionRunNumber,
  } = useWebSocket(sessionId, {
    onCommandEvent: handleCommandEvent,
    onRegressionResult: setImplicatedFeatureIds,
  });

  // Dark mode
  const [isDark, toggleDark] = useDarkMode();

  // View mode: kanban | graph
  const [viewMode, setViewMode] = useState<ViewMode>("kanban");

  // Feature detail drawer (desktop)
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(
    null,
  );
  const selectedFeature = useMemo(
    () => allFeatures.find((f) => f.id === selectedFeatureId) ?? null,
    [allFeatures, selectedFeatureId],
  );

  // Task detail modal (long-press, mobile)
  const [longPressFeature, setLongPressFeature] = useState<Feature | null>(null);

  // Filter state
  const [filters, setFilters] = useState<FilterState>({
    search: "",
    category: "All",
    statuses: new Set(),
  });
  const searchInputRef = useRef<HTMLInputElement>(null);


  // Activity log panel
  const [logOpen, setLogOpen] = useState(false);

  // Shortcuts modal
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  // Command palette
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Commands panel (sidebar tab)
  const [commandsPanelOpen, setCommandsPanelOpen] = useState(false);

  // Fetch command registry
  const { data: commands = [] } = useQuery<Command[]>({
    queryKey: ["commands"],
    queryFn: fetchCommands,
    staleTime: Infinity,
  });

  // Column refs for scrolling
  const columnRefs = useRef<(HTMLDivElement | null)[]>([]);

  // ── Touch / Mobile features ─────────────────────────────────────────────
  const isMobile = useMobileDetect();
  const [mobileColumnIndex, setMobileColumnIndex] = useState(0);

  // Pinch-to-zoom & swipe detection
  const { scale, setScale, swipeDirection, clearSwipe, touchHandlers } =
    useTouchGestures({ minScale: 0.5, maxScale: 2 });

  // Handle swipe to navigate columns on mobile
  useEffect(() => {
    if (!isMobile || !swipeDirection) return;
    setMobileColumnIndex((prev) => {
      if (swipeDirection === "left") return Math.min(prev + 1, KANBAN_COLUMNS.length - 1);
      if (swipeDirection === "right") return Math.max(prev - 1, 0);
      return prev;
    });
    clearSwipe();
  }, [swipeDirection, clearSwipe, isMobile]);

  // ── Drag-and-drop (retry failed/blocked tasks) ───────────────────────────
  const [activeFeature, setActiveFeature] = useState<Feature | null>(null);

  const handleDragStart = useCallback(
    ({ active }: DragStartEvent) => {
      const feature = allFeatures.find((f) => f.id === active.id);
      setActiveFeature(feature ?? null);
    },
    [allFeatures],
  );

  const handleDragEnd = useCallback(
    ({ active, over }: DragEndEvent) => {
      setActiveFeature(null);
      if (!over || over.id !== "pending") return;
      const data = active.data.current as { status: string } | undefined;
      if (!data || (data.status !== "failed" && data.status !== "blocked")) return;

      const featureId = active.id as string;

      // Optimistic update
      qc.setQueryData<Feature[]>(["features", sessionId], (prev) =>
        (prev ?? []).map((f) =>
          f.id === featureId ? { ...f, status: "pending" as const } : f,
        ),
      );

      void patchTaskStatus(sessionId, featureId, "pending")
        .then(() => {
          addToast("Task reset to pending — will retry on next run", "success");
        })
        .catch(() => {
          void qc.invalidateQueries({ queryKey: ["features"] });
          addToast("Failed to reset task status", "error");
        });
    },
    [sessionId, qc, addToast],
  );

  // Stop-task controls
  const [stoppingTasks, setStoppingTasks] = useState<Set<string>>(new Set());
  const [stoppingAll, setStoppingAll] = useState(false);
  const [resumingAll, setResumingAll] = useState(false);
  const [resumingTasks, setResumingTasks] = useState<Set<string>>(new Set());

  const handleStopTask = useCallback(
    (taskId: string) => {
      setStoppingTasks((prev) => new Set(prev).add(taskId));
      void stopTask(taskId).catch(() => {
        setStoppingTasks((prev) => {
          const s = new Set(prev);
          s.delete(taskId);
          return s;
        });
        addToast("Failed to stop task", "error");
      });
    },
    [addToast],
  );

  const handleStopAll = useCallback(() => {
    const runningIds = allFeatures
      .filter((f) => f.status === "running")
      .map((f) => f.id);
    setStoppingTasks((prev) => {
      const s = new Set(prev);
      runningIds.forEach((id) => s.add(id));
      return s;
    });
    setStoppingAll(true);
    void stopAllRunning(sessionId).catch(() => {
      setStoppingAll(false);
      setStoppingTasks((prev) => {
        const s = new Set(prev);
        runningIds.forEach((id) => s.delete(id));
        return s;
      });
      addToast("Failed to pause tasks", "error");
    });
  }, [features, sessionId, addToast]);

  const handleResumeAll = useCallback(() => {
    // Optimistically keep all paused cards in the In Progress column during
    // the transition (same behaviour as per-task resume via resumingTasks).
    const pausedIds = allFeatures
      .filter((f) => f.status === "paused")
      .map((f) => f.id);
    setResumingAll(true);
    setResumingTasks((prev) => {
      const next = new Set(prev);
      pausedIds.forEach((id) => next.add(id));
      return next;
    });
    void resumeAllPaused(sessionId).catch(() => {
      setResumingAll(false);
      setResumingTasks((prev) => {
        const next = new Set(prev);
        pausedIds.forEach((id) => next.delete(id));
        return next;
      });
      addToast("Failed to resume tasks", "error");
    });
  }, [sessionId, allFeatures, addToast]);

  const handleResumeTask = useCallback(
    (taskId: string) => {
      setResumingTasks((prev) => new Set(prev).add(taskId));
      void resumeTask(taskId).catch(() => {
        setResumingTasks((prev) => {
          const s = new Set(prev);
          s.delete(taskId);
          return s;
        });
        addToast("Failed to resume task", "error");
      });
    },
    [addToast],
  );

  // Clear per-task and bulk loading states once tasks actually transition
  useEffect(() => {
    const hasRunning = allFeatures.some((f) => f.status === "running");
    const hasPaused = allFeatures.some((f) => f.status === "paused");

    // Clear stoppingAll once no tasks are "running" anymore
    if (!hasRunning) setStoppingAll(false);
    // Clear resumingAll once no tasks are "paused" anymore
    if (!hasPaused) setResumingAll(false);

    // stoppingTasks: clear once the task reaches "paused" (stop complete)
    setStoppingTasks((prev) => {
      if (prev.size === 0) return prev;
      const next = new Set(
        [...prev].filter((id) => {
          const f = allFeatures.find((feat) => feat.id === id);
          // Keep while still "running" (stop in flight); clear on "paused" or gone
          return f?.status === "running";
        }),
      );
      return next.size === prev.size ? prev : next;
    });

    // resumingTasks: clear once the task reaches "running" (resume complete)
    setResumingTasks((prev) => {
      if (prev.size === 0) return prev;
      const next = new Set(
        [...prev].filter((id) => {
          const f = allFeatures.find((feat) => feat.id === id);
          // Keep while "paused" or "pending" (resume in flight); clear on "running" or gone
          return f != null && f.status !== "running" && f.status !== "completed" && f.status !== "failed";
        }),
      );
      return next.size === prev.size ? prev : next;
    });
  }, [features]);

  // FAB handlers
  const handleRefresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["features"] });
    void qc.invalidateQueries({ queryKey: ["pool", "status"] });
    void qc.invalidateQueries({ queryKey: ["regression", "status"] });
  }, [qc]);

  const handleResetZoom = useCallback(() => {
    setScale(1);
  }, [setScale]);

  const summary = useSummary(allFeatures);
  const projectName = (sessionData as Record<string, unknown>)?.project_path as
    | string
    | undefined;

  /** Last folder name of the project path, e.g. "claw-forge-test" */
  const projectFolder = projectName
    ? (projectName.replace(/\/$/, "").split("/").pop() ?? projectName)
    : undefined;

  const agentCountRef = useRef<HTMLSpanElement>(null);
  const displayedRunningRef = useRef(summary.running);

  useEffect(() => {
    const obj = { val: displayedRunningRef.current };
    gsap.to(obj, {
      val: summary.running,
      duration: 0.4,
      ease: "power1.out",
      snap: { val: 1 },
      onUpdate: () => {
        if (agentCountRef.current) {
          agentCountRef.current.textContent = String(Math.round(obj.val));
        }
        displayedRunningRef.current = Math.round(obj.val);
      },
    });
  }, [summary.running]);

  // Apply filters to features
  const filteredFeatures = useMemo(
    () => applyFilters(allFeatures, filters),
    [allFeatures, filters],
  );

  // Assign features to Kanban columns by status
  const columnFeatures = useMemo(() => {
    const map: Record<string, Feature[]> = {};
    for (const col of KANBAN_COLUMNS) {
      map[col.id] = filteredFeatures.filter((f) => {
        // Cards being resumed stay in the In Progress column during transition
        if (resumingTasks.has(f.id) && col.id === "in_progress") return true;
        if (resumingTasks.has(f.id) && col.id !== "in_progress") return false;
        return col.statuses.includes(f.status);
      });
    }
    return map;
  }, [filteredFeatures, resumingTasks]);


  // Execute a command
  const handleExecuteCommand = useCallback(
    async (command: Command) => {
      try {
        const result = await executeCommand(command.id, {});
        const newExec: Execution = {
          execution_id: result.execution_id,
          command_id: command.id,
          command_label: command.label,
          status: "running",
          output: [],
          started_at: Date.now(),
        };
        setActiveExecutions((prev) => [...prev, newExec]);
      } catch (err) {
        console.error("Failed to execute command:", err);
      }
    },
    [],
  );

  const dismissExecution = useCallback((execution_id: string) => {
    setActiveExecutions((prev) =>
      prev.filter((ex) => ex.execution_id !== execution_id),
    );
  }, []);

  // Keyboard shortcuts
  const closeAll = useCallback(() => {
    setSelectedFeatureId(null);
    setShortcutsOpen(false);
    setLogOpen(false);
    setPaletteOpen(false);
  }, []);

  const shortcutHandlers = useMemo(
    () => ({
      toggleDarkMode: toggleDark,
      toggleGraphView: () =>
        setViewMode((v) => (v === "kanban" ? "graph" : "kanban")),
      toggleShortcutsModal: () => setShortcutsOpen((v) => !v),
      focusSearch: () => searchInputRef.current?.focus(),
      closeAll,
      scrollToColumn: (index: number) => {
        columnRefs.current[index]?.scrollIntoView({
          behavior: "smooth",
          inline: "center",
        });
      },
    }),
    [toggleDark, closeAll],
  );

  useKeyboardShortcuts(shortcutHandlers);

  // ⌘K / Ctrl+K → open command palette
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-slate-50 dark:bg-slate-900 transition-colors duration-200">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="bg-white dark:bg-slate-800 border-b-2 border-orange-500/50 px-6 py-3 shadow-sm transition-colors duration-200">
        <div className="max-w-screen-2xl mx-auto">
          {/* Row 1: title + controls + live stats */}
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <span className="text-xl font-bold text-forge-700 dark:text-forge-100">
                ⚒ claw-forge
              </span>
              {projectFolder && (
                <div className="relative group flex items-center gap-1.5 cursor-default">
                  <FolderOpen size={13} className="text-slate-400 dark:text-slate-500 shrink-0" />
                  <span className="text-sm text-slate-500 dark:text-slate-400 font-mono">
                    {projectFolder}
                  </span>
                  {/* Tooltip: full absolute path on hover */}
                  <div className="absolute left-0 top-full mt-2 z-50 hidden group-hover:flex
                    items-center gap-1.5 bg-slate-900 dark:bg-slate-950 text-slate-100
                    text-xs font-mono px-3 py-1.5 rounded-lg shadow-xl whitespace-nowrap
                    pointer-events-none border border-slate-700">
                    <FolderOpen size={11} className="text-slate-400 shrink-0" />
                    {projectName}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-3 text-sm">
              {/* Active agents + task progress */}
              <div className="flex items-center gap-2.5">
                {/* Running agents pill */}
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border transition-colors duration-300
                    ${summary.running > 0
                      ? "bg-blue-50 border-blue-200 dark:bg-blue-950/40 dark:border-blue-800"
                      : "bg-slate-100 border-slate-200 dark:bg-slate-800 dark:border-slate-700"}`}
                  title={`${summary.running} agent${summary.running !== 1 ? "s" : ""} currently running`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full shrink-0 transition-colors duration-300
                      ${summary.running > 0 ? "bg-blue-500 animate-pulse" : "bg-slate-400 dark:bg-slate-500"}`}
                  />
                  <span
                    className={`text-sm font-semibold tabular-nums leading-none transition-colors duration-300
                      ${summary.running > 0 ? "text-blue-700 dark:text-blue-300" : "text-slate-500 dark:text-slate-400"}`}
                  >
                    <span ref={agentCountRef}>{summary.running}</span>
                  </span>
                  <span
                    className={`text-xs leading-none transition-colors duration-300
                      ${summary.running > 0 ? "text-blue-600 dark:text-blue-400" : "text-slate-400 dark:text-slate-500"}`}
                  >
                    {summary.running !== 1 ? "agents" : "agent"} live
                  </span>
                </div>

              </div>

              {/* Cost sparkline */}
              <CostSparkline
                costHistory={costHistory}
                currentCost={summary.totalCost}
              />

              {/* Separator */}
              <div className="w-px h-5 bg-slate-200 dark:bg-slate-700" />

              {/* View toggle */}
              <button
                type="button"
                onClick={() =>
                  setViewMode((v) => (v === "kanban" ? "graph" : "kanban"))
                }
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-all duration-200"
                title={
                  viewMode === "kanban"
                    ? "Switch to Graph (G)"
                    : "Switch to Kanban (G)"
                }
              >
                {viewMode === "kanban" ? (
                  <GitBranch size={18} />
                ) : (
                  <LayoutGrid size={18} />
                )}
              </button>

              {/* Activity log toggle */}
              <button
                type="button"
                onClick={() => setLogOpen((v) => !v)}
                className={`p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all duration-200
                  ${logOpen ? "text-forge-600 dark:text-forge-500 bg-slate-100 dark:bg-slate-700" : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"}`}
                title="Activity Log"
              >
                <Terminal size={18} />
              </button>

              {/* Commands panel toggle */}
              <button
                type="button"
                onClick={() => setCommandsPanelOpen((v) => !v)}
                className={`p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all duration-200
                  ${commandsPanelOpen ? "text-yellow-600 dark:text-yellow-400 bg-slate-100 dark:bg-slate-700" : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"}`}
                title="Commands (⌘K)"
              >
                <Zap size={18} />
              </button>

              {/* Dark mode toggle */}
              <button
                type="button"
                onClick={toggleDark}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-all duration-200"
                title="Toggle dark mode (D)"
              >
                {isDark ? <Sun size={18} /> : <Moon size={18} />}
              </button>

              {/* Shortcuts help */}
              <button
                type="button"
                onClick={() => setShortcutsOpen((v) => !v)}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-all duration-200"
                title="Keyboard shortcuts (?)"
              >
                <HelpCircle size={18} />
              </button>
            </div>
          </div>

          {/* Row 2: progress bar */}
          <div className="mt-2">
            <ProgressBar passing={summary.passing} total={summary.total} />
          </div>

          {/* Row 3: provider pool */}
          <div className="mt-2">
            <ProviderPoolStatus
              providers={providers}
              modelAliases={modelAliases}
              isLoading={poolLoading}
              onToast={addToast}
            />
          </div>
        </div>
      </header>

      {/* ── Regression health bar ────────────────────────────────────── */}
      <RegressionHealthBar
        isRunning={regressionIsRunning}
        runNumber={regressionRunNumber}
      />

      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      <FilterBar
        filters={filters}
        onFiltersChange={setFilters}
        searchInputRef={searchInputRef}
      />

      {/* ── Main content ────────────────────────────────────────────────── */}
      {viewMode === "kanban" ? (
        <main
          className="flex-1 overflow-x-auto px-4 py-4"
          style={{
            touchAction: isMobile ? "pan-y" : "auto",
          }}
          {...touchHandlers}
        >
          <div
            className="max-w-screen-2xl mx-auto"
            style={{
              transform: `scale(${scale})`,
              transformOrigin: "top left",
              transition: "transform 0.1s ease-out",
            }}
            data-testid="kanban-board"
          >
            {featuresError && (
              <div className="mb-4 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400">
                ⚠️ Failed to load features — is the state service running on
                port {(window as Window & typeof globalThis & { __CLAW_FORGE_STATE_PORT__?: number }).__CLAW_FORGE_STATE_PORT__ ?? 8420}?
              </div>
            )}

            {/* Mobile: column navigator header */}
            {isMobile && (
              <div className="flex items-center justify-between mb-3 px-1" data-testid="mobile-column-nav">
                <button
                  type="button"
                  onClick={() => setMobileColumnIndex((v) => Math.max(0, v - 1))}
                  disabled={mobileColumnIndex === 0}
                  className="p-1 rounded-lg text-slate-500 disabled:text-slate-300 dark:text-slate-400 dark:disabled:text-slate-600"
                >
                  <ChevronLeft size={20} />
                </button>
                <div className="flex items-center gap-1.5">
                  {KANBAN_COLUMNS.map((col, idx) => (
                    <button
                      key={col.id}
                      type="button"
                      onClick={() => setMobileColumnIndex(idx)}
                      className={`h-2 rounded-full transition-all duration-200 ${
                        idx === mobileColumnIndex
                          ? "w-6 bg-forge-600"
                          : "w-2 bg-slate-300 dark:bg-slate-600"
                      }`}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => setMobileColumnIndex((v) => Math.min(KANBAN_COLUMNS.length - 1, v + 1))}
                  disabled={mobileColumnIndex === KANBAN_COLUMNS.length - 1}
                  className="p-1 rounded-lg text-slate-500 disabled:text-slate-300 dark:text-slate-400 dark:disabled:text-slate-600"
                >
                  <ChevronRight size={20} />
                </button>
              </div>
            )}

            {/* Columns: flex on desktop, stacked/single on mobile */}
            <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
              <div className={isMobile ? "flex flex-col gap-4" : "flex gap-4 items-start h-full"} data-testid="kanban-columns">
                {KANBAN_COLUMNS.map((col, colIdx) => {
                  const cards = columnFeatures[col.id] ?? [];
                  // On mobile, only show the active column
                  if (isMobile && colIdx !== mobileColumnIndex) return null;

                  // Pending column is a drop target for retrying failed/blocked tasks
                  if (col.id === "pending") {
                    return (
                      <PendingDropColumn
                        key={col.id}
                        col={col}
                        cards={cards}
                        colIdx={colIdx}
                        setColumnRef={(el, idx) => {
                          columnRefs.current[idx] = el;
                        }}
                        isMobile={isMobile}
                        featuresLoading={featuresLoading}
                        setSelectedFeatureId={setSelectedFeatureId}
                        setLongPressFeature={setLongPressFeature}
                        implicatedFeatureIds={implicatedFeatureIds}
                      />
                    );
                  }

                  return (
                    <div
                      key={col.id}
                      ref={(el) => {
                        columnRefs.current[colIdx] = el;
                      }}
                      className={`flex flex-col rounded-xl border ${col.colorClass} ${col.darkColorClass} transition-colors duration-200
                        ${isMobile ? "w-full min-w-0" : "min-w-[240px] w-64 flex-shrink-0"}`}
                      data-testid={`kanban-column-${col.id}`}
                    >
                      {/* Column header */}
                      <div
                        className={`flex items-center justify-between px-3 py-2 rounded-t-xl ${col.headerClass} ${col.darkHeaderClass} transition-colors duration-200`}
                      >
                        <span className="text-sm font-semibold">{col.label}</span>
                        <div className="flex items-center gap-2">
                          {col.id === "in_progress" && (cards.some((c) => c.status === "paused") || resumingAll) && (
                            <button
                              type="button"
                              onClick={handleResumeAll}
                              disabled={resumingAll}
                              className={`text-[10px] font-medium transition-colors flex items-center gap-0.5 ${
                                resumingAll
                                  ? "text-purple-400 dark:text-purple-500 cursor-wait"
                                  : "text-purple-500 hover:text-purple-700 dark:text-purple-400 dark:hover:text-purple-300"
                              }`}
                              title="Resume all paused tasks"
                            >
                              {resumingAll ? (
                                <><span className="inline-block w-2.5 h-2.5 border border-purple-400 border-t-transparent rounded-full animate-spin" /> Resuming…</>
                              ) : (
                                <>▶ Resume All</>
                              )}
                            </button>
                          )}
                          {col.id === "in_progress" && (cards.some((c) => c.status === "running") || stoppingAll) && !cards.some((c) => c.status === "paused") && !resumingAll && (
                            <button
                              type="button"
                              onClick={handleStopAll}
                              disabled={stoppingAll}
                              className={`text-[10px] font-medium transition-colors flex items-center gap-0.5 ${
                                stoppingAll
                                  ? "text-red-400 dark:text-red-500 cursor-wait"
                                  : "text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                              }`}
                              title="Pause all running tasks"
                            >
                              {stoppingAll ? (
                                <><span className="inline-block w-2.5 h-2.5 border border-red-400 border-t-transparent rounded-full animate-spin" /> Stopping…</>
                              ) : (
                                <>■ Stop All</>
                              )}
                            </button>
                          )}
                          <span className="text-xs font-bold bg-white/50 dark:bg-black/20 rounded-full px-2 py-0.5">
                            {cards.length}
                          </span>
                        </div>
                      </div>

                      {/* Cards */}
                      <div className={`flex flex-col gap-2 p-2 overflow-y-auto ${isMobile ? "max-h-[calc(100vh-340px)]" : "max-h-[calc(100vh-280px)]"}`}>
                        {featuresLoading
                          ? Array.from({ length: 3 }, (_, i) => (
                              <div
                                key={i}
                                className="h-20 rounded-lg bg-white/60 dark:bg-slate-700/40 animate-pulse"
                              />
                            ))
                          : (
                            <AnimatePresence initial={false}>
                              {cards.map((feature) => (
                                <FeatureCard
                                  key={feature.id}
                                  feature={feature}
                                  onClick={() => setSelectedFeatureId(feature.id)}
                                  onLongPress={(f) => setLongPressFeature(f)}
                                  implicatedFeatureIds={implicatedFeatureIds}
                                  onStop={col.id === "in_progress" ? handleStopTask : undefined}
                                  onResume={col.id === "in_progress" ? handleResumeTask : undefined}
                                  isStopping={stoppingTasks.has(feature.id)}
                                  isResuming={resumingTasks.has(feature.id)}
                                />
                              ))}
                            </AnimatePresence>
                          )}
                        {!featuresLoading && cards.length === 0 && (
                          <div className="px-2 py-6 text-center">
                            <Inbox
                              size={24}
                              className="mx-auto text-slate-300 dark:text-slate-600 mb-1"
                            />
                            <p className="text-xs text-slate-400 dark:text-slate-500 italic">
                              Nothing here
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Drag overlay: ghost card following the cursor during drag */}
              <DragOverlay>
                {activeFeature ? (
                  <motion.div
                    initial={{ scale: 1.02, rotate: 1.5 }}
                    animate={{ scale: 1.02, rotate: 1.5 }}
                    className="rounded-lg"
                    style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.2)" }}
                  >
                    <FeatureCard feature={activeFeature} />
                  </motion.div>
                ) : null}
              </DragOverlay>
            </DndContext>
          </div>
        </main>
      ) : (
        <DependencyGraph
          features={features ?? []}
          onSelectFeature={(id) => setSelectedFeatureId(id)}
        />
      )}

      {/* ── Activity log panel ──────────────────────────────────────────── */}
      <ActivityLogPanel
        isOpen={logOpen}
        onToggle={() => setLogOpen((v) => !v)}
        entries={activityLog}
      />

      {/* ── Commands panel ──────────────────────────────────────────────── */}
      <CommandsPanel
        isOpen={commandsPanelOpen}
        commands={commands}
        onToggle={() => setCommandsPanelOpen((v) => !v)}
        onExecute={handleExecuteCommand}
      />

      {/* ── Command palette ─────────────────────────────────────────────── */}
      <CommandPalette
        isOpen={paletteOpen}
        commands={commands}
        onClose={() => setPaletteOpen(false)}
        onExecute={handleExecuteCommand}
      />

      {/* ── Execution drawer ─────────────────────────────────────────────── */}
      <ExecutionDrawer
        executions={activeExecutions}
        onDismiss={dismissExecution}
      />

      {/* ── Feature detail drawer ───────────────────────────────────────── */}
      <FeatureDetailDrawer
        feature={selectedFeature}
        onClose={() => setSelectedFeatureId(null)}
        onSelectFeature={(id) => setSelectedFeatureId(id)}
        allFeatures={features ?? []}
      />

      {/* ── Celebration overlay ─────────────────────────────────────────── */}
      <CelebrationOverlay passing={summary.passing} total={summary.total} />

      {/* ── Shortcuts modal ─────────────────────────────────────────────── */}
      <ShortcutsModal
        isOpen={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />

      {/* ── Toast notifications ─────────────────────────────────────────── */}
      <ToastContainer toasts={toasts} onDismiss={removeToast} />

      {/* ── Task detail modal (long-press on mobile) ──────────────────── */}
      <TaskDetailModal
        feature={longPressFeature}
        onClose={() => setLongPressFeature(null)}
      />

      {/* ── FAB (mobile only) ────────────────────────────────────────────── */}
      {isMobile && (
        <FAB onRefresh={handleRefresh} onResetZoom={handleResetZoom} />
      )}

      {/* ── Connection status ───────────────────────────────────────────── */}
      <ConnectionIndicator
        status={connectionStatus}
        reconnectCountdown={reconnectCountdown}
        onReconnect={forceReconnect}
      />
    </div>
  );
}

// ── Session selector (shown when no session in URL) ───────────────────────────

/** Filter out sessions created by pytest (tmp_path artifacts). */
function isRealSession(s: { project_path: string }): boolean {
  const p = s.project_path;
  return !p.includes("/pytest-") && !p.includes("/tmp/") && !p.includes("\\Temp\\");
}

function SessionSelector({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: rawSessions, isLoading, error, refetch } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 5000,
  });

  // Filter out test artifacts and auto-select the latest real session
  const sessions = rawSessions?.filter(isRealSession);
  const autoSelected = useRef(false);
  useEffect(() => {
    if (sessions && sessions.length > 0 && !autoSelected.current) {
      autoSelected.current = true;
      onSelect(sessions[0].id);
    }
  }, [sessions, onSelect]);

  const fmt = (iso: string) => {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const statusColor: Record<string, string> = {
    pending: "text-yellow-500",
    running: "text-blue-500",
    completed: "text-green-500",
    failed: "text-red-500",
  };

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="rounded-2xl bg-white dark:bg-slate-800 shadow-xl p-8 w-full max-w-lg border-t-4 border-orange-500">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-1">
          ⚒ claw-forge
        </h1>
        <p className="text-slate-500 dark:text-slate-400 text-sm mb-5">
          Select a session to open the Kanban board.
        </p>

        {isLoading && (
          <p className="text-sm text-slate-400 dark:text-slate-500 text-center py-6">Loading sessions…</p>
        )}
        {error && (
          <p className="text-sm text-red-500 text-center py-4">
            ⚠️ Could not load sessions — is the state service running?
          </p>
        )}
        {sessions && sessions.length === 0 && (
          <p className="text-sm text-slate-400 dark:text-slate-500 text-center py-6">
            No sessions yet. Run <code className="font-mono text-xs bg-slate-100 dark:bg-slate-700 px-1 rounded">claw-forge run</code> to start one.
          </p>
        )}
        {sessions && sessions.length > 0 && (
          <ul className="space-y-2 max-h-80 overflow-y-auto mb-4">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  className="w-full text-left rounded-lg border border-slate-200 dark:border-slate-600
                    hover:border-forge-400 dark:hover:border-forge-500
                    hover:bg-forge-50 dark:hover:bg-slate-700
                    px-4 py-3 transition-colors group"
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-semibold uppercase tracking-wide ${statusColor[s.status] ?? "text-slate-400"}`}>
                      {s.status}
                    </span>
                    <span className="text-xs text-slate-400 dark:text-slate-500">{fmt(s.created_at)}</span>
                  </div>
                  <div className="text-xs font-mono text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                    {s.project_path}
                  </div>
                  <div className="text-xs font-mono text-slate-300 dark:text-slate-600 mt-0.5 truncate group-hover:text-slate-400">
                    {s.id}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}

        <button
          type="button"
          onClick={() => void refetch()}
          className="w-full text-sm text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors py-1"
        >
          ↻ Refresh
        </button>
      </div>
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

function AppInner() {
  // Check URL for session id: /?session=<uuid> or /#<uuid>
  const params = new URLSearchParams(window.location.search);
  const urlSession =
    params.get("session") ?? window.location.hash.replace("#", "");

  const [sessionId, setSessionId] = useState(urlSession || "");

  if (!sessionId) {
    return <SessionSelector onSelect={(id) => {
      setSessionId(id);
      window.location.hash = id;
    }} />;
  }

  return <KanbanBoard sessionId={sessionId} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  );
}
