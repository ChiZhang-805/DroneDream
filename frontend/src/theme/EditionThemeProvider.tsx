import {
  useCallback,
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { applyUniversalMode } from "../features/distribution/universalMode";
import {
  editionTheme,
  editionThemeForAppearance,
  type AppearanceMode,
  type EditionTheme,
} from "./editionTheme";

const APPEARANCE_STORAGE_KEY = "dronedream:appearance";

export type EditionThemeContextValue = EditionTheme & Readonly<{
  setAppearance: (appearance: AppearanceMode) => void;
  resetAppearance: () => void;
}>;

const fallbackTheme: EditionThemeContextValue = {
  ...editionTheme("universal"),
  setAppearance: () => undefined,
  resetAppearance: () => undefined,
};

const EditionThemeContext = createContext<EditionThemeContextValue>(fallbackTheme);

function storedAppearance(): AppearanceMode {
  return window.localStorage.getItem(APPEARANCE_STORAGE_KEY) === "light"
    ? "light"
    : "dark";
}

export function EditionThemeProvider({
  edition,
  children,
}: {
  edition: BrandEditionId;
  children: ReactNode;
}) {
  const [appearance, setAppearanceState] = useState<AppearanceMode>(storedAppearance);
  const setAppearance = useCallback((next: AppearanceMode) => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, next);
    setAppearanceState(next);
  }, []);
  const resetAppearance = useCallback(() => setAppearance("dark"), [setAppearance]);
  const theme = useMemo<EditionThemeContextValue>(() => ({
    ...editionThemeForAppearance(edition, appearance),
    setAppearance,
    resetAppearance,
  }), [appearance, edition, resetAppearance, setAppearance]);
  useLayoutEffect(() => {
    applyUniversalMode(edition);
    document.documentElement.dataset.ddAppearance = appearance;
    document.documentElement.style.colorScheme = appearance;
  }, [appearance, edition]);
  return (
    <EditionThemeContext.Provider value={theme}>
      {children}
    </EditionThemeContext.Provider>
  );
}

export function useEditionTheme(): EditionThemeContextValue {
  return useContext(EditionThemeContext);
}
