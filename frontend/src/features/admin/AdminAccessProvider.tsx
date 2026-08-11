import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { isDesktopRuntime } from "../../desktop/bridge";
import { useAuth } from "../auth/AuthContext";
import type { AdminAccessSnapshot } from "./adminConsole";
import {
  AdminAccessContext,
  type AdminAccessContextValue,
  type AdminAccessStatus,
} from "./AdminAccessContext";

export function AdminAccessProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const desktopRuntime = isDesktopRuntime();
  const preview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get("adminPreview") === "1";
  const [status, setStatus] = useState<AdminAccessStatus>("disabled");
  const [access, setAccess] = useState<AdminAccessSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestGeneration = useRef(0);

  const refresh = useCallback(async () => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (desktopRuntime || !auth.account || (!auth.configured && !preview)) {
      setStatus("disabled");
      setAccess(null);
      setError(null);
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const { getAdminAccess } = await import("./adminConsole");
      const snapshot = await getAdminAccess();
      if (generation !== requestGeneration.current) return;
      setAccess(snapshot);
      setStatus(snapshot.authorized ? "allowed" : "denied");
    } catch (caught) {
      if (generation !== requestGeneration.current) return;
      setAccess(null);
      const statusCode = caught instanceof Error
        && "status" in caught
        && typeof caught.status === "number"
        ? caught.status
        : 0;
      if ([401, 403].includes(statusCode)) {
        setStatus("denied");
      } else {
        setStatus("unavailable");
        setError(caught instanceof Error ? caught.message : "Administration access is unavailable.");
      }
    }
  }, [auth.account, auth.configured, desktopRuntime, preview]);

  useEffect(() => {
    void refresh();
    return () => {
      requestGeneration.current += 1;
    };
  }, [refresh]);

  const value = useMemo<AdminAccessContextValue>(() => ({
    status,
    access,
    error,
    refresh,
  }), [access, error, refresh, status]);

  return (
    <AdminAccessContext.Provider value={value}>
      {children}
    </AdminAccessContext.Provider>
  );
}
