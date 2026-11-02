import { fetchWithDeadline } from "../../api/fetchWithDeadline";
import { getAuthAccessToken } from "./authTokenStore";

export class AccountDeletionError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AccountDeletionError";
    this.code = code;
  }
}

function accountSelfServiceUrl(): string {
  const explicit = (import.meta.env.VITE_ACCOUNT_SELF_SERVICE_URL as string | undefined)?.trim();
  if (explicit) return explicit.replace(/\/+$/u, "");
  const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined)?.trim().replace(/\/+$/u, "");
  return supabaseUrl ? `${supabaseUrl}/functions/v1/account-self-service` : "";
}

export async function deleteCurrentAccount(): Promise<void> {
  const token = getAuthAccessToken();
  const endpoint = accountSelfServiceUrl();
  if (!token) throw new AccountDeletionError("AUTHENTICATION_REQUIRED", "Sign in before deleting your account.");
  if (!endpoint) throw new AccountDeletionError("SERVICE_NOT_CONFIGURED", "Account deletion is unavailable.");

  const response = await fetchWithDeadline(`${endpoint}/delete`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ confirmation: "DELETE" }),
  }, 20_000, 64 * 1024);
  const payload = await response.json().catch(() => null) as {
    error?: { code?: string; message?: string };
  } | null;
  if (!response.ok) {
    throw new AccountDeletionError(
      payload?.error?.code ?? "ACCOUNT_DELETE_FAILED",
      payload?.error?.message ?? "The account could not be deleted.",
    );
  }
}
