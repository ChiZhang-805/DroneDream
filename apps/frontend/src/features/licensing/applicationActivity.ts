import { BUILD_EDITION } from "../../edition";
import { isDesktopRuntime } from "../../desktop/bridge";
import { supabaseClient } from "../auth/supabaseClient";

const recordedAccounts = new Set<string>();

/** Record a successful desktop sign-in for the installed edition. */
export async function recordDesktopApplicationActivity(accountId: string): Promise<void> {
  if (!isDesktopRuntime() || !supabaseClient) return;
  const key = `${accountId}:${BUILD_EDITION}`;
  if (recordedAccounts.has(key)) return;
  const { error } = await supabaseClient.rpc("record_user_application_activity", {
    p_edition: BUILD_EDITION,
  });
  if (error) throw error;
  recordedAccounts.add(key);
}
