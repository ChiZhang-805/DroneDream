import { hasExperimentDraft } from "./draftStorage";

const WORKSPACE_REGISTRY_PREFIX = "drone-dream:experiment-workspaces:v1:";
export const EXPERIMENT_WORKSPACES_CHANGED_EVENT =
  "drone-dream:experiment-workspaces-changed";

export type ExperimentWorkspaceSource = "manual" | "assistant";
export type ExperimentWorkspaceStatus = "draft" | "created";

export interface ExperimentWorkspace {
  id: string;
  ownerId: string;
  name: string;
  source: ExperimentWorkspaceSource;
  status: ExperimentWorkspaceStatus;
  activeStep: number;
  completedSteps: number[];
  jobId: string | null;
  pinned: boolean;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
}

interface ExperimentWorkspaceRegistry {
  schemaVersion: 1;
  items: ExperimentWorkspace[];
}

interface RegisterWorkspaceInput {
  id: string;
  ownerId: string;
  name: string;
  source: ExperimentWorkspaceSource;
  activeStep?: number;
  completedSteps?: number[];
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

function isWorkspace(value: unknown, ownerId: string): value is ExperimentWorkspace {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    /^[a-zA-Z0-9_-]{8,128}$/u.test(candidate.id) &&
    candidate.ownerId === ownerId &&
    typeof candidate.name === "string" &&
    candidate.name.trim().length > 0 &&
    (candidate.source === "manual" || candidate.source === "assistant") &&
    (candidate.status === "draft" || candidate.status === "created") &&
    typeof candidate.activeStep === "number" &&
    Number.isInteger(candidate.activeStep) &&
    candidate.activeStep >= 0 &&
    candidate.activeStep <= 4 &&
    Array.isArray(candidate.completedSteps) &&
    (candidate.jobId === null || typeof candidate.jobId === "string") &&
    typeof candidate.pinned === "boolean" &&
    typeof candidate.archived === "boolean" &&
    typeof candidate.createdAt === "string" &&
    Number.isFinite(Date.parse(candidate.createdAt)) &&
    typeof candidate.updatedAt === "string" &&
    Number.isFinite(Date.parse(candidate.updatedAt))
  );
}

function readRegistry(ownerId: string): ExperimentWorkspaceRegistry {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const storage = safePersistentStorage();
  if (!storage) return { schemaVersion: 1, items: [] };
  try {
    const raw = storage.getItem(registryKey(normalizedOwnerId));
    if (!raw) return { schemaVersion: 1, items: [] };
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { schemaVersion: 1, items: [] };
    }
    const candidate = parsed as Record<string, unknown>;
    if (candidate.schemaVersion !== 1 || !Array.isArray(candidate.items)) {
      return { schemaVersion: 1, items: [] };
    }
    return {
      schemaVersion: 1,
      items: candidate.items.filter((item) => isWorkspace(item, normalizedOwnerId)),
    };
  } catch {
    return { schemaVersion: 1, items: [] };
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
      JSON.stringify({ schemaVersion: 1, items }),
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

export function listExperimentWorkspaces(ownerId: string): ExperimentWorkspace[] {
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
  return retained.sort((left, right) => {
    if (left.pinned !== right.pinned) return left.pinned ? -1 : 1;
    return Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
  });
}

export function registerExperimentWorkspace(
  input: RegisterWorkspaceInput,
): ExperimentWorkspace {
  const ownerId = normalizeOwnerId(input.ownerId);
  const registry = readRegistry(ownerId);
  const now = new Date().toISOString();
  const existing = registry.items.find((item) => item.id === input.id);
  const workspace: ExperimentWorkspace = {
    id: input.id,
    ownerId,
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
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
  };
  writeRegistry(ownerId, [
    workspace,
    ...registry.items.filter((item) => item.id !== input.id),
  ]);
  return workspace;
}

export function updateExperimentWorkspace(
  ownerId: string,
  workspaceId: string,
  patch: WorkspacePatch,
): ExperimentWorkspace | null {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const registry = readRegistry(normalizedOwnerId);
  const current = registry.items.find((item) => item.id === workspaceId);
  if (!current) return null;
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
): void {
  const normalizedOwnerId = normalizeOwnerId(ownerId);
  const registry = readRegistry(normalizedOwnerId);
  writeRegistry(
    normalizedOwnerId,
    registry.items.filter((item) => item.id !== workspaceId),
  );
}

export function experimentWorkspacePath(workspace: ExperimentWorkspace): string {
  if (workspace.jobId) return `/jobs/${workspace.jobId}`;
  return `/jobs/new?experiment=${encodeURIComponent(workspace.id)}`;
}
