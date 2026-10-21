import { createContext, useContext } from "react";

import type { AdminAccessSnapshot } from "./adminConsole";

export type AdminAccessStatus =
  | "disabled"
  | "loading"
  | "allowed"
  | "denied"
  | "unavailable";

export interface AdminAccessContextValue {
  status: AdminAccessStatus;
  access: AdminAccessSnapshot | null;
  error: string | null;
  refresh: () => Promise<void>;
}

export const AdminAccessContext = createContext<AdminAccessContextValue | null>(null);

export function useAdminAccess(): AdminAccessContextValue {
  const context = useContext(AdminAccessContext);
  if (!context) {
    throw new Error("useAdminAccess must be used inside AdminAccessProvider");
  }
  return context;
}
