import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

import { getInstallerLocale, isDesktopRuntime } from "../desktop/bridge";
import type { FieldLocale } from "./catalog";

const STORAGE_KEY = "dronedream:field:locale";

type FieldLocaleValue = {
  locale: FieldLocale;
  setLocale: (locale: FieldLocale) => void;
};

function initialLocale(): FieldLocale {
  if (typeof window === "undefined") return "en";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "zh-CN") return saved;
  } catch {
    // The in-memory language remains available when storage is denied.
  }
  return "en";
}

const FieldLocaleContext = createContext<FieldLocaleValue>({
  locale: "en",
  setLocale: () => undefined,
});

export function FieldLocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<FieldLocale>(initialLocale);

  useEffect(() => {
    if (!isDesktopRuntime()) return;
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === "en" || saved === "zh-CN") return;
    } catch {
      // Apply the installer language in memory when storage is unavailable.
    }

    let active = true;
    void getInstallerLocale()
      .then((installerLocale) => {
        if (active) setLocaleState(installerLocale);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const setLocale = useCallback((next: FieldLocale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Keep the selection in memory when persistence is unavailable.
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return (
    <FieldLocaleContext.Provider value={value}>
      {children}
    </FieldLocaleContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useFieldLocale(): FieldLocaleValue {
  return useContext(FieldLocaleContext);
}
