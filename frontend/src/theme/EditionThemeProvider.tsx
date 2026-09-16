import {
  useCallback,
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { applyUniversalMode } from "../features/distribution/universalMode";
import {
  appReducedMotionEnabled,
  subscribeToAppReducedMotion,
} from "../desktop/uiMotionPreferences";
import {
  editionTheme,
  editionThemeForAppearance,
  type AppearanceMode,
  type EditionTheme,
} from "./editionTheme";

const APPEARANCE_STORAGE_KEY = "dronedream:appearance";
const CUSTOM_ACCENT_STORAGE_KEY = "dronedream:custom-accent";
export type AppearancePreference = AppearanceMode | "system" | "custom";

export type EditionThemeContextValue = EditionTheme & Readonly<{
  appearancePreference: AppearancePreference;
  customAccent: string;
  setAppearance: (appearance: AppearancePreference) => void;
  setCustomAccent: (accent: string) => void;
  resetAppearance: () => void;
}>;

const fallbackTheme: EditionThemeContextValue = {
  ...editionTheme("universal"),
  appearancePreference: "dark",
  customAccent: "#8d72ee",
  setAppearance: () => undefined,
  setCustomAccent: () => undefined,
  resetAppearance: () => undefined,
};

const EditionThemeContext = createContext<EditionThemeContextValue>(fallbackTheme);

/** Invalid or unavailable browser preferences fall back locally, not to a cloud account value. */
function storedAppearance(): AppearancePreference {
  let stored: string | null = null;
  try { stored = window.localStorage.getItem(APPEARANCE_STORAGE_KEY); }
  catch { /* Browser policy can deny persistence while still allowing the app. */ }
  return stored === "light" || stored === "system" || stored === "custom"
    ? stored
    : "dark";
}

/** Permit a hex color token only; arbitrary CSS is never interpolated from persisted text. */
function storedCustomAccent(): string {
  let stored = "";
  try { stored = window.localStorage.getItem(CUSTOM_ACCENT_STORAGE_KEY) ?? ""; }
  catch { /* Use the normal accent when the browser denies storage access. */ }
  return /^#[0-9a-f]{6}$/iu.test(stored) ? stored : "#8d72ee";
}

/** Own document-wide edition tokens and per-device appearance; mount one provider per page. */
export function EditionThemeProvider({
  edition,
  children,
}: {
  edition: BrandEditionId;
  children: ReactNode;
}) {
  const [appearancePreference, setAppearanceState] =
    useState<AppearancePreference>(storedAppearance);
  const [customAccent, setCustomAccentState] = useState(storedCustomAccent);
  const [systemAppearance, setSystemAppearance] = useState<AppearanceMode>(() =>
    window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark"
  );
  const reducedMotion = useSyncExternalStore(
    subscribeToAppReducedMotion,
    appReducedMotionEnabled,
    () => false,
  );
  const setAppearance = useCallback((next: AppearancePreference) => {
    try { window.localStorage.setItem(APPEARANCE_STORAGE_KEY, next); }
    catch { /* Apply in this mounted page without claiming durable storage. */ }
    setAppearanceState(next);
  }, []);
  const setCustomAccent = useCallback((next: string) => {
    if (!/^#[0-9a-f]{6}$/iu.test(next)) return;
    const normalized = next.toLowerCase();
    try { window.localStorage.setItem(CUSTOM_ACCENT_STORAGE_KEY, normalized); }
    catch { /* State below still makes the selected color usable this session. */ }
    setCustomAccentState(normalized);
  }, []);
  const resetAppearance = useCallback(() => setAppearance("dark"), [setAppearance]);
  useLayoutEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!query) return undefined;
    const update = () => setSystemAppearance(query.matches ? "light" : "dark");
    update();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", update);
      return () => query.removeEventListener("change", update);
    }
    query.addListener?.(update);
    return () => query.removeListener?.(update);
  }, []);
  const appearance: AppearanceMode = appearancePreference === "system"
    ? systemAppearance
    : appearancePreference === "light" ? "light" : "dark";
  const theme = useMemo<EditionThemeContextValue>(() => ({
    ...editionThemeForAppearance(edition, appearance),
    appearancePreference,
    customAccent,
    setAppearance,
    setCustomAccent,
    resetAppearance,
  }), [appearance, appearancePreference, customAccent, edition, resetAppearance, setAppearance, setCustomAccent]);
  useLayoutEffect(() => {
    applyUniversalMode(edition);
    document.documentElement.dataset.ddAppearance = appearance;
    document.documentElement.dataset.ddReducedMotion = String(reducedMotion);
    document.documentElement.style.colorScheme = appearance;
    if (appearancePreference === "custom") {
      document.documentElement.style.setProperty("--dd-brand-start", customAccent);
      document.documentElement.style.setProperty("--dd-brand-middle", customAccent);
      document.documentElement.style.setProperty("--dd-brand-end", customAccent);
    } else {
      document.documentElement.style.removeProperty("--dd-brand-start");
      document.documentElement.style.removeProperty("--dd-brand-middle");
      document.documentElement.style.removeProperty("--dd-brand-end");
    }
  }, [appearance, appearancePreference, customAccent, edition, reducedMotion]);
  return (
    <EditionThemeContext.Provider value={theme}>
      {children}
    </EditionThemeContext.Provider>
  );
}

// The hook is deliberately colocated with its provider so consumers cannot bind
// to a different context instance during product-edition switching.
// eslint-disable-next-line react-refresh/only-export-components
export function useEditionTheme(): EditionThemeContextValue {
  return useContext(EditionThemeContext);
}
