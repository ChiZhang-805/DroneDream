import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type { InterfaceLocale } from "../../i18n/I18nProvider";
import type { AppearancePreference } from "../../theme/EditionThemeProvider";
import { supabaseClient } from "../auth/supabaseClient";

const PERSONAL_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000000";

export type ConsoleMemoryScope =
  | "chat_preferences"
  | "experiment_defaults"
  | "device_vehicle"
  | "metrics_constraints"
  | "safety_approvals"
  | "workflow_tools"
  | "reports_delivery";

export interface ConsolePreferenceBoundary {
  userId: string;
  tenantId: string;
  organizationId: string | null;
  workspaceId: string;
  edition: BrandEditionId;
}

export interface ConsolePreferenceRecord {
  interface_locale: InterfaceLocale;
  appearance_mode: AppearancePreference;
  custom_accent: string;
  notifications: Record<string, boolean>;
  memory_enabled: boolean;
  memory_scopes: Record<ConsoleMemoryScope, boolean>;
  defaults: Record<string, string | number | null>;
}

function client() {
  if (!supabaseClient) throw new Error("CLOUD_PREFERENCES_NOT_CONFIGURED");
  return supabaseClient;
}

function boundaryColumns(boundary: ConsolePreferenceBoundary) {
  return {
    user_id: boundary.userId,
    tenant_id: boundary.tenantId,
    organization_id: boundary.organizationId ?? PERSONAL_ORGANIZATION_ID,
    workspace_id: boundary.workspaceId,
    edition: boundary.edition,
  };
}

export async function loadConsolePreferences(
  boundary: ConsolePreferenceBoundary,
): Promise<ConsolePreferenceRecord | null> {
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().from("console_preferences").select(
      "interface_locale,appearance_mode,custom_accent,notifications,memory_enabled,memory_scopes,defaults",
    )
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition)
    .maybeSingle();
  if (error) throw error;
  return data as ConsolePreferenceRecord | null;
}

export async function saveConsolePreferences(
  boundary: ConsolePreferenceBoundary,
  preference: ConsolePreferenceRecord,
): Promise<void> {
  const { error } = await client().from("console_preferences").upsert({
    ...boundaryColumns(boundary),
    ...preference,
    updated_at: new Date().toISOString(),
  }, { onConflict: "user_id,tenant_id,organization_id,workspace_id,edition" });
  if (error) throw error;
}

export async function deleteConsolePreferencesAndMemory(
  boundary: ConsolePreferenceBoundary,
): Promise<number> {
  const columns = boundaryColumns(boundary);
  const memoryDelete = await client().from("console_memory_records")
    .delete()
    .select("memory_id")
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition);
  if (memoryDelete.error) throw memoryDelete.error;
  const preferencesDelete = await client().from("console_preferences")
    .delete()
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition);
  if (preferencesDelete.error) throw preferencesDelete.error;
  return memoryDelete.data?.length ?? 0;
}

export async function loadConsoleMemory(
  boundary: ConsolePreferenceBoundary,
  scopes: ConsoleMemoryScope[],
): Promise<Array<{ scope: ConsoleMemoryScope; payload: Record<string, unknown> }>> {
  if (scopes.length === 0) return [];
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().from("console_memory_records")
    .select("scope,payload")
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition)
    .in("scope", scopes)
    .gt("expires_at", new Date().toISOString())
    .order("updated_at", { ascending: false })
    .limit(64);
  if (error) throw error;
  return (data ?? []) as Array<{ scope: ConsoleMemoryScope; payload: Record<string, unknown> }>;
}
