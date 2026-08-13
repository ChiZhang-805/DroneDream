import { hasExperimentDraft } from "./draftStorage";
import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type { AssistantWorkspaceIndexEntry } from "./assistantOrchestration";

const WORKSPACE_REGISTRY_PREFIX = "drone-dream:experiment-workspaces:v3:";
const V2_WORKSPACE_REGISTRY_PREFIX = "drone-dream:experiment-workspaces:v2:";
const LEGACY_WORKSPACE_REGISTRY_PREFIX = "drone-dream:experiment-workspaces:v1:";
const activeTenantContexts = new Map<string, AssistantTenantContext>();
export const EXPERIMENT_WORKSPACES_CHANGED_EVENT =
  "drone-dream:experiment-workspaces-changed";

export type ExperimentWorkspaceSource = "manual" | "assistant";
export type ExperimentWorkspaceStatus = "draft" | "created";
export type AssistantArtifactKind =
  | "universal_vehicle_model"
  | "universal_simulation_experiment"
  | "universal_cross_edition_workflow"
  | "simulation_experiment"
  | "lab_simulation_experiment"
  | "lab_hardware_validation"
  | "lab_calibration_workflow"
  | "lab_sim_to_real_workflow"
  | "lab_real_to_sim_workflow"
  | "field_task_plan";

export interface ExperimentWorkspace {
  id: string;
  ownerId: string;
  tenantId: string;
  organizationId: string | null;
  edition: BrandEditionId;
  name: string;
  source: ExperimentWorkspaceSource;
  status: ExperimentWorkspaceStatus;
  activeStep: number;
  completedSteps: number[];
  jobId: string | null;
  pinned: boolean;
  archived: boolean;
  assistantArtifactKind?: AssistantArtifactKind | null;
  vehicleDraftId?: string | null;
  order?: number;
  createdAt: string;
  updatedAt: string;
}

interface ExperimentWorkspaceRegistry {
  schemaVersion: 3;
  items: ExperimentWorkspace[];
}

interface RegisterWorkspaceInput {
  id: string;
  ownerId: string;
  tenantId?: string;
  organizationId?: string | null;
  edition: BrandEditionId;
  name: string;
  source: ExperimentWorkspaceSource;
  activeStep?: number;
  completedSteps?: number[];
  assistantArtifactKind?: AssistantArtifactKind | null;
  vehicleDraftId?: string | null;
}

type WorkspacePatch = Partial<
  Pick<
    ExperimentWorkspace,
    | "name"
    | "status"
    | "activeStep"
    | "completedSteps"
    | "jobId"
    | "pinned"
    | "archived"
    | "order"
  >
>;

function safePersistentStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalizeOwnerId(ownerId: string | null | undefined): string {
  const normalized = ownerId?.trim();
  return normalized && normalized.length <= 160 ? normalized : "local";
}

function registryKey(ownerId: string): string {
  return `${WORKSPACE_REGISTRY_PREFIX}${encodeURIComponent(normalizeOwnerId(ownerId))}`;
}

function v2RegistryKey(ownerId: string): string {
  return `${V2_WORKSPACE_REGISTRY_PREFIX}${encodeURIComponent(normalizeOwnerId(ownerId))}`;
}

function legacyRegistryKey(ownerId: string): string {
  return `${LEGACY_WORKSPACE_REGISTRY_PREFIX}${encodeURIComponent(normalizeOwnerId(ownerId))}`;
}

export interface AssistantTenantContext {
  tenantId: string;
  organizationId: string | null;
}

export function activeAssistantTenantContext(ownerId: string): AssistantTenantContext {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  return activeTenantContexts.get(normalizedOwnerId)
    ?? { tenantId: normalizedOwnerId, organizationId: null };
}

export function setActiveAssistantTenantContext(
  ownerId: string,
  context: AssistantTenantContext,
): void {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const tenantId = context.tenantId.trim();
  const organizationId = context.organizationId?.trim() || null;
  if (!tenantId || tenantId.length > 160 || (organizationId && organizationId.length > 160)) {
    throw new Error("The assistant tenant context is invalid.");
  }
  // This boundary is deliberately memory-only. A previous browser session may
  // not authorize a current organization after membership was revoked.
  activeTenantContexts.set(normalizedOwnerId, { tenantId, organizationId });
  emitRegistryChanged(normalizedOwnerId);
}

function isWorkspaceJobId(value: unknown): value is string {
  return typeof value === "string" &&
    /^[a-zA-Z0-9_-]{1,64}$/u.test(value);
}

function isBrandEditionId(value: unknown): value is BrandEditionId {
  return value === "universal" || value === "sim" || value === "lab" || value === "field";
}

function isAssistantArtifactKind(value: unknown): value is AssistantArtifactKind {
  return value === "universal_vehicle_model"
    || value === "universal_simulation_experiment"
    || value === "universal_cross_edition_workflow"
    || value === "simulation_experiment"
    || value === "lab_simulation_experiment"
    || value === "lab_hardware_validation"
    || value === "lab_calibration_workflow"
    || value === "lab_sim_to_real_workflow"
    || value === "lab_real_to_sim_workflow"
    || value === "field_task_plan";
}

function artifactMatchesEdition(
  edition: BrandEditionId,
  artifactKind: AssistantArtifactKind,
): boolean {
  if (edition === "universal") {
    return artifactKind === "universal_vehicle_model"
      || artifactKind === "universal_simulation_experiment"
      || artifactKind === "universal_cross_edition_workflow";
  }
  if (edition === "sim") return artifactKind === "simulation_experiment";
  if (edition === "field") return artifactKind === "field_task_plan";
  return artifactKind.startsWith("lab_");
}

function isWorkspace(value: unknown, ownerId: string): value is ExperimentWorkspace {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    /^[a-zA-Z0-9_-]{8,128}$/u.test(candidate.id) &&
    candidate.ownerId === ownerId &&
    typeof candidate.tenantId === "string" &&
    candidate.tenantId.length > 0 &&
    candidate.tenantId.length <= 160 &&
    (candidate.organizationId === null || typeof candidate.organizationId === "string") &&
    isBrandEditionId(candidate.edition) &&
    typeof candidate.name === "string" &&
    candidate.name.trim().length > 0 &&
    candidate.name.length <= 255 &&
    (candidate.source === "manual" || candidate.source === "assistant") &&
    (candidate.status === "draft" || candidate.status === "created") &&
    typeof candidate.activeStep === "number" &&
    Number.isInteger(candidate.activeStep) &&
    candidate.activeStep >= 0 &&
    candidate.activeStep <= 4 &&
    Array.isArray(candidate.completedSteps) &&
    candidate.completedSteps.every(
      (step) =>
        typeof step === "number" &&
        Number.isInteger(step) &&
        step >= 0 &&
        step <= 4,
    ) &&
    (candidate.jobId === null || isWorkspaceJobId(candidate.jobId)) &&
    typeof candidate.pinned === "boolean" &&
    typeof candidate.archived === "boolean" &&
    (
      candidate.assistantArtifactKind === undefined
      || candidate.assistantArtifactKind === null
      || (
        isAssistantArtifactKind(candidate.assistantArtifactKind)
        && artifactMatchesEdition(candidate.edition, candidate.assistantArtifactKind)
      )
    ) &&
    (
      candidate.vehicleDraftId === undefined
      || candidate.vehicleDraftId === null
      || (
        typeof candidate.vehicleDraftId === "string"
        && /^[a-zA-Z0-9_-]{8,128}$/u.test(candidate.vehicleDraftId)
        && candidate.edition === "universal"
        && candidate.assistantArtifactKind === "universal_vehicle_model"
      )
    ) &&
    (
      candidate.order === undefined
      || (
        typeof candidate.order === "number"
        && Number.isSafeInteger(candidate.order)
      )
    ) &&
    typeof candidate.createdAt === "string" &&
    Number.isFinite(Date.parse(candidate.createdAt)) &&
    typeof candidate.updatedAt === "string" &&
    Number.isFinite(Date.parse(candidate.updatedAt))
  );
}

function readRegistry(ownerId: string): ExperimentWorkspaceRegistry {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const storage = safePersistentStorage();
  if (!storage) return { schemaVersion: 3, items: [] };
  try {
    const raw = storage.getItem(registryKey(normalizedOwnerId));
    if (!raw) {
      const v2Raw = storage.getItem(v2RegistryKey(normalizedOwnerId));
      if (v2Raw) {
        const v2Parsed = JSON.parse(v2Raw) as unknown;
        if (v2Parsed && typeof v2Parsed === "object" && !Array.isArray(v2Parsed)) {
          const v2Candidate = v2Parsed as Record<string, unknown>;
          if (v2Candidate.schemaVersion === 2 && Array.isArray(v2Candidate.items)) {
            const migrated = v2Candidate.items.flatMap((item, index) => {
              if (!item || typeof item !== "object" || Array.isArray(item)) return [];
              const candidateItem = {
                ...item,
                tenantId: normalizedOwnerId,
                organizationId: null,
                order: (item as Record<string, unknown>).order ?? index,
              };
              return isWorkspace(candidateItem, normalizedOwnerId) ? [candidateItem] : [];
            });
            storage.setItem(
              registryKey(normalizedOwnerId),
              JSON.stringify({ schemaVersion: 3, items: migrated }),
            );
            storage.removeItem(v2RegistryKey(normalizedOwnerId));
            return { schemaVersion: 3, items: migrated };
          }
        }
      }
      const legacyRaw = storage.getItem(legacyRegistryKey(normalizedOwnerId));
      if (!legacyRaw) return { schemaVersion: 3, items: [] };
      const legacyParsed = JSON.parse(legacyRaw) as unknown;
      if (
        !legacyParsed
        || typeof legacyParsed !== "object"
        || Array.isArray(legacyParsed)
      ) {
        return { schemaVersion: 3, items: [] };
      }
      const legacyCandidate = legacyParsed as Record<string, unknown>;
      if (
        legacyCandidate.schemaVersion !== 1
        || !Array.isArray(legacyCandidate.items)
      ) {
        return { schemaVersion: 3, items: [] };
      }
      const migrated: ExperimentWorkspace[] = [];
      for (const [index, item] of legacyCandidate.items.entries()) {
        if (!item || typeof item !== "object" || Array.isArray(item)) continue;
        const candidateItem = {
          ...item,
          edition: "sim",
          tenantId: normalizedOwnerId,
          organizationId: null,
        };
        if (!isWorkspace(candidateItem, normalizedOwnerId)) continue;
        migrated.push({
          ...candidateItem,
          order: candidateItem.order ?? index,
        });
      }
      storage.setItem(
        registryKey(normalizedOwnerId),
        JSON.stringify({ schemaVersion: 3, items: migrated }),
      );
      storage.removeItem(legacyRegistryKey(normalizedOwnerId));
      return { schemaVersion: 3, items: migrated };
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { schemaVersion: 3, items: [] };
    }
    const candidate = parsed as Record<string, unknown>;
    if (candidate.schemaVersion !== 3 || !Array.isArray(candidate.items)) {
      return { schemaVersion: 3, items: [] };
    }
    const items = candidate.items.filter(
      (item) => isWorkspace(item, normalizedOwnerId),
    );
    return {
      schemaVersion: 3,
      items: items.map((item, index) => ({
        ...item,
        order: item.order ?? index,
      })),
    };
  } catch {
    return { schemaVersion: 3, items: [] };
  }
}

function emitRegistryChanged(ownerId: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(EXPERIMENT_WORKSPACES_CHANGED_EVENT, {
      detail: { ownerId: normalizeOwnerId(ownerId) },
    }),
  );
}

function writeRegistry(
  ownerId: string,
  items: ExperimentWorkspace[],
  emit = true,
): void {
  const storage = safePersistentStorage();
  if (!storage) return;
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  try {
    storage.setItem(
      registryKey(normalizedOwnerId),
      JSON.stringify({ schemaVersion: 3, items }),
    );
    if (emit) emitRegistryChanged(normalizedOwnerId);
  } catch {
    // The sidebar registry is optional; draft editing must still work.
  }
}

function normalizedName(name: string): string {
  const value = name.trim().replace(/\s+/gu, " ");
  return value.slice(0, 255) || "Untitled experiment";
}

function normalizedNameIdentity(name: string): string {
  return name
    .trim()
    .replace(/\s+/gu, " ")
    .normalize("NFKC")
    .toLowerCase();
}

function normalizedSteps(steps: number[]): number[] {
  return [...new Set(steps)]
    .filter((step) => Number.isInteger(step) && step >= 0 && step <= 4)
    .sort((left, right) => left - right);
}

export function createExperimentWorkspaceId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `experiment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function listExperimentWorkspaces(
  ownerId: string,
  edition: BrandEditionId,
): ExperimentWorkspace[] {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const registry = readRegistry(normalizedOwnerId);
  const retained = registry.items.filter(
    (workspace) =>
      workspace.status === "created" ||
      Boolean(workspace.jobId) ||
      hasExperimentDraft(workspace.id),
  );
  if (retained.length !== registry.items.length) {
    writeRegistry(normalizedOwnerId, retained, false);
  }
  return retained
    .filter((workspace) => {
      if (workspace.edition !== edition) return false;
      const activeTenant = activeAssistantTenantContext(normalizedOwnerId);
      return workspace.tenantId === activeTenant.tenantId
        && workspace.organizationId === activeTenant.organizationId;
    })
    .sort((left, right) => {
      if (left.pinned !== right.pinned) return left.pinned ? -1 : 1;
      if ((left.order ?? 0) !== (right.order ?? 0)) {
        return (left.order ?? 0) - (right.order ?? 0);
      }
      return Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
    });
}

export function isExperimentWorkspaceNameAvailable(
  ownerId: string,
  name: string,
  edition: BrandEditionId,
  excludeWorkspaceId?: string | null,
): boolean {
  const identity = normalizedNameIdentity(name);
  if (!identity) return false;
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  return !readRegistry(normalizedOwnerId).items.some(
    (workspace) =>
      !workspace.archived
      && workspace.edition === edition
      && workspace.id !== excludeWorkspaceId
      && normalizedNameIdentity(workspace.name) === identity,
  );
}

export function reorderExperimentWorkspaceItems(
  workspaces: ExperimentWorkspace[],
  draggedWorkspaceId: string,
  insertionIndex: number,
): ExperimentWorkspace[] {
  const dragged = workspaces.find(
    (workspace) => workspace.id === draggedWorkspaceId,
  );
  if (!dragged) return workspaces;
  const remaining = workspaces.filter(
    (workspace) => workspace.id !== draggedWorkspaceId,
  );
  const targetIndex = Math.min(
    remaining.length,
    Math.max(0, Math.trunc(insertionIndex)),
  );
  const remainingPinnedCount = remaining.filter(
    (workspace) => workspace.pinned,
  ).length;
  const nextPinned = dragged.pinned
    ? targetIndex <= remainingPinnedCount
    : remainingPinnedCount > 0 && targetIndex < remainingPinnedCount;
  const nextDragged = { ...dragged, pinned: nextPinned };
  const ordered = [...remaining];
  ordered.splice(targetIndex, 0, nextDragged);
  return ordered.map((workspace, order) => ({ ...workspace, order }));
}

export function reorderExperimentWorkspace(
  ownerId: string,
  draggedWorkspaceId: string,
  insertionIndex: number,
  edition: BrandEditionId,
): ExperimentWorkspace[] {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const visible = listExperimentWorkspaces(normalizedOwnerId, edition).filter(
    (workspace) => !workspace.archived,
  );
  const reordered = reorderExperimentWorkspaceItems(
    visible,
    draggedWorkspaceId,
    insertionIndex,
  );
  if (reordered === visible) return visible;
  const reorderedById = new Map(
    reordered.map((workspace) => [workspace.id, workspace]),
  );
  const now = new Date().toISOString();
  const registry = readRegistry(normalizedOwnerId);
  writeRegistry(
    normalizedOwnerId,
    registry.items.map((workspace) => {
      const next = reorderedById.get(workspace.id);
      if (!next) return workspace;
      return {
        ...workspace,
        pinned: next.pinned,
        order: next.order,
        ...(workspace.id === draggedWorkspaceId ? { updatedAt: now } : {}),
      };
    }),
  );
  return listExperimentWorkspaces(normalizedOwnerId, edition).filter(
    (workspace) => !workspace.archived,
  );
}

export function registerExperimentWorkspace(
  input: RegisterWorkspaceInput,
): ExperimentWorkspace {
  const ownerId = normalizeOwnerId(input.ownerId);
  const registry = readRegistry(ownerId);
  const now = new Date().toISOString();
  const existing = registry.items.find((item) => item.id === input.id);
  const activeTenant = activeAssistantTenantContext(ownerId);
  const tenantId = input.tenantId?.trim() || activeTenant.tenantId;
  const organizationId = input.organizationId === undefined
    ? activeTenant.organizationId
    : input.organizationId?.trim() || null;
  if (organizationId !== null && tenantId !== organizationId) {
    throw new Error("Organization workspaces must use their organization as tenant.");
  }
  if (organizationId === null && tenantId !== ownerId) {
    throw new Error("Personal workspaces must use their owner as tenant.");
  }
  if (existing && existing.edition !== input.edition) {
    throw new Error("Experiment workspaces cannot move between editions.");
  }
  if (
    existing
    && (existing.tenantId !== tenantId || existing.organizationId !== organizationId)
  ) {
    throw new Error("Experiment workspaces cannot move between tenants.");
  }
  if (
    input.assistantArtifactKind
    && !artifactMatchesEdition(input.edition, input.assistantArtifactKind)
  ) {
    throw new Error("Assistant artifacts cannot move between editions.");
  }
  if (
    input.vehicleDraftId
    && (
      input.edition !== "universal"
      || input.assistantArtifactKind !== "universal_vehicle_model"
      || !/^[a-zA-Z0-9_-]{8,128}$/u.test(input.vehicleDraftId)
    )
  ) {
    throw new Error("The vehicle draft link is invalid for this workspace.");
  }
  const firstOrder = registry.items.reduce(
    (minimum, item) => Math.min(minimum, item.order ?? 0),
    0,
  );
  const workspace: ExperimentWorkspace = {
    id: input.id,
    ownerId,
    tenantId,
    organizationId,
    edition: input.edition,
    name: normalizedName(input.name),
    source: input.source,
    status: existing?.status ?? "draft",
    activeStep: Math.min(4, Math.max(0, input.activeStep ?? existing?.activeStep ?? 0)),
    completedSteps: normalizedSteps(
      input.completedSteps ?? existing?.completedSteps ?? [],
    ),
    jobId: existing?.jobId ?? null,
    pinned: existing?.pinned ?? false,
    archived: existing?.archived ?? false,
    assistantArtifactKind: input.assistantArtifactKind === undefined
      ? existing?.assistantArtifactKind ?? null
      : input.assistantArtifactKind,
    vehicleDraftId: input.vehicleDraftId === undefined
      ? existing?.vehicleDraftId ?? null
      : input.vehicleDraftId,
    order: existing?.order ?? firstOrder - 1,
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
  };
  writeRegistry(ownerId, [
    workspace,
    ...registry.items.filter((item) => item.id !== input.id),
  ]);
  return workspace;
}

export function hydrateAssistantWorkspaceIndex(
  ownerId: string,
  entries: AssistantWorkspaceIndexEntry[],
): void {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const activeTenant = activeAssistantTenantContext(normalizedOwnerId);
  for (const entry of entries) {
    if (
      entry.tenant_id !== activeTenant.tenantId
      || entry.organization_id !== activeTenant.organizationId
      || !entry.latest_artifact
      || entry.latest_completed_sequence < 1
    ) {
      continue;
    }
    const workspace = registerExperimentWorkspace({
      id: entry.workspace_id,
      ownerId: normalizedOwnerId,
      tenantId: entry.tenant_id,
      organizationId: entry.organization_id,
      edition: entry.edition,
      name: entry.latest_artifact.title || entry.title,
      source: "assistant",
      activeStep: 1,
      completedSteps: [0],
      assistantArtifactKind: entry.latest_artifact.artifact_kind,
      vehicleDraftId: null,
    });
    updateExperimentWorkspace(normalizedOwnerId, workspace.id, {
      status: "created",
      archived: entry.status === "archived" || entry.latest_artifact.status === "archived",
    }, entry.edition);
  }
}

export function updateExperimentWorkspace(
  ownerId: string,
  workspaceId: string,
  patch: WorkspacePatch,
  edition: BrandEditionId,
): ExperimentWorkspace | null {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const registry = readRegistry(normalizedOwnerId);
  const current = registry.items.find((item) => item.id === workspaceId);
  if (!current || current.edition !== edition) return null;
  const updated: ExperimentWorkspace = {
    ...current,
    ...patch,
    ...(patch.name !== undefined ? { name: normalizedName(patch.name) } : {}),
    ...(patch.activeStep !== undefined
      ? { activeStep: Math.min(4, Math.max(0, patch.activeStep)) }
      : {}),
    ...(patch.completedSteps !== undefined
      ? { completedSteps: normalizedSteps(patch.completedSteps) }
      : {}),
    ...(patch.order !== undefined
      ? { order: Number.isSafeInteger(patch.order) ? patch.order : current.order }
      : {}),
    updatedAt: new Date().toISOString(),
  };
  writeRegistry(
    normalizedOwnerId,
    registry.items.map((item) => item.id === workspaceId ? updated : item),
  );
  return updated;
}

export function removeExperimentWorkspace(
  ownerId: string,
  workspaceId: string,
  edition: BrandEditionId,
): void {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const registry = readRegistry(normalizedOwnerId);
  writeRegistry(
    normalizedOwnerId,
    registry.items.filter(
      (item) => item.id !== workspaceId || item.edition !== edition,
    ),
  );
}

export function experimentWorkspacePath(workspace: ExperimentWorkspace): string {
  if (workspace.edition === "field") {
    return `/assistant?experiment=${encodeURIComponent(workspace.id)}`;
  }
  if (workspace.edition === "lab") {
    return `/assistant?experiment=${encodeURIComponent(workspace.id)}`;
  }
  if (workspace.edition === "universal") {
    if (
      workspace.assistantArtifactKind === "universal_vehicle_model"
      && workspace.vehicleDraftId
    ) {
      return `/vehicle-studio?draft=${encodeURIComponent(workspace.vehicleDraftId)}`;
    }
    if (workspace.source === "assistant" && !hasExperimentDraft(workspace.id)) {
      return `/assistant?experiment=${encodeURIComponent(workspace.id)}`;
    }
    return `/jobs/new?experiment=${encodeURIComponent(workspace.id)}`;
  }
  if (workspace.jobId) return `/jobs/${encodeURIComponent(workspace.jobId)}`;
  if (workspace.source === "assistant" && !hasExperimentDraft(workspace.id)) {
    return `/assistant?experiment=${encodeURIComponent(workspace.id)}`;
  }
  return `/jobs/new?experiment=${encodeURIComponent(workspace.id)}`;
}
