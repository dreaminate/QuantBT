import { useEffect, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

const THEME_MODE_KEY = "cc-theme-mode";
const LEGACY_THEME_KEY = "cc-theme";
const SYSTEM_QUERY = "(prefers-color-scheme: dark)";

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark" || value === "system";
}

function isEffectiveTheme(value: string | null): value is EffectiveTheme {
  return value === "light" || value === "dark";
}

export function getStoredThemeMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(THEME_MODE_KEY);
  if (isThemeMode(stored)) return stored;

  const legacy = window.localStorage.getItem(LEGACY_THEME_KEY);
  if (isEffectiveTheme(legacy)) return legacy;
  return "system";
}

export function resolveThemeMode(mode: ThemeMode): EffectiveTheme {
  if (mode !== "system") return mode;
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia(SYSTEM_QUERY).matches ? "dark" : "light";
}

export function applyThemeMode(mode: ThemeMode): EffectiveTheme {
  const effective = resolveThemeMode(mode);
  if (typeof document === "undefined") return effective;

  const root = document.documentElement;
  root.setAttribute("data-theme-mode", mode);
  root.setAttribute("data-theme", effective);
  root.style.colorScheme = effective;
  return effective;
}

export function persistThemeMode(mode: ThemeMode): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(THEME_MODE_KEY, mode);
  window.localStorage.setItem(LEGACY_THEME_KEY, resolveThemeMode(mode));
}

export function useThemeMode(): {
  mode: ThemeMode;
  effective: EffectiveTheme;
  setMode: (mode: ThemeMode) => void;
} {
  const [mode, setModeState] = useState<ThemeMode>(() => getStoredThemeMode());
  const [effective, setEffective] = useState<EffectiveTheme>(() => resolveThemeMode(mode));

  useEffect(() => {
    setEffective(applyThemeMode(mode));
    persistThemeMode(mode);
  }, [mode]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia(SYSTEM_QUERY);
    const update = () => setEffective(applyThemeMode(mode));
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [mode]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (event: StorageEvent) => {
      if (event.key !== THEME_MODE_KEY && event.key !== LEGACY_THEME_KEY) return;
      setModeState(getStoredThemeMode());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return {
    mode,
    effective,
    setMode: setModeState,
  };
}
