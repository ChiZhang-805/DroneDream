import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  type ReactNode,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { applyUniversalMode } from "../features/distribution/universalMode";
import { editionTheme, type EditionTheme } from "./editionTheme";

const EditionThemeContext = createContext<EditionTheme>(editionTheme("universal"));

export function EditionThemeProvider({
  edition,
  children,
}: {
  edition: BrandEditionId;
  children: ReactNode;
}) {
  const theme = useMemo(() => editionTheme(edition), [edition]);
  useLayoutEffect(() => {
    applyUniversalMode(edition);
  }, [edition]);
  return (
    <EditionThemeContext.Provider value={theme}>
      {children}
    </EditionThemeContext.Provider>
  );
}

export function useEditionTheme(): EditionTheme {
  return useContext(EditionThemeContext);
}
