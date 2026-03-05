/**
 * RegressionHealthBar — full-width strip above the Kanban board
 * showing the current regression test suite status.
 *
 * - Green when all tests pass
 * - Red when tests are failing
 * - Yellow pulsing when tests are running
 * - Gray when no test command detected
 *
 * Polls GET /regression/status every 10s; real-time updates come via
 * the shared WebSocket managed by useWebSocket (passed as props).
 */

import { useQuery } from "@tanstack/react-query";

interface RegressionStatus {
  run_count: number;
  has_test_command: boolean;
  last_result: {
    passed: boolean;
    total: number;
    failed: number;
    failed_tests: string[];
    duration_ms: number;
    run_number: number;
    implicated_feature_ids: number[];
    output: string;
  } | null;
}

interface RegressionHealthBarProps {
  /** Whether a regression suite is currently running (from shared WebSocket). */
  isRunning: boolean;
  /** The run number of the currently running suite. */
  runNumber: number;
}

// Use relative path — Vite proxy handles it in dev, same-origin in production
const BASE = "/api";

async function fetchRegressionStatus(): Promise<RegressionStatus> {
  const res = await fetch(`${BASE}/regression/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RegressionStatus>;
}

function secondsAgo(durationMs: number): string {
  const s = Math.round(durationMs / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

export function RegressionHealthBar({ isRunning, runNumber }: RegressionHealthBarProps) {
  const { data, isLoading } = useQuery<RegressionStatus>({
    queryKey: ["regression", "status"],
    queryFn: fetchRegressionStatus,
    refetchInterval: 10_000,
    retry: 1,
  });

  // Running state (driven by shared WebSocket in useWebSocket)
  if (isRunning) {
    return (
      <div className="w-full bg-yellow-100 dark:bg-yellow-900/40 border-b border-yellow-300 dark:border-yellow-700 px-4 py-1.5 text-xs font-medium text-yellow-800 dark:text-yellow-200 animate-pulse flex items-center gap-2">
        <span>🔄</span>
        <span>Running regression suite… (Run #{runNumber})</span>
      </div>
    );
  }

  // Initial load — avoid flashing "No test command detected" before data arrives
  if (isLoading) {
    return (
      <div className="w-full bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-1.5 text-xs text-slate-400 dark:text-slate-500 flex items-center gap-2 animate-pulse">
        <span>⚫</span>
        <span>Checking regression status…</span>
      </div>
    );
  }

  // No test command configured
  if (!data || !data.has_test_command) {
    return (
      <div className="w-full bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-1.5 text-xs text-slate-400 dark:text-slate-500 flex items-center gap-2">
        <span>⚫</span>
        <span>No test command detected</span>
      </div>
    );
  }

  // Test command configured but not yet run
  if (data.run_count === 0) {
    return (
      <div className="w-full bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-1.5 text-xs text-slate-400 dark:text-slate-500 flex items-center gap-2">
        <span>⚫</span>
        <span>Regression suite ready — waiting for first run</span>
      </div>
    );
  }

  const result = data.last_result;
  if (!result) {
    return null;
  }

  const agoText = secondsAgo(result.duration_ms);

  if (result.passed) {
    return (
      <div className="w-full bg-emerald-100 dark:bg-emerald-900/40 border-b border-emerald-300 dark:border-emerald-700 px-4 py-1.5 text-xs font-medium text-emerald-800 dark:text-emerald-200 flex items-center gap-2">
        <span>🟢</span>
        <span>
          Regression Suite — {result.total} passing | Last run:{" "}
          {agoText} ago | {data.run_count} run
          {data.run_count !== 1 ? "s" : ""}
        </span>
      </div>
    );
  }

  const firstFailed = result.failed_tests[0] ?? "unknown";
  const extra =
    result.failed_tests.length > 1
      ? ` +${result.failed_tests.length - 1} more`
      : "";

  return (
    <div className="w-full bg-red-100 dark:bg-red-900/40 border-b border-red-300 dark:border-red-700 px-4 py-1.5 text-xs font-medium text-red-800 dark:text-red-200 flex items-center gap-2">
      <span>🔴</span>
      <span>
        {result.failed} regression{result.failed !== 1 ? "s" : ""} —{" "}
        {firstFailed}
        {extra} | Run #{result.run_number}
      </span>
    </div>
  );
}
