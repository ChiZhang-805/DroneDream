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
import {
  clearRuntimeAutoStartFailure,
  ensureOverallDesktopReadiness,
  getDesktopReadinessSession,
  subscribeDesktopReadiness,
} from "./readiness";
import type { DesktopReadinessSnapshot } from "./readiness";

export type DesktopRuntimeAccessStatus =
  | "browser"
  | "checking"
  | "starting"
  | "startFailed"
  | "ready"
  | "blocked";

export interface DesktopRuntimeAccess {
  desktopRuntime: boolean;
  status: DesktopRuntimeAccessStatus;
  canUseRuntime: boolean;
  snapshot: DesktopReadinessSnapshot | null;
  lastFullCheckAt: number | null;
  isChecking: boolean;
  refresh: () => Promise<void>;
}

const BROWSER_ACCESS: DesktopRuntimeAccess = {
  desktopRuntime: false,
  status: "browser",
  canUseRuntime: true,
  snapshot: null,
  lastFullCheckAt: null,
  isChecking: false,
  refresh: async () => undefined,
};

const DesktopRuntimeAccessContext = createContext<DesktopRuntimeAccess>(BROWSER_ACCESS);

export function DesktopRuntimeAccessProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const initialPath = useRef(location.pathname);
  const requestId = useRef(0);
  const initialSession = getDesktopReadinessSession();
  const shouldCheckBeforeWorkspace = desktopRuntime &&
    initialPath.current === "/desktop/setup" &&
    !initialSession;
  const [status, setStatus] = useState<DesktopRuntimeAccessStatus>(
    desktopRuntime
      ? initialSession?.snapshot.ready
        ? "ready"
        : initialSession?.snapshot.autoStartFailed
          ? "startFailed"
          : initialSession
            ? "blocked"
            : shouldCheckBeforeWorkspace
              ? "checking"
              : "blocked"
      : "browser",
  );
  const [snapshot, setSnapshot] = useState<DesktopReadinessSnapshot | null>(
    desktopRuntime ? initialSession?.snapshot ?? null : null,
  );
  const snapshotRef = useRef<DesktopReadinessSnapshot | null>(
    desktopRuntime ? initialSession?.snapshot ?? null : null,
  );
  const [lastFullCheckAt, setLastFullCheckAt] = useState<number | null>(
    desktopRuntime ? initialSession?.lastFullCheckAt ?? null : null,
  );
  const [isChecking, setIsChecking] = useState(shouldCheckBeforeWorkspace);

  const applySnapshot = useCallback((next: DesktopReadinessSnapshot) => {
    snapshotRef.current = next;
    setSnapshot(next);
    setStatus(next.ready ? "ready" : next.autoStartFailed ? "startFailed" : "blocked");
  }, []);

  const refresh = useCallback(async () => {
    if (!desktopRuntime) {
      setStatus("browser");
      return;
    }

    const currentRequest = ++requestId.current;
    setIsChecking(true);
    if (!snapshotRef.current) setStatus("checking");
    clearRuntimeAutoStartFailure();
    let automaticStartAttempted = false;
    try {
      const snapshot = await ensureOverallDesktopReadiness({
        autoStart: true,
        force: true,
        shouldAutoStart: () => requestId.current === currentRequest,
        onStarting: () => {
          automaticStartAttempted = true;
        },
      });
      if (requestId.current !== currentRequest) return;
      applySnapshot(snapshot);
    } catch {
      if (requestId.current === currentRequest) {
        setStatus(automaticStartAttempted ? "startFailed" : "blocked");
      }
    } finally {
      if (requestId.current === currentRequest) setIsChecking(false);
    }
  }, [applySnapshot, desktopRuntime]);

  useEffect(() => {
    if (!desktopRuntime) return;
    return subscribeDesktopReadiness((session) => {
      snapshotRef.current = session.snapshot;
      setSnapshot(session.snapshot);
      setLastFullCheckAt(session.lastFullCheckAt);
      applySnapshot(session.snapshot);
    });
  }, [applySnapshot, desktopRuntime]);

  useEffect(() => {
    if (!desktopRuntime) {
      setStatus("browser");
      setIsChecking(false);
      return;
    }

    // A full automatic check is allowed only on the setup screen, before the
    // user enters the workspace. Dashboard, history, settings, and route
    // changes must never start a probe. Inside the workspace, refresh() is the
    // sole full-check entry point and is wired only to the explicit Settings
    // button.
    if (initialPath.current !== "/desktop/setup" || getDesktopReadinessSession()) {
      setIsChecking(false);
      return;
    }

    const currentRequest = ++requestId.current;
    setStatus("checking");
    setIsChecking(true);
    let automaticStartAttempted = false;
    void ensureOverallDesktopReadiness({
      autoStart: false,
      shouldAutoStart: () => requestId.current === currentRequest,
      onStarting: () => {
        automaticStartAttempted = true;
        if (requestId.current === currentRequest) setStatus("starting");
      },
    }).then((next) => {
      if (requestId.current === currentRequest) applySnapshot(next);
    }).catch(() => {
      if (requestId.current === currentRequest) {
        setStatus(automaticStartAttempted ? "startFailed" : "blocked");
      }
    }).finally(() => {
      if (requestId.current === currentRequest) setIsChecking(false);
    });

    return () => {
      requestId.current += 1;
    };
  }, [applySnapshot, desktopRuntime]);

  const value = useMemo<DesktopRuntimeAccess>(() => ({
    desktopRuntime,
    status,
    canUseRuntime: !desktopRuntime || (status === "ready" && !isChecking),
    snapshot,
    lastFullCheckAt,
    isChecking,
    refresh,
  }), [desktopRuntime, isChecking, lastFullCheckAt, refresh, snapshot, status]);

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
