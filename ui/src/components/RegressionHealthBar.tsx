/**
 * RegressionHealthBar — full-width strip above the Kanban board
 * showing the current regression test suite status.
 *
 * - Green when all tests pass
 * - Red when tests are failing
 * - Yellow pulsing when tests are running
 * - Gray when no test command detected
 *
 * Polls GET /regression/status every 10s and listens to WebSocket events.
 */

import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

interface RegressionStatus {
  run_count: number;
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
  /** Called when a regression_result event arrives with implicated IDs */
  onImplicatedUpdate?: (ids: number[]) => void;
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

export function RegressionHealthBar({
  onImplicatedUpdate,
}: RegressionHealthBarProps) {
  const [isRunning, setIsRunning] = useState(false);
  const [runningNumber, setRunningNumber] = useState(0);

  const { data, refetch } = useQuery<RegressionStatus>({
    queryKey: ["regression", "status"],
    queryFn: fetchRegressionStatus,
    refetchInterval: 10_000,
    retry: 1,
  });

  // Listen for WebSocket regression events
  const handleWsMessage = useCallback(
    (event: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(event.data) as Record<string, unknown>;
        if (msg.type === "regression_started") {
          setIsRunning(true);
          setRunningNumber(msg.run_number as number);
        } else if (msg.type === "regression_result") {
          setIsRunning(false);
          void refetch();
          if (
            onImplicatedUpdate &&
            Array.isArray(msg.implicated_feature_ids)
          ) {
            onImplicatedUpdate(
              msg.implicated_feature_ids as number[],
            );
          }
        }
      } catch {
        // ignore non-JSON
      }
    },
    [refetch, onImplicatedUpdate],
  );

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}://${host}/ws`);
    ws.onmessage = handleWsMessage;
    return () => {
      ws.close();
    };
  }, [handleWsMessage]);

  // Running state
  if (isRunning) {
    return (
      <div className="w-full bg-yellow-100 dark:bg-yellow-900/40 border-b border-yellow-300 dark:border-yellow-700 px-4 py-1.5 text-xs font-medium text-yellow-800 dark:text-yellow-200 animate-pulse flex items-center gap-2">
        <span>🔄</span>
        <span>Running regression suite… (Run #{runningNumber})</span>
      </div>
    );
  }

  // Never run
  if (!data || data.run_count === 0) {
    return (
      <div className="w-full bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-1.5 text-xs text-slate-400 dark:text-slate-500 flex items-center gap-2">
        <span>⚫</span>
        <span>No test command detected</span>
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
