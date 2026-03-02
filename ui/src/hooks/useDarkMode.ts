/**
 * useDarkMode — toggle dark mode with localStorage persistence.
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "claw-forge-dark-mode";

export function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) return stored === "true";
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch {
      return false;
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    try {
      localStorage.setItem(STORAGE_KEY, String(dark));
    } catch {
      // localStorage not available
    }
  }, [dark]);

  const toggle = useCallback(() => setDark((d) => !d), []);

  return [dark, toggle];
}
