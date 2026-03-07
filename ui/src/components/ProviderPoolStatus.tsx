/**
 * ProviderPoolStatus — provider list with model display and toggles.
 *
 * Each provider row shows: toggle, name, type badge, model, health, cost.
 * Toggle = soft (runtime). Persist = hard (writes claw-forge.yaml).
 * Model tier accordion: expandable checkboxes to enable/disable model tiers
 * per-provider; checked tiers form the ordered pool used for complexity routing
 * (low → first tier, high → last tier).
 */

import { useState, useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProviderStatus } from "../types";
import { toggleProvider, persistProvider, setProviderTiers } from "../api";
import { POOL_KEY } from "../hooks/usePoolStatus";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastKind = "success" | "error";

// ── Health badge ──────────────────────────────────────────────────────────────

const HEALTH_CONFIG: Record<string, {
  dot: string; bg: string; border: string; text: string; label: string; pulse: boolean;
}> = {
  healthy:   { dot: "bg-emerald-500", bg: "bg-emerald-50 dark:bg-emerald-950/40", border: "border-emerald-200 dark:border-emerald-800", text: "text-emerald-700 dark:text-emerald-300", label: "OK",   pulse: true  },
  degraded:  { dot: "bg-amber-400",   bg: "bg-amber-50 dark:bg-amber-950/30",     border: "border-amber-200 dark:border-amber-800",   text: "text-amber-700 dark:text-amber-400",   label: "SLOW", pulse: false },
  unhealthy: { dot: "bg-red-500",     bg: "bg-red-50 dark:bg-red-950/30",         border: "border-red-200 dark:border-red-800",       text: "text-red-700 dark:text-red-400",       label: "DOWN", pulse: false },
};

function HealthBadge({ health, enabled }: { health: ProviderStatus["health"]; enabled: boolean }) {
  if (!enabled) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold
        border bg-slate-100 border-slate-200 text-slate-400 dark:bg-slate-700/50 dark:border-slate-600 dark:text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-600 shrink-0" />
        OFF
      </span>
    );
  }
  const cfg = HEALTH_CONFIG[health] ?? {
    dot: "bg-slate-400", bg: "bg-slate-100 dark:bg-slate-700", border: "border-slate-200 dark:border-slate-600",
    text: "text-slate-500 dark:text-slate-400", label: "IDLE", pulse: false,
  };
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold border ${cfg.bg} ${cfg.border} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${cfg.dot} ${cfg.pulse ? "animate-pulse" : ""}`} />
      {cfg.label}
    </span>
  );
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

/** Strip ${VAR:-default} or ${VAR} to show a human-friendly model name. */
function displayModel(raw: string | undefined): string {
  if (!raw) return "";
  if (raw.startsWith("${") && raw.includes(":-")) {
    return raw.split(":-")[1].replace(/}$/, "");
  }
  if (raw.startsWith("${") && raw.endsWith("}")) {
    return raw.slice(2, -1);
  }
  return raw;
}

/**
 * Return "LOW", "MED", or "HIGH" based on position within activeTiers.
 * Returns "" when the alias is not active.
 */
function complexityLabel(alias: string, activeTiers: string[]): string {
  const idx = activeTiers.indexOf(alias);
  if (idx === -1) return "";
  if (activeTiers.length === 1) return "ALL";
  if (idx === 0) return "LOW";
  if (idx === activeTiers.length - 1) return "HIGH";
  return "MED";
}

const COMPLEXITY_COLORS: Record<string, string> = {
  LOW: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  MED: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  HIGH: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  ALL: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
};

// ── ProviderRow ───────────────────────────────────────────────────────────────

interface ProviderRowProps {
  provider: ProviderStatus;
  pendingPersist: boolean;
  toggling: boolean;
  onToggle: (name: string, enabled: boolean) => void;
  onToggleResult: (name: string, success: boolean, newEnabled: boolean) => void;
  onPersist: (name: string) => void;
  onToast: (msg: string, kind: ToastKind) => void;
  onTierToggle: (name: string, activeTiers: string[]) => void;
  onTierToggleResult: (name: string, success: boolean, activeTiers: string[]) => void;
}

function ProviderRow({
  provider,
  pendingPersist,
  toggling,
  onToggle,
  onToggleResult,
  onPersist,
  onToast,
  onTierToggle,
  onTierToggleResult,
}: ProviderRowProps) {
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [togglingTier, setTogglingTier] = useState(false);

  const modelMap = provider.model_map ?? {};
  const modelMapEntries = Object.entries(modelMap); // [alias, modelId]
  const activeTiers = provider.active_tiers ?? [];
  const hasModelMap = modelMapEntries.length > 0;

  const handleToggle = useCallback(async () => {
    if (toggling) return;
    const newEnabled = !provider.enabled;
    onToggle(provider.name, newEnabled);
    try {
      await toggleProvider(provider.name, newEnabled);
      onToggleResult(provider.name, true, newEnabled);
      onToast(
        `${provider.name} ${newEnabled ? "enabled" : "disabled"} (runtime)`,
        "success",
      );
    } catch (err) {
      onToggle(provider.name, provider.enabled);
      onToggleResult(provider.name, false, provider.enabled);
      onToast(`Toggle failed: ${String(err)}`, "error");
    }
  }, [provider.name, provider.enabled, toggling, onToggle, onToggleResult, onToast]);

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

  const handleTierCheck = useCallback(async (alias: string, checked: boolean) => {
    if (togglingTier) return;
    // Rebuild active list in model_map definition order so complexity routing
    // always follows the user's intended cheapest→most-capable hierarchy.
    const allAliases = Object.keys(modelMap);
    const newTiers = checked
      ? allAliases.filter((a) => activeTiers.includes(a) || a === alias)
      : activeTiers.filter((a) => a !== alias);
    setTogglingTier(true);
    onTierToggle(provider.name, newTiers);
    try {
      await setProviderTiers(provider.name, newTiers);
      onTierToggleResult(provider.name, true, newTiers);
      onToast(`${provider.name}: model tier pool updated`, "success");
    } catch (err) {
      onTierToggle(provider.name, activeTiers); // revert
      onTierToggleResult(provider.name, false, activeTiers);
      onToast(`Tier update failed: ${String(err)}`, "error");
    } finally {
      setTogglingTier(false);
    }
  }, [provider.name, activeTiers, modelMap, togglingTier, onTierToggle, onTierToggleResult, onToast]);

  const typeClass = TYPE_COLORS[provider.type] ?? "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400";
  const model = displayModel(provider.model);

  const rowBorder =
    !provider.enabled
      ? "border-slate-200 dark:border-slate-700"
      : provider.health === "unhealthy"
        ? "border-red-200 dark:border-red-800/60"
        : provider.health === "degraded"
          ? "border-amber-200 dark:border-amber-800/60"
          : "border-slate-200 dark:border-slate-700";

  return (
    <div
      className={`rounded-lg border bg-white dark:bg-slate-800 text-xs transition-all duration-200
        ${rowBorder} ${provider.enabled ? "" : "opacity-55"}`}
    >
      {/* ── Summary row ─────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2">
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
            border-2 border-transparent transition-colors duration-200 focus:outline-none
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

        {/* Model name (if set) */}
        {model && (
          <span
            className="font-mono text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[140px] shrink"
            title={provider.model}
          >
            {model}
          </span>
        )}

        {/* Health badge */}
        <HealthBadge health={provider.health} enabled={provider.enabled} />

        {/* Cost */}
        <span className="text-slate-500 dark:text-slate-400 shrink-0 tabular-nums">
          {provider.enabled && provider.total_cost_usd > 0 ? `$${provider.total_cost_usd.toFixed(2)}` : ""}
        </span>

        {/* Persist button (hard toggle) */}
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

        {/* Expand chevron — only when model_map has entries */}
        {hasModelMap && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={`${pendingPersist ? "" : "ml-auto"} p-0.5 text-slate-400 hover:text-slate-600
              dark:hover:text-slate-300 transition-colors`}
            aria-label={expanded ? "Collapse model tiers" : "Expand model tiers"}
            title={expanded ? "Hide model tiers" : "Show model tiers"}
          >
            <span className="text-xs">{expanded ? "\u25B2" : "\u25BC"}</span>
          </button>
        )}
      </div>

      {/* ── Model tier accordion ─────────────────────────────────── */}
      {hasModelMap && expanded && (
        <div className="border-t border-slate-100 dark:border-slate-700 px-3 py-2 flex flex-col gap-1.5">
          <div className="text-[10px] text-slate-400 dark:text-slate-500 font-medium uppercase tracking-wide mb-0.5">
            Model tiers — checked tiers form the active pool (low → high)
          </div>
          {modelMapEntries.map(([alias, modelId]) => {
            const isActive = activeTiers.includes(alias);
            const label = complexityLabel(alias, activeTiers);
            const labelColor = COMPLEXITY_COLORS[label] ?? "";
            return (
              <label
                key={alias}
                className="flex items-center gap-2 cursor-pointer group"
              >
                <input
                  type="checkbox"
                  checked={isActive}
                  disabled={togglingTier}
                  onChange={(e) => handleTierCheck(alias, e.target.checked)}
                  className="h-3 w-3 rounded border-slate-300 text-emerald-500 focus:ring-emerald-400
                    disabled:opacity-60 disabled:cursor-not-allowed"
                />
                {/* Complexity badge (only shown when active) */}
                {label && (
                  <span className={`px-1 py-0.5 rounded text-[9px] font-bold leading-none ${labelColor}`}>
                    {label}
                  </span>
                )}
                {!label && <span className="w-[26px]" />}
                <span className="font-semibold text-slate-700 dark:text-slate-200 text-[11px] min-w-[48px]">
                  {alias}
                </span>
                <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500 truncate">
                  {modelId}
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── ModelAliases section ──────────────────────────────────────────────────────

function ModelAliasesSection({ aliases }: { aliases: Record<string, string> }) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(aliases);
  if (entries.length === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors rounded-lg"
      >
        <span className="font-semibold text-slate-700 dark:text-slate-200">Model Aliases</span>
        <span className="text-slate-400 dark:text-slate-500">
          {entries.length} alias{entries.length !== 1 ? "es" : ""}
        </span>
        <span className="ml-auto text-slate-400">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>
      {expanded && (
        <div className="border-t border-slate-100 dark:border-slate-700 px-3 py-2 bg-slate-50/50 dark:bg-slate-800/50 rounded-b-lg">
          <div className="flex flex-wrap gap-1.5">
            {entries.map(([alias, resolved]) => (
              <span
                key={alias}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md
                  bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200"
              >
                <span className="font-semibold">{alias}</span>
                <span className="text-slate-400 dark:text-slate-500">{"\u2192"}</span>
                <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[160px]">
                  {resolved}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface ProviderPoolStatusProps {
  providers: ProviderStatus[];
  modelAliases?: Record<string, string>;
  isLoading?: boolean;
  onProvidersChange?: (providers: ProviderStatus[]) => void;
  onToast?: (message: string, type: "success" | "error" | "info" | "warning") => void;
}

export function ProviderPoolStatus({
  providers: initialProviders,
  modelAliases = {},
  isLoading = false,
  onProvidersChange,
  onToast,
}: ProviderPoolStatusProps) {
  const qc = useQueryClient();
  const [providers, setProviders] = useState<ProviderStatus[]>(initialProviders);
  const [pendingPersist, setPendingPersist] = useState<Set<string>>(new Set());
  const [toggling, setToggling] = useState<Set<string>>(new Set());

  useEffect(() => {
    // Merge: accept server updates for all providers except those with an
    // in-flight optimistic toggle — preserve local state only for those.
    setProviders((prev) => {
      const prevMap = new Map(prev.map((p) => [p.name, p]));
      return initialProviders.map((p) =>
        toggling.has(p.name) ? (prevMap.get(p.name) ?? p) : p,
      );
    });
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
    onProvidersChange?.(providers.map((p) => (p.name === name ? { ...p, enabled } : p)));
  }, [providers, onProvidersChange]);

  const handleToggleResult = useCallback(
    (name: string, _success: boolean, _newEnabled: boolean) => {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
      // Always refetch — on success this confirms, on failure this reverts.
      void qc.invalidateQueries({ queryKey: POOL_KEY });
    },
    [qc],
  );

  const handlePersistSuccess = useCallback((name: string) => {
    setPendingPersist((prev) => {
      const next = new Set(prev);
      next.delete(name);
      return next;
    });
  }, []);

  const handleTierToggle = useCallback((name: string, activeTiers: string[]) => {
    setProviders((prev) =>
      prev.map((p) => (p.name === name ? { ...p, active_tiers: activeTiers } : p)),
    );
  }, []);

  const handleTierToggleResult = useCallback(
    (_name: string, _success: boolean, _activeTiers: string[]) => {
      // Always refetch — on success this confirms, on failure this reverts.
      void qc.invalidateQueries({ queryKey: POOL_KEY });
    },
    [qc],
  );

  if (isLoading) {
    return (
      <div className="flex flex-col gap-1.5">
        {[1, 2].map((i) => (
          <div
            key={i}
            className="h-10 rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
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
    <div className="flex flex-col gap-1.5">
      {providers.map((p) => (
        <ProviderRow
          key={p.name}
          provider={p}
          pendingPersist={pendingPersist.has(p.name)}
          toggling={toggling.has(p.name)}
          onToggle={handleToggle}
          onToggleResult={handleToggleResult}
          onPersist={handlePersistSuccess}
          onToast={handleToast}
          onTierToggle={handleTierToggle}
          onTierToggleResult={handleTierToggleResult}
        />
      ))}
      <ModelAliasesSection aliases={modelAliases} />
    </div>
  );
}
