/**
 * ProviderPoolStatus — compact provider health indicator.
 *
 * Shows a coloured dot + name for each provider:
 *   🟢 healthy   🟡 degraded   🔴 unhealthy   ⚪ unknown
 *
 * Clicking a provider reveals a tooltip with RPM, latency, and circuit state.
 */

import { useState } from "react";
import type { ProviderStatus } from "../types";

interface ProviderDotProps {
  provider: ProviderStatus;
}

function healthColour(health: ProviderStatus["health"]): string {
  switch (health) {
    case "healthy":
      return "bg-emerald-500";
    case "degraded":
      return "bg-amber-400";
    case "unhealthy":
      return "bg-red-500";
    default:
      return "bg-slate-400";
  }
}

function circuitLabel(state: ProviderStatus["circuit_state"]): string {
  switch (state) {
    case "closed":
      return "✅ closed";
    case "open":
      return "🔴 open";
    case "half_open":
      return "🟡 half-open";
  }
}

function ProviderDot({ provider }: ProviderDotProps) {
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        onClick={() => setShowTip((v) => !v)}
        title={provider.name}
      >
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${healthColour(provider.health)} ${
            provider.health === "degraded" ? "animate-pulse" : ""
          }`}
        />
        <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate max-w-[80px]">
          {provider.name}
        </span>
      </button>

      {showTip && (
        <div className="absolute top-full left-0 mt-1 z-50 w-56 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg p-3 text-xs space-y-1">
          <div className="font-semibold text-slate-800 dark:text-slate-100 mb-1">{provider.name}</div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">Type</span>
            <span className="font-mono text-slate-700 dark:text-slate-300">{provider.type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">RPM</span>
            <span className="text-slate-700 dark:text-slate-300">
              {provider.rpm}/{provider.max_rpm}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">Latency</span>
            <span className="text-slate-700 dark:text-slate-300">{Math.round(provider.avg_latency_ms)}ms</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">Circuit</span>
            <span className="text-slate-700 dark:text-slate-300">{circuitLabel(provider.circuit_state)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">Cost</span>
            <span className="text-slate-700 dark:text-slate-300">${provider.total_cost_usd.toFixed(3)}</span>
          </div>
          <button
            type="button"
            className="absolute top-2 right-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            onClick={() => setShowTip(false)}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

interface ProviderPoolStatusProps {
  providers: ProviderStatus[];
  isLoading?: boolean;
}

export function ProviderPoolStatus({
  providers,
  isLoading = false,
}: ProviderPoolStatusProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-6 w-20 rounded-md bg-slate-200 dark:bg-slate-700 animate-pulse"
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
    <div className="flex flex-wrap items-center gap-1">
      {providers.map((p) => (
        <ProviderDot key={p.name} provider={p} />
      ))}
    </div>
  );
}
