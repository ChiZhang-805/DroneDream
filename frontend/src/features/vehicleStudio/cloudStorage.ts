import type { BrandEditionId } from "../../brand/edition-brand.generated";
import { supabaseClient } from "../auth/supabaseClient";
import { migrateVehicleModelDraft, type VehicleModelDraft } from "./model";
import { assertVehicleModelShape } from "./pack";
import type { StoredVehicleModel } from "./storage";

const PERSONAL_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000000";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_MODELS = 50;
const MAX_REVISIONS = 40;
const CLOUD_PAGE_SIZE = 1_000;

export interface VehicleModelBoundary {
  userId: string;
  tenantId: string;
  organizationId: string | null;
  workspaceId: string;
  edition: Extract<BrandEditionId, "universal" | "autonomy">;
}

export function vehicleModelBoundaryFor(
  userId: string,
  tenantId: string,
  organizationId: string | null,
  edition: VehicleModelBoundary["edition"] = "universal",
): VehicleModelBoundary | null {
  const boundary: VehicleModelBoundary = {
    userId,
    tenantId,
    organizationId,
    workspaceId: `console-${edition}`,
    edition,
  };
  try {
    cloudBoundary(boundary);
    return boundary;
  } catch {
    return null;
  }
}

interface VehicleModelRevisionRow {
  draft_id: string;
  revision: number;
  model: unknown;
}

function cloudBoundary(boundary: VehicleModelBoundary) {
  if (
    !UUID_PATTERN.test(boundary.userId)
    || !UUID_PATTERN.test(boundary.tenantId)
    || (boundary.organizationId !== null && !UUID_PATTERN.test(boundary.organizationId))
    || !(
      (boundary.edition === "universal" && boundary.workspaceId === "console-universal")
      || (boundary.edition === "autonomy" && boundary.workspaceId === "console-autonomy")
    )
  ) {
    throw new Error("The vehicle-model tenant boundary is invalid.");
  }
  return {
    user_id: boundary.userId,
    tenant_id: boundary.tenantId,
    organization_id: boundary.organizationId ?? PERSONAL_ORGANIZATION_ID,
    workspace_id: boundary.workspaceId,
    edition: boundary.edition,
  };
}

function client() {
  return supabaseClient;
}

export function vehicleModelCloudAvailable(): boolean {
  return client() !== null;
}

export async function loadCloudVehicleModels(
  boundary: VehicleModelBoundary,
): Promise<StoredVehicleModel[] | null> {
  const database = client();
  if (!database) return null;
  const columns = cloudBoundary(boundary);
  const rows: VehicleModelRevisionRow[] = [];
  for (let offset = 0; ; offset += CLOUD_PAGE_SIZE) {
    const { data, error } = await database.from("vehicle_model_revisions")
      .select("draft_id,revision,model")
      .eq("user_id", columns.user_id)
      .eq("tenant_id", columns.tenant_id)
      .eq("organization_id", columns.organization_id)
      .eq("workspace_id", columns.workspace_id)
      .eq("edition", columns.edition)
      .order("updated_at", { ascending: false })
      .order("draft_id", { ascending: true })
      .order("revision", { ascending: false })
      .range(offset, offset + CLOUD_PAGE_SIZE - 1);
    if (error) throw error;
    const page = (data ?? []) as VehicleModelRevisionRow[];
    rows.push(...page);
    if (page.length < CLOUD_PAGE_SIZE) break;
  }

  const grouped = new Map<string, VehicleModelDraft[]>();
  for (const row of rows) {
    if (typeof row.draft_id !== "string" || !Number.isInteger(row.revision)) continue;
    try {
      const revision = migrateVehicleModelDraft(row.model);
      assertVehicleModelShape(revision);
      if (revision.draftId !== row.draft_id || revision.revision !== row.revision) continue;
      const revisions = grouped.get(row.draft_id) ?? [];
      if (!revisions.some((candidate) => candidate.revision === revision.revision)) {
        revisions.push(revision);
        grouped.set(row.draft_id, revisions);
      }
    } catch {
      // A malformed cloud row is isolated instead of making every valid model
      // unavailable. The server-side envelope checks prevent new malformed rows.
    }
  }
  return [...grouped.entries()]
    .map(([draftId, revisions]) => ({
      draftId,
      revisions: revisions
        .sort((left, right) => right.revision - left.revision)
        .slice(0, MAX_REVISIONS),
    }))
    .sort((left, right) => Date.parse(right.revisions[0].updatedAt) - Date.parse(left.revisions[0].updatedAt))
    .slice(0, MAX_MODELS);
}

export async function saveCloudVehicleModel(
  boundary: VehicleModelBoundary,
  draft: VehicleModelDraft,
): Promise<boolean> {
  const database = client();
  if (!database) return false;
  assertVehicleModelShape(draft);
  const columns = cloudBoundary(boundary);
  const { error } = await database.from("vehicle_model_revisions").insert({
    ...columns,
    draft_id: draft.draftId,
    revision: draft.revision,
    model: draft,
    updated_at: draft.updatedAt,
  });
  if (error?.code === "23505") {
    throw new Error(`Vehicle-model revision ${draft.revision} already exists and cannot be overwritten.`);
  }
  if (error) throw error;
  return true;
}

export async function deleteCloudVehicleModel(
  boundary: VehicleModelBoundary,
  draftId: string,
): Promise<boolean> {
  const database = client();
  if (!database) return false;
  const columns = cloudBoundary(boundary);
  const { error } = await database.from("vehicle_model_revisions")
    .delete()
    .eq("user_id", columns.user_id)
    .eq("tenant_id", columns.tenant_id)
    .eq("organization_id", columns.organization_id)
    .eq("workspace_id", columns.workspace_id)
    .eq("edition", columns.edition)
    .eq("draft_id", draftId);
  if (error) throw error;
  return true;
}

export function mergeVehicleModelStores(
  localModels: StoredVehicleModel[],
  cloudModels: StoredVehicleModel[],
): StoredVehicleModel[] {
  const merged = new Map<string, Map<number, VehicleModelDraft>>();
  for (const model of [...cloudModels, ...localModels]) {
    const revisions = merged.get(model.draftId) ?? new Map<number, VehicleModelDraft>();
    for (const revision of model.revisions) {
      const current = revisions.get(revision.revision);
      if (!current || Date.parse(revision.updatedAt) >= Date.parse(current.updatedAt)) {
        revisions.set(revision.revision, structuredClone(revision));
      }
    }
    merged.set(model.draftId, revisions);
  }
  return [...merged.entries()]
    .map(([draftId, revisions]) => ({
      draftId,
      revisions: [...revisions.values()]
        .sort((left, right) => right.revision - left.revision)
        .slice(0, MAX_REVISIONS),
    }))
    .filter((model) => model.revisions.length > 0)
    .sort((left, right) => Date.parse(right.revisions[0].updatedAt) - Date.parse(left.revisions[0].updatedAt))
    .slice(0, MAX_MODELS);
}
