import { useCallback, useEffect, useState } from "react";

type Theme = "dark" | "light" | "ember";

const STORAGE_KEY = "factory-portal-theme";
const GALLERY_KEY = "commandsheets-theme";
const CYCLE: Theme[] = ["ember", "dark", "light"];

function isTheme(v: string | null): v is Theme {
  return v === "dark" || v === "light" || v === "ember";
}

function getStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isTheme(stored)) return stored;
    const gallery = localStorage.getItem(GALLERY_KEY);
    if (isTheme(gallery)) return gallery;
  } catch {
    // localStorage unavailable
  }
  return null;
}

const THEME_COLORS: Record<Theme, string> = {
  ember: "#352619",
  dark: "#0b1117",
  light: "#f8fafc",
};

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLORS[theme]);
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme() ?? "ember");

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
      localStorage.setItem(GALLERY_KEY, next);
    } catch {
      // localStorage unavailable
    }
  }, []);

  const toggle = useCallback(() => {
    const next = CYCLE[(CYCLE.indexOf(theme) + 1) % CYCLE.length];
    setTheme(next);
  }, [theme, setTheme]);

  return { theme, setTheme, toggle } as const;
}
