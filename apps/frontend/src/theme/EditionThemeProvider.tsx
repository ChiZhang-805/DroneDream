import {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { isDesktopRuntime } from "../desktop/bridge";
import { applyUniversalMode } from "../features/distribution/universalMode";
import {
  appReducedMotionEnabled,
  subscribeToAppReducedMotion,
} from "../desktop/uiMotionPreferences";
import {
  DEFAULT_APPEARANCE,
  editionTheme,
  editionThemeForAppearance,
  type AppearanceMode,
  type EditionTheme,
} from "./editionTheme";

const CUSTOM_ACCENT_STORAGE_KEY = "dronedream:custom-accent";
export type AppearancePreference = AppearanceMode;

export type EditionThemeContextValue = EditionTheme & Readonly<{
  appearancePreference: AppearancePreference;
  customAccent: string;
  setAppearance: (appearance: AppearancePreference) => void;
  setCustomAccent: (accent: string) => void;
  resetAppearance: () => void;
}>;

const fallbackTheme: EditionThemeContextValue = {
  ...editionTheme("universal"),
  appearancePreference: DEFAULT_APPEARANCE,
  customAccent: "#8d72ee",
  setAppearance: () => undefined,
  setCustomAccent: () => undefined,
  resetAppearance: () => undefined,
};

const EditionThemeContext = createContext<EditionThemeContextValue>(fallbackTheme);

/** Permit a hex color token only; arbitrary CSS is never interpolated from persisted text. */
function storedCustomAccent(): string {
  let stored = "";
  try { stored = window.localStorage.getItem(CUSTOM_ACCENT_STORAGE_KEY) ?? ""; }
  catch { /* Use the normal accent when the browser denies storage access. */ }
  return /^#[0-9a-f]{6}$/iu.test(stored) ? stored : "#8d72ee";
}

/** Start each app session in light mode; appearance changes belong to this mounted app only. */
export function EditionThemeProvider({
  edition,
  children,
}: {
  edition: BrandEditionId;
  children: ReactNode;
}) {
  const [appearancePreference, setAppearanceState] =
    useState<AppearancePreference>(DEFAULT_APPEARANCE);
  const [customAccent, setCustomAccentState] = useState(storedCustomAccent);
  const reducedMotion = useSyncExternalStore(
    subscribeToAppReducedMotion,
    appReducedMotionEnabled,
    () => false,
  );
  const setAppearance = useCallback((next: AppearancePreference) => {
    // Do not restore or replace legacy persisted appearance: every new launch
    // starts light, while language and other durable preferences stay intact.
    setAppearanceState(next);
  }, []);
  const setCustomAccent = useCallback((next: string) => {
    if (!/^#[0-9a-f]{6}$/iu.test(next)) return;
    const normalized = next.toLowerCase();
    try { window.localStorage.setItem(CUSTOM_ACCENT_STORAGE_KEY, normalized); }
    catch { /* State below still makes the selected color usable this session. */ }
    setCustomAccentState(normalized);
  }, []);
  const resetAppearance = useCallback(() => setAppearance(DEFAULT_APPEARANCE), [setAppearance]);
  const appearance: AppearanceMode = appearancePreference;
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
    document.documentElement.style.removeProperty("--dd-brand-start");
    document.documentElement.style.removeProperty("--dd-brand-middle");
    document.documentElement.style.removeProperty("--dd-brand-end");
  }, [appearance, edition, reducedMotion]);
  useEffect(() => {
    if (!isDesktopRuntime()) return;
    let active = true;
    void import("@tauri-apps/api/window")
      .then(({ getCurrentWindow }) => {
        if (active) return getCurrentWindow().setTheme(appearance);
      })
      .catch(() => {
        // Native chrome failure must not prevent the in-app theme from changing.
      });
    return () => { active = false; };
  }, [appearance]);
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
