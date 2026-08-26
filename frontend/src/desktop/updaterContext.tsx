import { createContext, useContext, type ReactNode } from "react";

import { useAppUpdater } from "./updater";

type AppUpdaterState = ReturnType<typeof useAppUpdater>;

const FALLBACK: AppUpdaterState = {
  status: "current",
  availableVersion: null,
  updateRequired: false,
  progress: null,
  error: null,
  enginePack: null,
  componentUpdates: null,
  desktopRuntime: false,
  checkForUpdates: async () => undefined,
  installAvailableUpdate: async () => undefined,
  installComponentUpdates: async () => undefined,
  reconcileEnginePack: async () => undefined,
  reconcileComponentPacks: async () => undefined,
};

const AppUpdaterContext = createContext<AppUpdaterState>(FALLBACK);

export function AppUpdaterProvider({ children }: { children: ReactNode }) {
  const updater = useAppUpdater();
  return (
    <AppUpdaterContext.Provider value={updater}>
      {children}
    </AppUpdaterContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAppUpdaterState(): AppUpdaterState {
  return useContext(AppUpdaterContext);
}
