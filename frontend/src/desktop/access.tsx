import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { isDesktopRuntime } from "./bridge";
import { probeOverallDesktopReadiness } from "./readiness";

export type DesktopRuntimeAccessStatus =
  | "browser"
  | "checking"
  | "ready"
  | "blocked";

export interface DesktopRuntimeAccess {
  desktopRuntime: boolean;
  status: DesktopRuntimeAccessStatus;
  canUseRuntime: boolean;
  refresh: () => Promise<void>;
}

const BROWSER_ACCESS: DesktopRuntimeAccess = {
  desktopRuntime: false,
  status: "browser",
  canUseRuntime: true,
  refresh: async () => undefined,
};

const DesktopRuntimeAccessContext = createContext<DesktopRuntimeAccess>(BROWSER_ACCESS);

export function DesktopRuntimeAccessProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const requestId = useRef(0);
  const [status, setStatus] = useState<DesktopRuntimeAccessStatus>(
    desktopRuntime ? "checking" : "browser",
  );

  const refresh = useCallback(async () => {
    if (!desktopRuntime) {
      setStatus("browser");
      return;
    }

    const currentRequest = ++requestId.current;
    // A fresh probe invalidates the previous result immediately. Keeping an
    // old "ready" value visible here would briefly re-enable mutating actions
    // while the current Runtime state is still unknown.
    setStatus("checking");
    try {
      const snapshot = await probeOverallDesktopReadiness();
      if (requestId.current === currentRequest) {
        setStatus(snapshot.ready ? "ready" : "blocked");
      }
    } catch {
      if (requestId.current === currentRequest) setStatus("blocked");
    }
  }, [desktopRuntime]);

  useEffect(() => {
    void refresh();
    return () => {
      requestId.current += 1;
    };
  }, [location.pathname, location.search, refresh]);

  const value = useMemo<DesktopRuntimeAccess>(() => ({
    desktopRuntime,
    status,
    canUseRuntime: !desktopRuntime || status === "ready",
    refresh,
  }), [desktopRuntime, refresh, status]);

  return (
    <DesktopRuntimeAccessContext.Provider value={value}>
      {children}
    </DesktopRuntimeAccessContext.Provider>
  );
}

// The provider and its consumer hook intentionally share this small module.
// eslint-disable-next-line react-refresh/only-export-components
export function useDesktopRuntimeAccess(): DesktopRuntimeAccess {
  return useContext(DesktopRuntimeAccessContext);
}
