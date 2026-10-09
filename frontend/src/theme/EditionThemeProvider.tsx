import {
  createContext,
  useContext,
  useLayoutEffect,
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
  type EditionTheme,
} from "./editionTheme";

const APPEARANCE_STORAGE_KEY = "dronedream:appearance";
const CUSTOM_ACCENT_STORAGE_KEY = "dronedream:custom-accent";
export type EditionThemeContextValue = EditionTheme;

const EditionThemeContext = createContext<EditionThemeContextValue>(editionTheme("universal"));

/** Own the one fixed palette for this product edition; mount one provider per page. */
export function EditionThemeProvider({
  edition,
  children,
}: {
  edition: BrandEditionId;
  children: ReactNode;
}) {
  const reducedMotion = useSyncExternalStore(
    subscribeToAppReducedMotion,
    appReducedMotionEnabled,
    () => false,
  );
  const theme = editionTheme(edition);
  useLayoutEffect(() => {
    applyUniversalMode(edition);
    document.documentElement.dataset.ddAppearance = "light";
    document.documentElement.dataset.ddReducedMotion = String(reducedMotion);
    document.documentElement.style.colorScheme = "light";
    document.documentElement.style.removeProperty("--dd-brand-start");
    document.documentElement.style.removeProperty("--dd-brand-middle");
    document.documentElement.style.removeProperty("--dd-brand-end");
    try {
      window.localStorage.removeItem(APPEARANCE_STORAGE_KEY);
      window.localStorage.removeItem(CUSTOM_ACCENT_STORAGE_KEY);
    } catch {
      // A denied storage API cannot alter the fixed palette.
    }
  }, [edition, reducedMotion]);
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
