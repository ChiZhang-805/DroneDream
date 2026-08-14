import type { VehicleModelDraft } from "./model";
import { migrateVehicleModelDraft } from "./model";
import { assertVehicleModelShape } from "./pack";

const STORAGE_PREFIX = "dronedream:vehicle-studio:v1";
const MAX_REVISIONS = 40;
const MAX_MODELS = 50;

export interface StoredVehicleModel {
  draftId: string;
  revisions: VehicleModelDraft[];
}

export interface VehicleModelLocalBoundary {
  userId: string;
  tenantId: string;
  organizationId: string | null;
  workspaceId: string;
  edition: string;
}

export function vehicleModelStorageScope(boundary: VehicleModelLocalBoundary): string {
  return [
    boundary.userId || "local",
    boundary.tenantId || "personal",
    boundary.organizationId || "personal",
    boundary.workspaceId || "console-universal",
    boundary.edition || "universal",
  ].map((part) => encodeURIComponent(part)).join(":");
}

function storageKey(storageScope: string): string {
  return `${STORAGE_PREFIX}:${storageScope || "local"}`;
}

type VehicleModelReadableStorage = Pick<Storage, "getItem"> & Partial<Pick<Storage, "setItem" | "removeItem">>;

function legacyPersonalStorageKey(storageScope: string): string | null {
  const encodedParts = storageScope.split(":");
  if (encodedParts.length !== 5) return null;
  try {
    const [userId, tenantId, organizationId, workspaceId, edition] = encodedParts.map((part) => decodeURIComponent(part));
    if (
      !userId
      || tenantId !== userId
      || organizationId !== "personal"
      || workspaceId !== "console-universal"
      || edition !== "universal"
    ) return null;
    return storageKey(userId);
  } catch {
    return null;
  }
}

function readVehicleModelStorageValue(storageScope: string, storage: VehicleModelReadableStorage): string | null {
  const currentKey = storageKey(storageScope);
  const current = storage.getItem(currentKey);
  if (current !== null) return current;
  const legacyKey = legacyPersonalStorageKey(storageScope);
  if (!legacyKey) return null;
  const legacy = storage.getItem(legacyKey);
  if (legacy === null) return null;
  if (storage.setItem) {
    storage.setItem(currentKey, legacy);
    if (storage.getItem(currentKey) === legacy) storage.removeItem?.(legacyKey);
  }
  return legacy;
}

export function loadVehicleModels(
  ownerId: string,
  storage: VehicleModelReadableStorage = window.localStorage,
): StoredVehicleModel[] {
  try {
    const value = JSON.parse(readVehicleModelStorageValue(ownerId, storage) ?? "[]") as unknown;
    if (!Array.isArray(value)) return [];
    const loaded: StoredVehicleModel[] = [];
    for (const item of value.slice(0, MAX_MODELS)) {
      if (!item || typeof item !== "object") continue;
      const record = item as Partial<StoredVehicleModel>;
      if (
        typeof record.draftId !== "string"
        || !Array.isArray(record.revisions)
        || record.revisions.length === 0
      ) continue;
      try {
        const revisions = record.revisions
          .slice(0, MAX_REVISIONS)
          .map((revision) => migrateVehicleModelDraft(revision));
        for (const revision of revisions) assertVehicleModelShape(revision);
        if (!revisions.every((revision) => revision.draftId === record.draftId)) continue;
        if (new Set(revisions.map((revision) => revision.revision)).size !== revisions.length) continue;
        loaded.push({
          draftId: record.draftId,
          revisions: [...revisions].sort((left, right) => right.revision - left.revision),
        });
      } catch {
        continue;
      }
    }
    return loaded;
  } catch {
    return [];
  }
}

export function saveVehicleModel(
  ownerId: string,
  draft: VehicleModelDraft,
  storage: Pick<Storage, "getItem" | "setItem"> = window.localStorage,
): StoredVehicleModel[] {
  assertVehicleModelShape(draft);
  const models = loadVehicleModels(ownerId, storage);
  const index = models.findIndex((model) => model.draftId === draft.draftId);
  const current = index >= 0 ? models[index] : { draftId: draft.draftId, revisions: [] };
  const revisions = [structuredClone(draft), ...current.revisions.filter((item) => item.revision !== draft.revision)]
    .sort((left, right) => right.revision - left.revision)
    .slice(0, MAX_REVISIONS);
  const next = { draftId: draft.draftId, revisions };
  if (index >= 0) models[index] = next;
  else models.unshift(next);
  models.splice(MAX_MODELS);
  storage.setItem(storageKey(ownerId), JSON.stringify(models));
  return models;
}

export function cacheVehicleModels(
  ownerId: string,
  models: StoredVehicleModel[],
  storage: Pick<Storage, "setItem"> = window.localStorage,
): StoredVehicleModel[] {
  const retained = models.slice(0, MAX_MODELS).map((model) => ({
    draftId: model.draftId,
    revisions: model.revisions.slice(0, MAX_REVISIONS).map((revision) => {
      assertVehicleModelShape(revision);
      if (revision.draftId !== model.draftId) {
        throw new Error("A cached vehicle-model revision crossed its draft boundary.");
      }
      return structuredClone(revision);
    }),
  })).filter((model) => model.revisions.length > 0);
  storage.setItem(storageKey(ownerId), JSON.stringify(retained));
  return retained;
}

export function removeVehicleModel(
  ownerId: string,
  draftId: string,
  storage: Pick<Storage, "getItem" | "setItem"> = window.localStorage,
): StoredVehicleModel[] {
  const next = loadVehicleModels(ownerId, storage)
    .filter((model) => model.draftId !== draftId);
  storage.setItem(storageKey(ownerId), JSON.stringify(next));
  return next;
}

export function nextVehicleRevision(
  draft: VehicleModelDraft,
  now = new Date(),
): VehicleModelDraft {
  return {
    ...structuredClone(draft),
    revision: draft.revision + 1,
    updatedAt: now.toISOString(),
  };
}

export function restoreVehicleRevision(
  historical: VehicleModelDraft,
  latestRevision: number,
  now = new Date(),
): VehicleModelDraft {
  return {
    ...structuredClone(historical),
    revision: latestRevision + 1,
    updatedAt: now.toISOString(),
  };
}
