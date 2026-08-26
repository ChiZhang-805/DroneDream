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
  | "reports_delivery"
  | "collaboration_organization"
  | "files_artifacts";

export const MODEL_HARNESS_MEMORY_NAMESPACES = [
  "account.shared",
  "optimization.control_tuning",
  "autonomy.mission",
  "asset.qualification",
  "experiment.simulation",
  "workflow.cross_edition",
  "validation.hardware",
  "calibration.system",
  "transfer.sim_to_real",
  "transfer.real_to_sim",
  "operations.field",
] as const;

export type ModelHarnessMemoryNamespace =
  typeof MODEL_HARNESS_MEMORY_NAMESPACES[number];

export interface ConsoleMemoryRecord {
  responsibility_namespace: ModelHarnessMemoryNamespace;
  scope: ConsoleMemoryScope;
  memory_key: string;
  memory_kind: "structured_state" | "curated_note";
  payload: Record<string, unknown>;
  evidence_count: number;
  confidence: number;
  first_seen: string;
  last_seen: string;
}

export interface ConsoleMemoryCandidate extends ConsoleMemoryRecord {
  candidate_id: string;
  status: "staged" | "conflict";
}

export interface ConsoleMemoryForgetTarget {
  responsibilityNamespace: ModelHarnessMemoryNamespace;
  scope?: ConsoleMemoryScope;
  memoryKey?: string;
}

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

export interface ConsoleMemoryConsentRecord {
  memory_enabled: boolean;
  read_namespaces: ModelHarnessMemoryNamespace[];
  write_namespaces: ModelHarnessMemoryNamespace[];
  memory_scopes: Record<ConsoleMemoryScope, boolean>;
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

export async function loadConsoleMemoryConsent(
  boundary: ConsolePreferenceBoundary,
): Promise<ConsoleMemoryConsentRecord | null> {
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().from("console_memory_consents")
    .select("memory_enabled,read_namespaces,write_namespaces,memory_scopes")
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .maybeSingle();
  if (error) throw error;
  return data as ConsoleMemoryConsentRecord | null;
}

export async function saveConsoleMemoryConsent(
  boundary: ConsolePreferenceBoundary,
  consent: ConsoleMemoryConsentRecord,
): Promise<void> {
  const columns = boundaryColumns(boundary);
  const { error } = await client().from("console_memory_consents").upsert({
    user_id: columns.user_id,
    tenant_id: columns.tenant_id,
    organization_id: columns.organization_id,
    ...consent,
    updated_at: new Date().toISOString(),
  }, { onConflict: "user_id,tenant_id,organization_id" });
  if (error) throw error;
}

export async function deleteConsolePreferencesAndMemory(
  boundary: ConsolePreferenceBoundary,
): Promise<number> {
  const columns = boundaryColumns(boundary);
  const { data: deleted, error: deleteError } = await client().rpc(
    "console_memory_permanently_delete_all_current_user",
    {
      p_tenant_id: columns.tenant_id,
      p_organization_id: columns.organization_id,
    },
  );
  if (deleteError) throw deleteError;
  const consentDelete = await client().from("console_memory_consents")
    .delete()
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id);
  if (consentDelete.error) throw consentDelete.error;
  const preferencesDelete = await client().from("console_preferences")
    .delete()
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition);
  if (preferencesDelete.error) throw preferencesDelete.error;
  const count = Number(deleted ?? 0);
  return Number.isSafeInteger(count) && count >= 0 ? count : 0;
}

export async function loadConsoleMemory(
  boundary: ConsolePreferenceBoundary,
  scopes: ConsoleMemoryScope[],
  responsibilityNamespaces: readonly ModelHarnessMemoryNamespace[] =
    MODEL_HARNESS_MEMORY_NAMESPACES,
): Promise<ConsoleMemoryRecord[]> {
  if (scopes.length === 0 || responsibilityNamespaces.length === 0) return [];
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().from("console_memory_records")
    .select(
      "responsibility_namespace,scope,memory_key,memory_kind,payload,evidence_count,confidence,first_seen,last_seen",
    )
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .in("responsibility_namespace", [...responsibilityNamespaces])
    .in("scope", scopes)
    .eq("status", "active")
    .gt("expires_at", new Date().toISOString())
    .order("confidence", { ascending: false })
    .order("last_seen", { ascending: false })
    .limit(64);
  if (error) throw error;
  return (data ?? []) as ConsoleMemoryRecord[];
}

export async function loadConsoleMemoryCandidates(
  boundary: ConsolePreferenceBoundary,
  responsibilityNamespaces: readonly ModelHarnessMemoryNamespace[] =
    MODEL_HARNESS_MEMORY_NAMESPACES,
): Promise<ConsoleMemoryCandidate[]> {
  if (responsibilityNamespaces.length === 0) return [];
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().from("console_memory_candidates")
    .select(
      "candidate_id,responsibility_namespace,scope,memory_key,memory_kind,payload,evidence_count,confidence,status,first_seen,last_seen",
    )
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .in("responsibility_namespace", [...responsibilityNamespaces])
    .in("status", ["staged", "conflict"])
    .gt("expires_at", new Date().toISOString())
    .order("last_seen", { ascending: false })
    .limit(64);
  if (error) throw error;
  return (data ?? []) as ConsoleMemoryCandidate[];
}

export async function forgetConsoleMemory(
  boundary: ConsolePreferenceBoundary,
  target: ConsoleMemoryForgetTarget,
): Promise<number> {
  if (target.memoryKey && !target.scope) {
    throw new Error("MEMORY_SCOPE_REQUIRED_FOR_RECORD_FORGET");
  }
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().rpc(
    "console_memory_forget_current_user",
    {
      p_tenant_id: columns.tenant_id,
      p_organization_id: columns.organization_id,
      p_responsibility_namespace: target.responsibilityNamespace,
      p_scope: target.scope ?? null,
      p_memory_key: target.memoryKey ?? null,
    },
  );
  if (error) throw error;
  const count = Number(data ?? 0);
  return Number.isSafeInteger(count) && count >= 0 ? count : 0;
}

export async function permanentlyDeleteConsoleMemory(
  boundary: ConsolePreferenceBoundary,
  target: ConsoleMemoryForgetTarget,
): Promise<number> {
  if (target.memoryKey && !target.scope) {
    throw new Error("MEMORY_SCOPE_REQUIRED_FOR_RECORD_DELETE");
  }
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().rpc(
    "console_memory_permanently_delete_current_user",
    {
      p_tenant_id: columns.tenant_id,
      p_organization_id: columns.organization_id,
      p_responsibility_namespace: target.responsibilityNamespace,
      p_scope: target.scope ?? null,
      p_memory_key: target.memoryKey ?? null,
    },
  );
  if (error) throw error;
  const count = Number(data ?? 0);
  return Number.isSafeInteger(count) && count >= 0 ? count : 0;
}

export async function forgetConsoleMemoryDomain(
  boundary: ConsolePreferenceBoundary,
  responsibilityNamespace: ModelHarnessMemoryNamespace,
): Promise<number> {
  return forgetConsoleMemory(boundary, { responsibilityNamespace });
}

export async function forgetConsoleMemoryRecord(
  boundary: ConsolePreferenceBoundary,
  record: Pick<
    ConsoleMemoryRecord,
    "responsibility_namespace" | "scope" | "memory_key"
  >,
): Promise<number> {
  return forgetConsoleMemory(boundary, {
    responsibilityNamespace: record.responsibility_namespace,
    scope: record.scope,
    memoryKey: record.memory_key,
  });
}

export async function resolveConsoleMemoryCandidate(
  boundary: ConsolePreferenceBoundary,
  candidateId: string,
  resolution: "promote" | "reject",
): Promise<ConsoleMemoryCandidate> {
  const columns = boundaryColumns(boundary);
  const { data, error } = await client().rpc(
    "console_memory_resolve_current_user",
    {
      p_tenant_id: columns.tenant_id,
      p_organization_id: columns.organization_id,
      p_candidate_id: candidateId,
      p_resolution: resolution,
    },
  );
  if (error) throw error;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("MEMORY_CANDIDATE_RESOLUTION_INVALID");
  }
  return data as ConsoleMemoryCandidate;
}
