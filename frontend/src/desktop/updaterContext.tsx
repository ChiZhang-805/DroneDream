import { createContext, useContext, type ReactNode } from "react";

import { useAppUpdater } from "./updater";
import { useAuth } from "../features/auth/AuthContext";

type AppUpdaterState = ReturnType<typeof useAppUpdater>;

const FALLBACK: AppUpdaterState = {
  status: "current",
  availableVersion: null,
  updateRequired: false,
  progress: null,
  error: null,
  enginePack: null,
  componentUpdates: null,
  blockedActivity: null,
  desktopRuntime: false,
  checkForUpdates: async () => undefined,
  installAvailableUpdate: async () => undefined,
  dismissBlockedActivity: () => undefined,
  installComponentUpdates: async () => undefined,
  reconcileEnginePack: async () => undefined,
  reconcileComponentPacks: async () => undefined,
};

const AppUpdaterContext = createContext<AppUpdaterState>(FALLBACK);

export function AppUpdaterProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const updater = useAppUpdater({
    enabled: !auth.loading && Boolean(auth.account),
  });
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
