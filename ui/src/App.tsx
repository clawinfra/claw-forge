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
} from "lucide-react";
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
import { fetchSession, fetchSessions, fetchCommands, executeCommand, patchTaskStatus, stopTask, stopAllRunning } from "./api";
import { KANBAN_COLUMNS } from "./types";
import type {
  Command,
  Execution,
  Feature,
  FeatureGroup,
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

/**
 * Group raw tasks into FeatureGroups by traversing the coding→testing→reviewer
 * dependency chain. Each coding task is a feature root; testing and reviewer
 * tasks are identified by their depends_on links. Non-coding tasks (bugfix etc.)
 * become solo groups.
 */
function groupFeatures(tasks: Feature[]): FeatureGroup[] {
  const byId = new Map(tasks.map((t) => [t.id, t]));

  // Index testing tasks by the coding task ID they depend on
  const testingByCodingId = new Map<string, Feature>();
  // Index reviewer tasks by the testing task ID they depend on
  const reviewerByTestingId = new Map<string, Feature>();

  for (const task of tasks) {
    if (task.plugin_name === "testing") {
      for (const depId of task.depends_on) {
        const dep = byId.get(depId);
        if (dep?.plugin_name === "coding") {
          testingByCodingId.set(dep.id, task);
          break;
        }
      }
    } else if (task.plugin_name === "reviewer") {
      for (const depId of task.depends_on) {
        const dep = byId.get(depId);
        if (dep?.plugin_name === "testing") {
          reviewerByTestingId.set(dep.id, task);
          break;
        }
      }
    }
  }

  const groups: FeatureGroup[] = [];

  for (const task of tasks) {
    // Only coding (and bugfix/other non-standard) tasks are group roots
    if (task.plugin_name === "testing" || task.plugin_name === "reviewer") continue;

    const testing = task.plugin_name === "coding" ? testingByCodingId.get(task.id) : undefined;
    const reviewer = testing ? reviewerByTestingId.get(testing.id) : undefined;
    const stages = [task, testing, reviewer].filter(Boolean) as Feature[];

    // Effective status: drives Kanban column placement
    let effectiveStatus: FeatureStatus = "pending";
    if (stages.some((s) => s.status === "running")) {
      effectiveStatus = "running";
    } else if (stages.some((s) => s.status === "failed")) {
      effectiveStatus = "failed";
    } else if (stages.some((s) => s.status === "blocked")) {
      effectiveStatus = "blocked";
    } else if (stages.every((s) => s.status === "completed")) {
      effectiveStatus = "completed";
    } else if (stages.some((s) => s.status === "queued")) {
      effectiveStatus = "queued";
    }

    groups.push({
      id: task.id,
      name: task.name,
      category: task.category,
      depends_on: task.depends_on,
      effectiveStatus,
      coding: task,
      testing,
      reviewer,
      cost_usd: stages.reduce((s, f) => s + (f.cost_usd ?? 0), 0),
      input_tokens: stages.reduce((s, f) => s + (f.input_tokens ?? 0), 0),
      output_tokens: stages.reduce((s, f) => s + (f.output_tokens ?? 0), 0),
    });
  }

  return groups;
}

/** Derive project summary stats from feature groups (counts features, not subtasks). */
function useSummary(groups: FeatureGroup[]) {
  return useMemo(() => {
    const passing = groups.filter((g) => g.effectiveStatus === "completed").length;
    const failing = groups.filter((g) => g.effectiveStatus === "failed").length;
    const running = groups.filter((g) => g.effectiveStatus === "running").length;
    const blocked = groups.filter((g) => g.effectiveStatus === "blocked").length;
    const totalCost = groups.reduce((s, g) => s + (g.cost_usd ?? 0), 0);
    return { passing, failing, running, blocked, totalCost, total: groups.length };
  }, [groups]);
}

/** Filter feature groups based on search, category, and status filters. */
function applyFilters(groups: FeatureGroup[], filters: FilterState): FeatureGroup[] {
  return groups.filter((g) => {
    if (
      filters.search &&
      !g.name.toLowerCase().includes(filters.search.toLowerCase())
    ) {
      return false;
    }
    if (
      filters.category !== "All" &&
      g.category.toLowerCase() !== filters.category.toLowerCase()
    ) {
      return false;
    }
    if (filters.statuses.size > 0) {
      const effectiveStatuses = new Set<FeatureStatus>(filters.statuses);
      if (effectiveStatuses.has("pending")) effectiveStatuses.add("queued");
      if (!effectiveStatuses.has(g.effectiveStatus)) return false;
    }
    return true;
  });
}

// ── PendingDropColumn ─────────────────────────────────────────────────────────

interface PendingDropColumnProps {
  col: (typeof KANBAN_COLUMNS)[number];
  cards: FeatureGroup[];
  colIdx: number;
  setColumnRef: (el: HTMLDivElement | null, idx: number) => void;
  isMobile: boolean;
  featuresLoading: boolean;
  setSelectedFeatureId: (id: string) => void;
  setLongPressFeature: (f: Feature) => void;
  implicatedFeatureIds: number[];
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
          : cards.map((group) => (
              <FeatureCard
                key={group.id}
                group={group}
                onClick={() => setSelectedFeatureId(group.id)}
                onLongPress={(f) => setLongPressFeature(f)}
                implicatedFeatureIds={implicatedFeatureIds}
              />
            ))}
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

  // Build feature groups from raw tasks (declared early so all hooks below can use it)
  const featureGroups = useMemo(() => groupFeatures(features ?? []), [features]);

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
  const [implicatedFeatureIds, setImplicatedFeatureIds] = useState<number[]>([]);

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
  // Resolve selected group → pass coding task to the detail drawer
  const selectedFeature = useMemo(
    () => featureGroups.find((g) => g.id === selectedFeatureId)?.coding ?? null,
    [featureGroups, selectedFeatureId],
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
  const [activeFeature, setActiveFeature] = useState<FeatureGroup | null>(null);

  const handleDragStart = useCallback(
    ({ active }: DragStartEvent) => {
      const group = featureGroups.find((g) => g.id === active.id);
      setActiveFeature(group ?? null);
    },
    [featureGroups],
  );

  const handleDragEnd = useCallback(
    ({ active, over }: DragEndEvent) => {
      setActiveFeature(null);
      if (!over || over.id !== "pending") return;
      const data = active.data.current as { status: string } | undefined;
      if (!data || (data.status !== "failed" && data.status !== "blocked")) return;

      const groupId = active.id as string;
      const group = featureGroups.find((g) => g.id === groupId);
      if (!group) return;

      // Find the first failed/blocked task within this group to reset
      const taskToReset = [group.reviewer, group.testing, group.coding]
        .filter(Boolean)
        .find((t) => t!.status === "failed" || t!.status === "blocked");
      if (!taskToReset) return;

      // Optimistic update
      qc.setQueryData<Feature[]>(["features", sessionId], (prev) =>
        (prev ?? []).map((f) =>
          f.id === taskToReset.id ? { ...f, status: "pending" as const } : f,
        ),
      );

      void patchTaskStatus(sessionId, taskToReset.id, "pending")
        .then(() => {
          addToast("Task reset to pending — will retry on next run", "success");
        })
        .catch(() => {
          void qc.invalidateQueries({ queryKey: ["features"] });
          addToast("Failed to reset task status", "error");
        });
    },
    [featureGroups, sessionId, qc, addToast],
  );

  // Stop-task controls
  const [stoppingTasks, setStoppingTasks] = useState<Set<string>>(new Set());

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
    const runningIds = (features ?? [])
      .filter((f) => f.status === "running")
      .map((f) => f.id);
    // (uses raw features so all running subtasks are stopped)
    setStoppingTasks((prev) => {
      const s = new Set(prev);
      runningIds.forEach((id) => s.add(id));
      return s;
    });
    void stopAllRunning(sessionId).catch(() => {
      setStoppingTasks((prev) => {
        const s = new Set(prev);
        runningIds.forEach((id) => s.delete(id));
        return s;
      });
      addToast("Failed to stop all tasks", "error");
    });
  }, [features, sessionId, addToast]);

  // Remove task IDs from stoppingTasks once they leave the "running" state
  useEffect(() => {
    if (!features) return;
    const runningIds = new Set(
      features.filter((f) => f.status === "running").map((f) => f.id),
    );
    setStoppingTasks((prev) => {
      const next = new Set([...prev].filter((id) => runningIds.has(id)));
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

  const summary = useSummary(featureGroups);
  const projectName = (sessionData as Record<string, unknown>)?.project_path as
    | string
    | undefined;

  // Apply filters to groups
  const filteredGroups = useMemo(
    () => applyFilters(featureGroups, filters),
    [featureGroups, filters],
  );

  // Assign groups to Kanban columns by effectiveStatus
  const columnFeatures = useMemo(() => {
    const map: Record<string, FeatureGroup[]> = {};
    for (const col of KANBAN_COLUMNS) {
      map[col.id] = filteredGroups.filter((g) =>
        col.statuses.includes(g.effectiveStatus),
      );
    }
    return map;
  }, [filteredGroups]);


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
              {projectName && (
                <span className="text-sm text-slate-500 dark:text-slate-400 font-mono truncate max-w-xs">
                  {projectName}
                </span>
              )}
            </div>

            <div className="flex items-center gap-3 text-sm">
              {/* Active agents */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${summary.running > 0 ? "bg-blue-500 animate-pulse" : "bg-slate-300 dark:bg-slate-600"}`}
                />
                <span className="text-slate-600 dark:text-slate-300 font-medium">
                  {summary.running} agent{summary.running !== 1 ? "s" : ""} live
                </span>
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
                          {col.id === "in_progress" && cards.length > 0 && (
                            <button
                              type="button"
                              onClick={handleStopAll}
                              className="text-[10px] font-medium text-red-500 hover:text-red-700 dark:text-red-400
                                dark:hover:text-red-300 transition-colors flex items-center gap-0.5"
                              title="Stop all running tasks"
                            >
                              ■ Stop All
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
                          : cards.map((group) => (
                              <FeatureCard
                                key={group.id}
                                group={group}
                                onClick={() => setSelectedFeatureId(group.id)}
                                onLongPress={(f) => setLongPressFeature(f)}
                                implicatedFeatureIds={implicatedFeatureIds}
                                onStop={col.id === "in_progress" ? handleStopTask : undefined}
                                isStopping={[group.coding, group.testing, group.reviewer].some(
                                  (t) => t && stoppingTasks.has(t.id),
                                )}
                              />
                            ))}
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
                  <div className="shadow-xl opacity-90 rounded-lg">
                    <FeatureCard group={activeFeature} />
                  </div>
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

function SessionSelector({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: sessions, isLoading, error, refetch } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 5000,
  });

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
    return <SessionSelector onSelect={(id) => setSessionId(id)} />;
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
