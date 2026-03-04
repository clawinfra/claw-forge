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
 * Real-time updates via WebSocket (ws://localhost:8888/ws).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { fetchSession, fetchCommands, executeCommand } from "./api";
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

/** Derive project summary stats from the feature list. */
function useSummary(features: Feature[] | undefined) {
  return useMemo(() => {
    const all = features ?? [];
    const passing = all.filter((f) => f.status === "completed").length;
    const failing = all.filter((f) => f.status === "failed").length;
    const running = all.filter((f) => f.status === "running").length;
    const blocked = all.filter((f) => f.status === "blocked").length;
    const totalCost = all.reduce((s, f) => s + (f.cost_usd ?? 0), 0);
    return { passing, failing, running, blocked, totalCost, total: all.length };
  }, [features]);
}

/** Filter features based on search, category, and status filters. */
function applyFilters(features: Feature[], filters: FilterState): Feature[] {
  return features.filter((f) => {
    // Text search
    if (
      filters.search &&
      !f.name.toLowerCase().includes(filters.search.toLowerCase())
    ) {
      return false;
    }
    // Category filter
    if (
      filters.category !== "All" &&
      f.category.toLowerCase() !== filters.category.toLowerCase()
    ) {
      return false;
    }
    // Status filter
    if (filters.statuses.size > 0) {
      // Map "queued" to "pending" for filter purposes since they share a column
      const effectiveStatuses = new Set<FeatureStatus>(filters.statuses);
      if (effectiveStatuses.has("pending")) {
        effectiveStatuses.add("queued");
      }
      if (!effectiveStatuses.has(f.status)) {
        return false;
      }
    }
    return true;
  });
}

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
  const { data: providers = [], isLoading: poolLoading } = usePoolStatus();
  const { data: sessionData } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetchSession(sessionId),
    staleTime: 60_000,
  });

  // Shared WebSocket
  const {
    connectionStatus,
    activityLog,
    costHistory,
    toasts,
    reconnectCountdown,
    forceReconnect,
    removeToast,
  } = useWebSocket(sessionId);

  // Dark mode
  const [isDark, toggleDark] = useDarkMode();

  // View mode: kanban | graph
  const [viewMode, setViewMode] = useState<ViewMode>("kanban");

  // Feature detail drawer (desktop)
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(
    null,
  );
  const selectedFeature = useMemo(
    () => (features ?? []).find((f) => f.id === selectedFeatureId) ?? null,
    [features, selectedFeatureId],
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

  // Regression implicated feature IDs
  const [implicatedFeatureIds, setImplicatedFeatureIds] = useState<number[]>(
    [],
  );

  // Activity log panel
  const [logOpen, setLogOpen] = useState(false);

  // Shortcuts modal
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  // Command palette
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Commands panel (sidebar tab)
  const [commandsPanelOpen, setCommandsPanelOpen] = useState(false);

  // Active executions for the ExecutionDrawer
  const [activeExecutions, setActiveExecutions] = useState<Execution[]>([]);

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

  // FAB handlers
  const handleRefresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["features"] });
    void qc.invalidateQueries({ queryKey: ["pool-status"] });
  }, [qc]);

  const handleResetZoom = useCallback(() => {
    setScale(1);
  }, [setScale]);

  const summary = useSummary(features);
  const projectName = (sessionData as Record<string, unknown>)?.project_path as
    | string
    | undefined;

  // Apply filters
  const filteredFeatures = useMemo(
    () => applyFilters(features ?? [], filters),
    [features, filters],
  );

  // Group features into columns
  const columnFeatures = useMemo(() => {
    const map: Record<string, Feature[]> = {};
    for (const col of KANBAN_COLUMNS) {
      map[col.id] = filteredFeatures.filter((f) =>
        col.statuses.includes(f.status),
      );
    }
    return map;
  }, [filteredFeatures]);

  // Handle command WebSocket events (command_output / command_done)
  useEffect(() => {
    // We listen via a custom event dispatched from useWebSocket
    // Instead, poll activityLog for command events — handled below in useWebSocket extension
    // For now we attach a direct handler by monkey-patching via a ref approach.
    // The cleanest approach: intercept in useWebSocket hook — but to avoid changing hook,
    // we expose a global handler here that the ExecutionDrawer can reference.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__commandEventHandler = (event: Record<string, unknown>) => {
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
    };
    return () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (window as any).__commandEventHandler;
    };
  }, []);

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
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-slate-400 dark:text-slate-500 font-medium shrink-0">
              Providers:
            </span>
            <ProviderPoolStatus providers={providers} isLoading={poolLoading} />
          </div>
        </div>
      </header>

      {/* ── Regression health bar ────────────────────────────────────── */}
      <RegressionHealthBar
        onImplicatedUpdate={setImplicatedFeatureIds}
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
            <div className={isMobile ? "flex flex-col gap-4" : "flex gap-4 items-start h-full"} data-testid="kanban-columns">
              {KANBAN_COLUMNS.map((col, colIdx) => {
                const cards = columnFeatures[col.id] ?? [];
                // On mobile, only show the active column
                if (isMobile && colIdx !== mobileColumnIndex) return null;
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
                      <span className="text-xs font-bold bg-white/50 dark:bg-black/20 rounded-full px-2 py-0.5">
                        {cards.length}
                      </span>
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
                        : cards.map((feature) => (
                            <FeatureCard
                              key={feature.id}
                              feature={feature}
                              onClick={() => setSelectedFeatureId(feature.id)}
                              onLongPress={(f) => setLongPressFeature(f)}
                              implicatedFeatureIds={implicatedFeatureIds}
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
          </div>
        </main>
      ) : (
        <DependencyGraph
          features={filteredFeatures}
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
  const [input, setInput] = useState("");

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="rounded-2xl bg-white dark:bg-slate-800 shadow-xl p-8 w-full max-w-md border-t-4 border-orange-500">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-2">
          ⚒ claw-forge
        </h1>
        <p className="text-slate-500 dark:text-slate-400 text-sm mb-6">
          Enter a session ID to open the Kanban board.
        </p>
        <input
          type="text"
          className="w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-sm font-mono
            bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-200
            focus:outline-none focus:ring-2 focus:ring-forge-500 mb-3
            placeholder:text-slate-400 dark:placeholder:text-slate-500"
          placeholder="Session UUID…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && input && onSelect(input.trim())}
        />
        <button
          type="button"
          className="w-full bg-forge-600 hover:bg-forge-700 text-white font-semibold py-2 rounded-lg transition-colors disabled:opacity-50"
          disabled={!input.trim()}
          onClick={() => onSelect(input.trim())}
        >
          Open Board
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
