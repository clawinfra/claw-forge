/**
 * claw-forge Kanban UI — main application component.
 *
 * Columns: Pending | In Progress | Passing | Failed | Blocked
 *
 * Header:
 *   - Project name
 *   - Provider pool status dots
 *   - Overall progress bar (X/Y passing)
 *   - Live agent count
 *   - Cost tracker ($X.XX total)
 *
 * Real-time updates via WebSocket (ws://localhost:8888/ws).
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { FeatureCard } from "./components/FeatureCard";
import { ProgressBar } from "./components/ProgressBar";
import { ProviderPoolStatus } from "./components/ProviderPoolStatus";
import { useFeatures } from "./hooks/useFeatures";
import { usePoolStatus } from "./hooks/usePoolStatus";
import { fetchSession } from "./api";
import { KANBAN_COLUMNS } from "./types";
import type { Feature } from "./types";

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

interface KanbanBoardProps {
  sessionId: string;
}

function KanbanBoard({ sessionId }: KanbanBoardProps) {
  const { data: features, isLoading: featuresLoading, error: featuresError } = useFeatures(sessionId);
  const { data: providers = [], isLoading: poolLoading } = usePoolStatus();
  const { data: sessionData } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetchSession(sessionId),
    staleTime: 60_000,
  });

  const summary = useSummary(features);
  const projectName = (sessionData as Record<string, unknown>)?.project_path as string | undefined;

  // Group features into columns
  const columnFeatures = useMemo(() => {
    const map: Record<string, Feature[]> = {};
    for (const col of KANBAN_COLUMNS) {
      map[col.id] = (features ?? []).filter((f) =>
        col.statuses.includes(f.status),
      );
    }
    return map;
  }, [features]);

  return (
    <div className="flex flex-col h-screen bg-slate-50">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 shadow-sm">
        <div className="max-w-screen-2xl mx-auto">
          {/* Row 1: title + live stats */}
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <span className="text-xl font-bold text-forge-700">⚒ claw-forge</span>
              {projectName && (
                <span className="text-sm text-slate-500 font-mono truncate max-w-xs">
                  {projectName}
                </span>
              )}
            </div>

            <div className="flex items-center gap-6 text-sm">
              {/* Active agents */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${summary.running > 0 ? "bg-blue-500 animate-pulse" : "bg-slate-300"}`}
                />
                <span className="text-slate-600 font-medium">
                  {summary.running} agent{summary.running !== 1 ? "s" : ""} live
                </span>
              </div>

              {/* Cost */}
              <div className="font-mono text-slate-700">
                <span className="text-slate-400 font-sans text-xs mr-1">total</span>$
                {summary.totalCost.toFixed(2)}
              </div>
            </div>
          </div>

          {/* Row 2: progress bar */}
          <div className="mt-2">
            <ProgressBar passing={summary.passing} total={summary.total} />
          </div>

          {/* Row 3: provider pool */}
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-slate-400 font-medium shrink-0">Providers:</span>
            <ProviderPoolStatus providers={providers} isLoading={poolLoading} />
          </div>
        </div>
      </header>

      {/* ── Kanban columns ──────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-x-auto px-4 py-4">
        <div className="max-w-screen-2xl mx-auto">
          {featuresError && (
            <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              ⚠️ Failed to load features — is the state service running on port 8888?
            </div>
          )}

          <div className="flex gap-4 items-start h-full">
            {KANBAN_COLUMNS.map((col) => {
              const cards = columnFeatures[col.id] ?? [];
              return (
                <div
                  key={col.id}
                  className={`flex flex-col rounded-xl border ${col.colorClass} min-w-[240px] w-64 flex-shrink-0`}
                >
                  {/* Column header */}
                  <div
                    className={`flex items-center justify-between px-3 py-2 rounded-t-xl ${col.headerClass}`}
                  >
                    <span className="text-sm font-semibold">{col.label}</span>
                    <span className="text-xs font-bold bg-white/50 rounded-full px-2 py-0.5">
                      {cards.length}
                    </span>
                  </div>

                  {/* Cards */}
                  <div className="flex flex-col gap-2 p-2 overflow-y-auto max-h-[calc(100vh-180px)]">
                    {featuresLoading
                      ? Array.from({ length: 3 }, (_, i) => (
                          <div
                            key={i}
                            className="h-20 rounded-lg bg-white/60 animate-pulse"
                          />
                        ))
                      : cards.map((feature) => (
                          <FeatureCard key={feature.id} feature={feature} />
                        ))}
                    {!featuresLoading && cards.length === 0 && (
                      <p className="px-2 py-4 text-center text-xs text-slate-400 italic">
                        Nothing here
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}

// ── Session selector (shown when no session in URL) ───────────────────────────

function SessionSelector({
  onSelect,
}: {
  onSelect: (id: string) => void;
}) {
  const [input, setInput] = useState("");

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <div className="rounded-2xl bg-white shadow-xl p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-slate-800 mb-2">⚒ claw-forge</h1>
        <p className="text-slate-500 text-sm mb-6">
          Enter a session ID to open the Kanban board.
        </p>
        <input
          type="text"
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-forge-500 mb-3"
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
  const urlSession = params.get("session") ?? window.location.hash.replace("#", "");

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
