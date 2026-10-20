import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "../auth/AuthContext";
import type { AdminAccessSnapshot } from "./adminConsole";
import {
  AdminAccessContext,
  type AdminAccessContextValue,
  type AdminAccessStatus,
} from "./AdminAccessContext";

export function AdminAccessProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const accountId = auth.account?.id ?? null;
  const preview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get("adminPreview") === "1";
  const [status, setStatus] = useState<AdminAccessStatus>("disabled");
  const [access, setAccess] = useState<AdminAccessSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const resolvedAccountId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (!accountId || (!auth.configured && !preview)) {
      resolvedAccountId.current = null;
      setStatus("disabled");
      setAccess(null);
      setError(null);
      return;
    }
    // A token refresh replaces the auth account object even though the signed-in
    // identity has not changed. Keep the confirmed permission visible while the
    // same account is checked again so restoring a window cannot make the
    // Administration entry disappear and then flash back into place.
    if (resolvedAccountId.current !== accountId) {
      setStatus("loading");
      setAccess(null);
    }
    setError(null);
    try {
      if (preview) {
        const { getAdminAccess } = await import("./adminConsole");
        const snapshot = await getAdminAccess();
        if (generation !== requestGeneration.current) return;
        resolvedAccountId.current = accountId;
        setAccess(snapshot);
        setStatus(snapshot.authorized ? "allowed" : "denied");
        return;
      }
      const { getOrganizationAccess } = await import("../organization/organizationConsole");
      const organization = await getOrganizationAccess();
      const snapshot: AdminAccessSnapshot = {
        authorized: organization.authorized,
        role: organization.role === "owner" || organization.role === "admin"
          ? organization.role
          : null,
        permissions: organization.role === "owner"
          ? ["organization.members", "organization.admins", "organization.founder"]
          : organization.role === "admin"
            ? ["organization.members"]
            : [],
      };
      if (generation !== requestGeneration.current) return;
      resolvedAccountId.current = accountId;
      setAccess(snapshot);
      setStatus(snapshot.authorized ? "allowed" : "denied");
    } catch (caught) {
      if (generation !== requestGeneration.current) return;
      resolvedAccountId.current = accountId;
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
  }, [accountId, auth.configured, preview]);

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
