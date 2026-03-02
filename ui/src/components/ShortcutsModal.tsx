/**
 * ShortcutsModal — keyboard shortcut help modal.
 */
import { Keyboard, X } from "lucide-react";

interface ShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const SHORTCUTS = [
  { key: "?", description: "Toggle this help" },
  { key: "D", description: "Toggle dark mode" },
  { key: "G", description: "Toggle Kanban / Graph view" },
  { key: "F", description: "Focus search input" },
  { key: "Esc", description: "Close any open panel" },
  { key: "1-5", description: "Scroll to column" },
];

export function ShortcutsModal({ isOpen, onClose }: ShortcutsModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Keyboard size={18} className="text-forge-600 dark:text-forge-500" />
            <h3 className="font-semibold text-slate-800 dark:text-slate-100">
              Keyboard Shortcuts
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-2">
          {SHORTCUTS.map((s) => (
            <div
              key={s.key}
              className="flex items-center justify-between py-1.5"
            >
              <span className="text-sm text-slate-600 dark:text-slate-300">
                {s.description}
              </span>
              <kbd className="px-2 py-1 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 rounded text-xs font-mono font-semibold border border-slate-200 dark:border-slate-600">
                {s.key}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
