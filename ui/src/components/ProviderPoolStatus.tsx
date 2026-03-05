/**
 * ProviderPoolStatus — provider list with runtime enable/disable toggles.
 *
 * Each row shows: toggle | name + type | health badge | model | RPM | cost | latency | [Persist]
 *
 * Toggling calls PATCH /pool/providers/{name} immediately (runtime only — "soft" toggle).
 * "Persist" calls POST /pool/providers/{name}/persist to write claw-forge.yaml ("hard" toggle).
 */

import { useState, useCallback, useEffect } from "react";
import type { ProviderStatus } from "../types";
import { toggleProvider, persistProvider } from "../api";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastKind = "success" | "error";

interface ProviderRowProps {
  provider: ProviderStatus;
  pendingPersist: boolean;
  toggling: boolean;
  onToggle: (name: string, enabled: boolean) => void;
  onPersist: (name: string) => void;
  onToast: (msg: string, kind: ToastKind) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function healthDot(health: ProviderStatus["health"], enabled: boolean): string {
  if (!enabled) return "\u23F8";
  switch (health) {
    case "healthy": return "\uD83D\uDFE2";
    case "degraded": return "\uD83D\uDFE1";
    case "unhealthy": return "\uD83D\uDD34";
    default: return "\u26AA";
  }
}

function healthLabel(health: ProviderStatus["health"], enabled: boolean): string {
  if (!enabled) return "OFF";
  switch (health) {
    case "healthy": return "OK";
    case "degraded": return "SLOW";
    case "unhealthy": return "DOWN";
    default: return "—";
  }
}

const TYPE_COLORS: Record<string, string> = {
  anthropic: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
  bedrock: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  azure: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  vertex: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  openai_compat: "bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-300",
  anthropic_compat: "bg-orange-50 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400",
  anthropic_oauth: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  ollama: "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300",
};

// ── ProviderRow ───────────────────────────────────────────────────────────────

function ProviderRow({
  provider,
  pendingPersist,
  toggling,
  onToggle,
  onPersist,
  onToast,
}: ProviderRowProps) {
  const [saving, setSaving] = useState(false);

  const handleToggle = useCallback(async () => {
    if (toggling) return;
    const newEnabled = !provider.enabled;
    onToggle(provider.name, newEnabled);
    try {
      await toggleProvider(provider.name, newEnabled);
      onToast(
        `${provider.name} ${newEnabled ? "enabled" : "disabled"} (runtime)`,
        "success",
      );
    } catch (err) {
      onToggle(provider.name, provider.enabled);
      onToast(`Toggle failed: ${String(err)}`, "error");
    }
  }, [provider.name, provider.enabled, toggling, onToggle, onToast]);

  const handlePersist = useCallback(async () => {
    setSaving(true);
    try {
      await persistProvider(provider.name, provider.enabled);
      onPersist(provider.name);
      onToast(`${provider.name} persisted to config`, "success");
    } catch (err) {
      onToast(`Persist failed: ${String(err)}`, "error");
    } finally {
      setSaving(false);
    }
  }, [provider.name, provider.enabled, onPersist, onToast]);

  const typeClass = TYPE_COLORS[provider.type] ?? "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400";
  const rpmPct = provider.max_rpm > 0
    ? Math.min(100, (provider.rpm / provider.max_rpm) * 100)
    : 0;

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700
        bg-white dark:bg-slate-800 text-xs transition-all duration-200
        ${provider.enabled ? "" : "opacity-60"}`}
    >
      {/* Toggle switch (soft / runtime) */}
      <button
        type="button"
        role="switch"
        aria-checked={provider.enabled}
        aria-label={`${provider.enabled ? "Disable" : "Enable"} ${provider.name} (runtime)`}
        disabled={toggling}
        onClick={handleToggle}
        title="Runtime toggle (soft)"
        className={`relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full
          border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-forge-400
          ${provider.enabled ? "bg-emerald-500" : "bg-slate-400 dark:bg-slate-600"}
          ${toggling ? "opacity-60 cursor-not-allowed" : ""}`}
      >
        <span
          className={`pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow
            transition duration-200 ease-in-out
            ${provider.enabled ? "translate-x-3" : "translate-x-0"}`}
        />
      </button>

      {/* Name + type badge */}
      <div className="flex items-center gap-1.5 min-w-0 shrink">
        <span className="font-semibold text-slate-800 dark:text-slate-100 truncate max-w-[120px]">
          {provider.name}
        </span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium leading-none whitespace-nowrap ${typeClass}`}>
          {provider.type.replace(/_/g, "-")}
        </span>
      </div>

      {/* Health dot + label */}
      <span className="flex items-center gap-0.5 text-slate-600 dark:text-slate-300 shrink-0" title={`Circuit: ${provider.circuit_state}`}>
        <span className="text-sm leading-none">{healthDot(provider.health, provider.enabled)}</span>
        <span className="font-medium">{healthLabel(provider.health, provider.enabled)}</span>
      </span>

      {/* Model */}
      {provider.model && provider.enabled && (
        <span className="text-slate-400 dark:text-slate-500 truncate max-w-[100px]" title={provider.model}>
          {provider.model}
        </span>
      )}

      {/* RPM gauge */}
      {provider.enabled && (
        <span className="flex items-center gap-1 shrink-0" title={`${provider.rpm}/${provider.max_rpm} requests/min`}>
          <span className="relative w-8 h-1.5 rounded-full bg-slate-200 dark:bg-slate-600 overflow-hidden">
            <span
              className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500
                ${rpmPct > 80 ? "bg-red-400" : rpmPct > 50 ? "bg-amber-400" : "bg-emerald-400"}`}
              style={{ width: `${rpmPct}%` }}
            />
          </span>
          <span className="text-slate-500 dark:text-slate-400 tabular-nums">
            {provider.rpm}/{provider.max_rpm === 0 ? "\u221E" : provider.max_rpm}
          </span>
        </span>
      )}

      {/* Cost */}
      <span className="text-slate-500 dark:text-slate-400 shrink-0 tabular-nums">
        {provider.enabled ? `$${provider.total_cost_usd.toFixed(2)}` : "—"}
      </span>

      {/* Latency */}
      {provider.enabled && provider.avg_latency_ms > 0 && provider.avg_latency_ms < Infinity && (
        <span className="text-slate-400 dark:text-slate-500 shrink-0 tabular-nums">
          {provider.avg_latency_ms < 1000
            ? `${Math.round(provider.avg_latency_ms)}ms`
            : `${(provider.avg_latency_ms / 1000).toFixed(1)}s`}
        </span>
      )}

      {/* Persist button (hard toggle — appears after unsaved runtime change) */}
      {pendingPersist && (
        <button
          type="button"
          disabled={saving}
          onClick={handlePersist}
          title="Save to claw-forge.yaml (persist)"
          className={`ml-auto px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wide
            border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-300
            hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-colors
            ${saving ? "opacity-60 cursor-not-allowed" : ""}`}
        >
          {saving ? "Saving\u2026" : "Persist"}
        </button>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface ProviderPoolStatusProps {
  providers: ProviderStatus[];
  isLoading?: boolean;
  onProvidersChange?: (providers: ProviderStatus[]) => void;
  /** Bubble toast events to the parent (global toast system) */
  onToast?: (message: string, type: "success" | "error" | "info" | "warning") => void;
}

export function ProviderPoolStatus({
  providers: initialProviders,
  isLoading = false,
  onProvidersChange,
  onToast,
}: ProviderPoolStatusProps) {
  const [providers, setProviders] = useState<ProviderStatus[]>(initialProviders);
  const [pendingPersist, setPendingPersist] = useState<Set<string>>(new Set());
  const [toggling, setToggling] = useState<Set<string>>(new Set());

  // Keep local state in sync with prop updates (e.g. WebSocket refreshes)
  // Only sync when not mid-toggle to avoid flicker
  useEffect(() => {
    if (toggling.size === 0) {
      setProviders(initialProviders);
    }
  }, [initialProviders, toggling]);

  const handleToast = useCallback((message: string, kind: ToastKind) => {
    onToast?.(message, kind === "success" ? "success" : "error");
  }, [onToast]);

  const handleToggle = useCallback((name: string, enabled: boolean) => {
    setToggling((prev) => {
      const next = new Set(prev);
      next.add(name);
      return next;
    });
    setProviders((prev) =>
      prev.map((p) => (p.name === name ? { ...p, enabled } : p)),
    );
    setPendingPersist((prev) => new Set([...prev, name]));
    setTimeout(() => {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }, 500);
    onProvidersChange?.(providers.map((p) => (p.name === name ? { ...p, enabled } : p)));
  }, [providers, onProvidersChange]);

  const handlePersistSuccess = useCallback((name: string) => {
    setPendingPersist((prev) => {
      const next = new Set(prev);
      next.delete(name);
      return next;
    });
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-9 rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (providers.length === 0) {
    return (
      <span className="text-xs text-slate-400 dark:text-slate-500 italic">
        No providers configured
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {providers.map((p) => (
        <ProviderRow
          key={p.name}
          provider={p}
          pendingPersist={pendingPersist.has(p.name)}
          toggling={toggling.has(p.name)}
          onToggle={handleToggle}
          onPersist={handlePersistSuccess}
          onToast={handleToast}
        />
      ))}
    </div>
  );
}
