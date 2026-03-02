/**
 * useKeyboardShortcuts — global keyboard shortcut handler.
 */
import { useEffect } from "react";

export interface ShortcutHandlers {
  toggleDarkMode: () => void;
  toggleGraphView: () => void;
  toggleShortcutsModal: () => void;
  focusSearch: () => void;
  closeAll: () => void;
  scrollToColumn: (index: number) => void;
}

export function useKeyboardShortcuts(handlers: ShortcutHandlers) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Don't trigger when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") {
          (e.target as HTMLElement).blur();
          handlers.closeAll();
        }
        return;
      }

      switch (e.key) {
        case "?":
          e.preventDefault();
          handlers.toggleShortcutsModal();
          break;
        case "d":
        case "D":
          e.preventDefault();
          handlers.toggleDarkMode();
          break;
        case "g":
        case "G":
          e.preventDefault();
          handlers.toggleGraphView();
          break;
        case "f":
        case "F":
          e.preventDefault();
          handlers.focusSearch();
          break;
        case "Escape":
          handlers.closeAll();
          break;
        case "1":
        case "2":
        case "3":
        case "4":
        case "5":
          e.preventDefault();
          handlers.scrollToColumn(parseInt(e.key) - 1);
          break;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handlers]);
}
