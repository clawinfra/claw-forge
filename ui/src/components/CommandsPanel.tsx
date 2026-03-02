/**
 * CommandsPanel — sidebar panel showing all 7 commands as cards.
 *
 * Sits alongside the ActivityLogPanel. Each card has an icon, label,
 * description and a "Run" button that fires POST /commands/execute.
 */

import {
  Activity,
  Bug,
  CheckCircle,
  FileText,
  GitPullRequest,
  Plus,
  Save,
  X,
} from "lucide-react";
import type { Command } from "../types";

// ── Icon map ──────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ElementType> = {
  FileText,
  Plus,
  CheckCircle,
  Save,
  GitPullRequest,
  Activity,
  Bug,
};

// ── Category styling ──────────────────────────────────────────────────────────

const CATEGORY_COLOR: Record<string, string> = {
  setup:
    "bg-blue-50 border-blue-200 dark:bg-blue-950/40 dark:border-blue-800",
  build:
    "bg-purple-50 border-purple-200 dark:bg-purple-950/40 dark:border-purple-800",
  quality:
    "bg-green-50 border-green-200 dark:bg-green-950/40 dark:border-green-800",
  save:
    "bg-teal-50 border-teal-200 dark:bg-teal-950/40 dark:border-teal-800",
  monitoring:
    "bg-yellow-50 border-yellow-200 dark:bg-yellow-950/40 dark:border-yellow-800",
  fix: "bg-red-50 border-red-200 dark:bg-red-950/40 dark:border-red-800",
};

const CATEGORY_ICON_COLOR: Record<string, string> = {
  setup: "text-blue-500",
  build: "text-purple-500",
  quality: "text-green-500",
  save: "text-teal-500",
  monitoring: "text-yellow-500",
  fix: "text-red-500",
};

const CATEGORY_BTN: Record<string, string> = {
  setup: "bg-blue-600 hover:bg-blue-700",
  build: "bg-purple-600 hover:bg-purple-700",
  quality: "bg-green-600 hover:bg-green-700",
  save: "bg-teal-600 hover:bg-teal-700",
  monitoring: "bg-yellow-500 hover:bg-yellow-600",
  fix: "bg-red-600 hover:bg-red-700",
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface CommandsPanelProps {
  isOpen: boolean;
  commands: Command[];
  onToggle: () => void;
  onExecute: (command: Command) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CommandsPanel({
  isOpen,
  commands,
  onToggle,
  onExecute,
}: CommandsPanelProps) {
  if (!isOpen) return null;

  return (
    <aside
      className="fixed right-0 top-0 h-full w-80 bg-white dark:bg-slate-800
        border-l border-slate-200 dark:border-slate-700 shadow-xl z-30
        flex flex-col transition-transform duration-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3
        border-b border-slate-200 dark:border-slate-700">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          ⚡ Commands
        </h2>
        <button
          type="button"
          onClick={onToggle}
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200
            transition-colors p-1 rounded"
        >
          <X size={16} />
        </button>
      </div>

      {/* Cards grid */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-1 gap-2">
          {commands.map((cmd) => {
            const Icon = ICON_MAP[cmd.icon] ?? Activity;
            const cardClass = CATEGORY_COLOR[cmd.category] ?? "";
            const iconClass = CATEGORY_ICON_COLOR[cmd.category] ?? "text-slate-500";
            const btnClass = CATEGORY_BTN[cmd.category] ?? "bg-slate-600 hover:bg-slate-700";
            return (
              <div
                key={cmd.id}
                className={`rounded-lg border p-3 ${cardClass} transition-colors`}
              >
                <div className="flex items-start gap-2.5">
                  <Icon size={16} className={`mt-0.5 shrink-0 ${iconClass}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {cmd.label}
                      </span>
                      {cmd.shortcut && (
                        <kbd className="text-[9px] font-mono bg-white/70 dark:bg-black/20
                          text-slate-500 rounded px-1 py-0.5 border border-slate-200
                          dark:border-slate-600">
                          {cmd.shortcut}
                        </kbd>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 leading-snug">
                      {cmd.description}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onExecute(cmd)}
                  className={`mt-2 w-full rounded text-xs font-semibold text-white py-1.5
                    transition-colors ${btnClass}`}
                >
                  Run
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer hint */}
      <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-700
        text-[10px] text-slate-400 dark:text-slate-500">
        Press <kbd className="font-mono">⌘K</kbd> for command palette
      </div>
    </aside>
  );
}
