import { useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "note-atlas-theme";

function readPref(): ThemePref {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // Private mode can block localStorage.
  }
  return "system";
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function resolve(pref: ThemePref): ResolvedTheme {
  return pref === "system" ? systemTheme() : pref;
}

function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

export function useTheme(): {
  pref: ThemePref;
  resolved: ResolvedTheme;
  cycle: () => void;
} {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolve(readPref()));

  useEffect(() => {
    function sync(): void {
      const next = resolve(pref);
      setResolved(next);
      applyTheme(next);
    }
    sync();
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      // Ignore quota / private-mode failures.
    }
    const media = window.matchMedia("(prefers-color-scheme: light)");
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [pref]);

  function cycle(): void {
    setPref((current) => {
      if (current === "system") {
        return "light";
      }
      if (current === "light") {
        return "dark";
      }
      return "system";
    });
  }

  return { pref, resolved, cycle };
}
