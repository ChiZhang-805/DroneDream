import type { BrowserAuthSession } from "../../desktop/bridge";
import { supabaseClient } from "./supabaseClient";

export async function adoptBrowserAuthSession(
  session: BrowserAuthSession,
): Promise<void> {
  if (!supabaseClient) {
    throw new Error("DroneDream account authentication is not configured.");
  }
  const { error } = await supabaseClient.auth.setSession({
    access_token: session.accessToken,
    refresh_token: session.refreshToken,
  });
  if (error) {
    throw new Error(error.message || "The browser session could not be adopted.");
  }
}
