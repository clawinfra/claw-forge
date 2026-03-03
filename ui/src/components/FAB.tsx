/**
 * FAB — Floating Action Button for mobile.
 * Shows in bottom-right on mobile (<640px).
 * Expands to reveal quick actions: add task, refresh, zoom reset.
 */
import { useState } from "react";
import { Plus, RefreshCw, ZoomIn, X } from "lucide-react";
import { triggerHaptic } from "../utils/haptic";

interface FABProps {
  onRefresh: () => void;
  onResetZoom: () => void;
}

export function FAB({ onRefresh, onResetZoom }: FABProps) {
  const [expanded, setExpanded] = useState(false);

  const toggle = () => {
    triggerHaptic(30);
    setExpanded((v) => !v);
  };

  const handleAction = (action: () => void) => {
    triggerHaptic(50);
    action();
    setExpanded(false);
  };

  return (
    <div className="fixed bottom-6 right-6 z-[75] flex flex-col items-end gap-2 sm:hidden" data-testid="fab-container">
      {/* Expanded actions */}
      {expanded && (
        <div className="flex flex-col gap-2 animate-fab-expand">
          <button
            type="button"
            onClick={() => handleAction(onRefresh)}
            className="flex items-center gap-2 bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-200
              rounded-full pl-3 pr-4 py-2 shadow-lg border border-slate-200 dark:border-slate-600
              active:scale-95 transition-transform"
            data-testid="fab-refresh"
          >
            <RefreshCw size={16} />
            <span className="text-sm font-medium">Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction(onResetZoom)}
            className="flex items-center gap-2 bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-200
              rounded-full pl-3 pr-4 py-2 shadow-lg border border-slate-200 dark:border-slate-600
              active:scale-95 transition-transform"
            data-testid="fab-zoom-reset"
          >
            <ZoomIn size={16} />
            <span className="text-sm font-medium">Reset Zoom</span>
          </button>
        </div>
      )}

      {/* Main FAB button */}
      <button
        type="button"
        onClick={toggle}
        className={`w-14 h-14 rounded-full shadow-xl flex items-center justify-center
          transition-all duration-200 active:scale-90
          ${
            expanded
              ? "bg-slate-600 dark:bg-slate-500 text-white rotate-45"
              : "bg-forge-600 hover:bg-forge-700 text-white"
          }`}
        data-testid="fab-main"
        aria-label="Quick actions"
      >
        {expanded ? <X size={24} /> : <Plus size={24} />}
      </button>
    </div>
  );
}
