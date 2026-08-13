import { fetchWithDeadline } from "../../api/fetchWithDeadline";
import { getAuthAccessToken } from "../auth/authTokenStore";
import type { SoftwareEditionId } from "../licensing/softwareLicense";

export type OrganizationRole = "owner" | "admin" | "member";
export type OrganizationPlan = "plus" | "pro";
export type EditionLicenseId = SoftwareEditionId;

export interface OrganizationAccess {
  authorized: boolean;
  organization_id: string | null;
  role: OrganizationRole | null;
}

export interface OrganizationMember {
  id: string;
  display_name: string;
  email: string;
  role: OrganizationRole;
  plan: "free" | OrganizationPlan;
  subscription_status: string;
  created_at: string;
  last_sign_in_at: string | null;
  licenses: EditionLicenseId[];
}

export interface OrganizationSnapshot {
  organization: {
    id: string;
    name: string;
    plan: OrganizationPlan;
    status: "active" | "suspended";
    owner_user_id: string;
  };
  actor: {
    user_id: string;
    role: OrganizationRole;
    can_manage_members: boolean;
    can_manage_admins: boolean;
  };
  admin_limit: 3;
  members: OrganizationMember[];
}

export class OrganizationConsoleError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "OrganizationConsoleError";
    this.code = code;
    this.status = status;
  }
}

function deriveOrganizationConsoleUrl(): string {
  const explicit = (import.meta.env.VITE_ORGANIZATION_CONSOLE_URL as string | undefined)
    ?.trim();
  if (explicit) return explicit.replace(/\/+$/u, "");
  const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined)
    ?.trim()
    .replace(/\/+$/u, "");
  return supabaseUrl ? `${supabaseUrl}/functions/v1/organization-console` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthAccessToken();
  if (!token) {
    throw new OrganizationConsoleError(
      "AUTHENTICATION_REQUIRED",
      "Sign in to manage an organization.",
      401,
    );
  }
  const baseUrl = deriveOrganizationConsoleUrl();
  if (!baseUrl) {
    throw new OrganizationConsoleError(
      "SERVICE_NOT_CONFIGURED",
      "Organization management is not configured.",
      503,
    );
  }
  let response: Response;
  try {
    response = await fetchWithDeadline(`${baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    }, 30_000, 2 * 1024 * 1024);
  } catch (error) {
    throw new OrganizationConsoleError(
      "NETWORK_ERROR",
      error instanceof Error ? error.message : "Organization management is unavailable.",
      0,
    );
  }
  const payload = await response.json() as {
    data?: T;
    error?: { code?: string; message?: string };
  };
  if (!response.ok || payload.data === undefined) {
    throw new OrganizationConsoleError(
      payload.error?.code ?? "ORGANIZATION_REQUEST_FAILED",
      payload.error?.message ?? "The organization request failed.",
      response.status,
    );
  }
  return payload.data;
}

export function getOrganizationAccess(): Promise<OrganizationAccess> {
  return request<OrganizationAccess>("/access");
}

export function getOrganizationSnapshot(): Promise<OrganizationSnapshot> {
  return request<OrganizationSnapshot>("");
}

export function addOrganizationMember(
  email: string,
  role: Exclude<OrganizationRole, "owner">,
): Promise<OrganizationSnapshot> {
  return request<OrganizationSnapshot>("/members", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export function setOrganizationMemberRole(
  userId: string,
  role: Exclude<OrganizationRole, "owner">,
): Promise<OrganizationSnapshot> {
  return request<OrganizationSnapshot>(`/members/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeOrganizationMember(
  userId: string,
): Promise<OrganizationSnapshot> {
  return request<OrganizationSnapshot>(`/members/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}
