/**
 * ProviderPoolStatus — provider list with runtime enable/disable toggles.
 *
 * Each row shows: toggle | name | health badge | RPM | cost | [Save to config]
 *
 * Toggling calls PATCH /pool/providers/{name} immediately (runtime only).
 * "Save to config" calls POST /pool/providers/{name}/persist to write claw-forge.yaml.
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
  onSave: (name: string) => void;
  onSaveSuccess: (name: string) => void;
  onToast: (msg: string, kind: ToastKind) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function healthDot(health: ProviderStatus["health"], enabled: boolean): string {
  if (!enabled) return "⏸";
  switch (health) {
    case "healthy": return "🟢";
    case "degraded": return "🟡";
    case "unhealthy": return "🔴";
    default: return "⚪";
  }
}

function healthLabel(health: ProviderStatus["health"], enabled: boolean): string {
  if (!enabled) return "DISABLED";
  switch (health) {
    case "healthy": return "OK";
    case "degraded": return "SLOW";
    case "unhealthy": return "DOWN";
    default: return "UNKNOWN";
  }
}

function rpmDisplay(provider: ProviderStatus): string {
  if (!provider.enabled) return "—";
  const max = provider.max_rpm === 0 ? "∞" : String(provider.max_rpm);
  return `${provider.rpm}/${max} RPM`;
}

// ── ProviderRow ───────────────────────────────────────────────────────────────

function ProviderRow({
  provider,
  pendingPersist,
  toggling,
  onToggle,
  onSave,
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
        `${provider.name} ${newEnabled ? "enabled" : "disabled"} (runtime only)`,
        "success",
      );
    } catch (err) {
      // Revert on failure
      onToggle(provider.name, provider.enabled);
      onToast(`Failed to toggle ${provider.name}: ${String(err)}`, "error");
    }
  }, [provider.name, provider.enabled, toggling, onToggle, onToast]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await persistProvider(provider.name, provider.enabled);
      onSave(provider.name);
      onToast(`Saved to claw-forge.yaml`, "success");
    } catch (err) {
      onToast(`Failed to persist ${provider.name}: ${String(err)}`, "error");
    } finally {
      setSaving(false);
    }
  }, [provider.name, provider.enabled, onSave, onToast]);

  const rowOpacity = provider.enabled ? "" : "opacity-50";

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700
        bg-white dark:bg-slate-800 text-xs ${rowOpacity} transition-opacity`}
    >
      {/* Toggle switch */}
      <button
        type="button"
        role="switch"
        aria-checked={provider.enabled}
        aria-label={`${provider.enabled ? "Disable" : "Enable"} ${provider.name}`}
        disabled={toggling}
        onClick={handleToggle}
        className={`relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full
          border-2 border-transparent transition-colors duration-200 focus:outline-none
          ${provider.enabled ? "bg-emerald-500" : "bg-slate-400"}
          ${toggling ? "opacity-60 cursor-not-allowed" : ""}`}
      >
        <span
          className={`pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow
            transition duration-200 ease-in-out
            ${provider.enabled ? "translate-x-3" : "translate-x-0"}`}
        />
      </button>

      {/* Name */}
      <span className="font-medium text-slate-800 dark:text-slate-100 truncate min-w-[100px] max-w-[140px]">
        {provider.name}
      </span>

      {/* Health badge */}
      <span className="flex items-center gap-1 text-slate-600 dark:text-slate-300 min-w-[80px]">
        <span>{healthDot(provider.health, provider.enabled)}</span>
        <span>{healthLabel(provider.health, provider.enabled)}</span>
      </span>

      {/* RPM */}
      <span className="text-slate-500 dark:text-slate-400 min-w-[80px]">
        {rpmDisplay(provider)}
      </span>

      {/* Cost */}
      <span className="text-slate-500 dark:text-slate-400 min-w-[50px]">
        {provider.enabled ? `$${provider.total_cost_usd.toFixed(2)}` : "—"}
      </span>

      {/* Save to config button (appears after unsaved runtime change) */}
      {pendingPersist && (
        <button
          type="button"
          disabled={saving}
          onClick={handleSave}
          className={`ml-auto px-2 py-0.5 rounded border border-slate-300 dark:border-slate-600
            text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700
            transition-colors text-xs ${saving ? "opacity-60 cursor-not-allowed" : ""}`}
        >
          {saving ? "Saving…" : "Save"}
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
    // Remove toggling lock after short delay (actual API call handles real state)
    setTimeout(() => {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }, 500);
    onProvidersChange?.(providers.map((p) => (p.name === name ? { ...p, enabled } : p)));
  }, [providers, onProvidersChange]);

  const handleSaveSuccess = useCallback((name: string) => {
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
      <span className="text-xs text-slate-400 dark:text-slate-500 italic">No providers</span>
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
          onSave={handleSaveSuccess}
          onSaveSuccess={handleSaveSuccess}
          onToast={handleToast}
        />
      ))}
    </div>
  );
}
