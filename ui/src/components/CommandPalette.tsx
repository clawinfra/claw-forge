/**
 * CommandPalette — ⌘K / Ctrl+K full-screen overlay for running commands.
 *
 * Fuzzy-filters the 7 registered commands, groups by category,
 * supports arrow-key navigation and Enter to execute.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

const CATEGORY_BADGE: Record<string, string> = {
  setup: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200",
  build: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-200",
  quality: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200",
  save: "bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-200",
  monitoring: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200",
  fix: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200",
};

// ── Fuzzy match ───────────────────────────────────────────────────────────────

function fuzzyMatch(query: string, target: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface CommandPaletteProps {
  isOpen: boolean;
  commands: Command[];
  onClose: () => void;
  onExecute: (command: Command) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CommandPalette({
  isOpen,
  commands,
  onClose,
  onExecute,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Filter commands
  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    return commands.filter(
      (cmd) =>
        fuzzyMatch(query, cmd.label) ||
        fuzzyMatch(query, cmd.description) ||
        fuzzyMatch(query, cmd.category),
    );
  }, [commands, query]);

  // Reset on open/close
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Clamp active index
  useEffect(() => {
    setActiveIndex((i) => Math.min(i, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  // Scroll active item into view
  useEffect(() => {
    const el = listRef.current?.children[activeIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setActiveIndex((i) => Math.max(i - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (filtered[activeIndex]) {
            onExecute(filtered[activeIndex]);
            onClose();
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    },
    [filtered, activeIndex, onExecute, onClose],
  );

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

      {/* Panel */}
      <div
        className="relative z-10 w-full max-w-xl rounded-2xl bg-white dark:bg-slate-800 shadow-2xl
          border border-slate-200 dark:border-slate-700 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200 dark:border-slate-700">
          <span className="text-slate-400 dark:text-slate-500 text-sm font-mono">⌘</span>
          <input
            ref={inputRef}
            type="text"
            className="flex-1 bg-transparent text-sm text-slate-800 dark:text-slate-100
              placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none"
            placeholder="Search commands…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Results */}
        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-400 dark:text-slate-500">
            No commands found
          </div>
        ) : (
          <ul ref={listRef} className="max-h-80 overflow-y-auto py-1">
            {filtered.map((cmd, idx) => {
              const Icon = ICON_MAP[cmd.icon] ?? Activity;
              const isActive = idx === activeIndex;
              return (
                <li
                  key={cmd.id}
                  className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors
                    ${isActive
                      ? "bg-slate-100 dark:bg-slate-700"
                      : "hover:bg-slate-50 dark:hover:bg-slate-700/60"
                    }`}
                  onMouseEnter={() => setActiveIndex(idx)}
                  onClick={() => {
                    onExecute(cmd);
                    onClose();
                  }}
                >
                  <Icon
                    size={16}
                    className="shrink-0 text-slate-500 dark:text-slate-400"
                  />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                      {cmd.label}
                    </span>
                    <span className="ml-2 text-xs text-slate-400 dark:text-slate-500 truncate">
                      {cmd.description}
                    </span>
                  </div>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold
                      ${CATEGORY_BADGE[cmd.category] ?? "bg-slate-100 text-slate-600"}`}
                  >
                    {cmd.category}
                  </span>
                  {cmd.shortcut && (
                    <kbd className="shrink-0 text-[10px] font-mono bg-slate-100 dark:bg-slate-700
                      text-slate-500 dark:text-slate-400 rounded px-1.5 py-0.5 border
                      border-slate-200 dark:border-slate-600">
                      {cmd.shortcut}
                    </kbd>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-700
          flex items-center gap-3 text-[10px] text-slate-400 dark:text-slate-500">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> run</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
