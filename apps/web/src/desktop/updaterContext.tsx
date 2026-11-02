import { createContext, useContext, type ReactNode } from "react";

import { useAppUpdater } from "./updater";
import { useAuth } from "../features/auth/AuthContext";

type AppUpdaterState = ReturnType<typeof useAppUpdater>;

// Non-desktop/provider-free views expose inert actions; "current" here is not
// evidence that an installed product or its Runtime has passed update checks.
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

/** Share one updater lifecycle and defer account-bound calls until auth hydration settles. */
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

/** Consume the provider-owned state; reading it never starts a second update loop. */
// eslint-disable-next-line react-refresh/only-export-components
export function useAppUpdaterState(): AppUpdaterState {
  return useContext(AppUpdaterContext);
}
