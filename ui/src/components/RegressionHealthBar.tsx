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

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

interface ImplicatedFeature {
  id: string;
  name: string;
}

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
    implicated_feature_ids: string[];
    implicated_features?: ImplicatedFeature[];
    trigger_features?: ImplicatedFeature[];
    output: string;
  } | null;
}

interface RegressionHealthBarProps {
  /** Whether a regression suite is currently running (from shared WebSocket). */
  isRunning: boolean;
  /** When true, disables background polling (e.g. all tasks complete). */
  paused?: boolean;
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

export function RegressionHealthBar({ isRunning, paused = false }: RegressionHealthBarProps) {
  const { data, isLoading } = useQuery<RegressionStatus>({
    queryKey: ["regression", "status"],
    queryFn: fetchRegressionStatus,
    refetchInterval: paused ? false : 10_000,
    retry: 1,
  });

  // Running state (driven by shared WebSocket in useWebSocket)
  if (isRunning) {
    return (
      <div className="w-full bg-yellow-100 dark:bg-yellow-900/40 border-b border-yellow-300 dark:border-yellow-700 px-4 py-1.5 text-xs font-medium text-yellow-800 dark:text-yellow-200 animate-pulse flex items-center gap-2">
        <span>🔄</span>
        <span>Running regression suite…</span>
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

  const triggerFeatures = result.trigger_features ?? [];
  const implicatedFeatures = result.implicated_features ?? [];
  const hasDetails =
    result.failed_tests.length > 1 ||
    triggerFeatures.length > 0 ||
    implicatedFeatures.length > 0;

  // Test command errored (non-zero exit) but no individual test failures parsed —
  // e.g. build failure, missing dependency, import error before tests ran.
  if (result.failed === 0 && result.failed_tests.length === 0) {
    const hint = result.output
      ? result.output.split("\n").filter(Boolean).slice(-1)[0]?.slice(0, 120) ?? ""
      : "";
    const warnHasDetails = triggerFeatures.length > 0 || implicatedFeatures.length > 0;
    return (
      <HealthBarAccordion
        color="amber"
        icon={<span className="text-amber-500">&#x26A0;</span>}
        summary={
          <>
            Test command failed (no test results)
            {hint ? <span className="ml-1 font-normal opacity-75">— {hint}</span> : null}
          </>
        }
        hasDetails={warnHasDetails}
      >
        <FeatureSection label="Triggered after" features={triggerFeatures} color="amber" />
        <FeatureSection label="Implicated features" features={implicatedFeatures} color="amber" />
      </HealthBarAccordion>
    );
  }

  const firstFailed = result.failed_tests[0] ?? "unknown";

  return (
    <HealthBarAccordion
      color="red"
      icon={<span>🔴</span>}
      summary={
        <>
          {result.failed} regression{result.failed !== 1 ? "s" : ""} — {firstFailed}
          {result.failed_tests.length > 1 && (
            <span className="ml-1 font-normal opacity-75">
              +{result.failed_tests.length - 1} more
            </span>
          )}
        </>
      }
      hasDetails={hasDetails}
    >
      {result.failed_tests.length > 1 && (
        <div className="mb-1.5">
          <span className="font-semibold">Failed tests:</span>
          <ul className="list-disc list-inside mt-0.5 space-y-0.5">
            {result.failed_tests.map((t) => (
              <li key={t} className="break-all">{t}</li>
            ))}
          </ul>
        </div>
      )}
      <FeatureSection label="Triggered after" features={triggerFeatures} color="red" />
      <FeatureSection label="Implicated features" features={implicatedFeatures} color="red" />
    </HealthBarAccordion>
  );
}

/* ── Shared sub-components ─────────────────────────────────────────────────── */

const COLOR_MAP = {
  red: {
    bar: "bg-red-100 dark:bg-red-900/40 border-red-300 dark:border-red-700",
    text: "text-red-800 dark:text-red-200",
    detail: "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800",
    bullet: "text-red-400 dark:text-red-500",
  },
  amber: {
    bar: "bg-amber-100 dark:bg-amber-900/40 border-amber-300 dark:border-amber-700",
    text: "text-amber-800 dark:text-amber-200",
    detail: "bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800",
    bullet: "text-amber-400 dark:text-amber-500",
  },
} as const;

function HealthBarAccordion({
  color,
  icon,
  summary,
  hasDetails,
  children,
}: {
  color: keyof typeof COLOR_MAP;
  icon: React.ReactNode;
  summary: React.ReactNode;
  hasDetails: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const c = COLOR_MAP[color];

  return (
    <div className={`w-full ${c.bar} border-b`}>
      <button
        type="button"
        className={`w-full px-4 py-1.5 text-xs font-medium ${c.text} flex items-center gap-2 text-left`}
        onClick={() => hasDetails && setOpen((o) => !o)}
        aria-expanded={open}
      >
        {icon}
        <span className="truncate min-w-0">{summary}</span>
        {hasDetails && (
          <ChevronRight
            size={12}
            className={`shrink-0 ml-auto transition-transform duration-200 ${open ? "rotate-90" : ""}`}
          />
        )}
      </button>
      {open && hasDetails && (
        <div className={`px-6 pb-2 pt-0.5 text-xs ${c.text} ${c.detail} border-t`}>
          {children}
        </div>
      )}
    </div>
  );
}

function FeatureSection({
  label,
  features,
  color,
}: {
  label: string;
  features: ImplicatedFeature[];
  color: keyof typeof COLOR_MAP;
}) {
  if (features.length === 0) return null;
  const c = COLOR_MAP[color];
  return (
    <div className="mb-1.5 last:mb-0">
      <span className="font-semibold">{label}:</span>
      <ul className={`list-disc list-inside mt-0.5 space-y-0.5 ${c.bullet}`}>
        {features.map((f) => (
          <li key={f.id} className="truncate max-w-full" title={f.name}>
            <span className={c.text}>
              {f.name.length > 80 ? f.name.slice(0, 80) + "…" : f.name}{" "}
              <span className="opacity-50 font-mono text-[10px]">({f.id.slice(0, 8)})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
