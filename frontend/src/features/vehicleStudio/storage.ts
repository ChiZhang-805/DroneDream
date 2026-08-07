import type { VehicleModelDraft } from "./model";
import { assertVehicleModelShape } from "./pack";

const STORAGE_PREFIX = "dronedream:vehicle-studio:v1";
const MAX_REVISIONS = 40;

export interface StoredVehicleModel {
  draftId: string;
  revisions: VehicleModelDraft[];
}

function storageKey(ownerId: string): string {
  return `${STORAGE_PREFIX}:${ownerId || "local"}`;
}

export function loadVehicleModels(
  ownerId: string,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): StoredVehicleModel[] {
  try {
    const value = JSON.parse(storage.getItem(storageKey(ownerId)) ?? "[]") as unknown;
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is StoredVehicleModel => {
      if (!item || typeof item !== "object") return false;
      const record = item as Partial<StoredVehicleModel>;
      if (
        typeof record.draftId !== "string"
        || !Array.isArray(record.revisions)
        || record.revisions.length === 0
      ) return false;
      try {
        for (const revision of record.revisions) assertVehicleModelShape(revision);
        return record.revisions.every((revision) => revision.draftId === record.draftId);
      } catch {
        return false;
      }
    });
  } catch {
    return [];
  }
}

export function saveVehicleModel(
  ownerId: string,
  draft: VehicleModelDraft,
  storage: Pick<Storage, "getItem" | "setItem"> = window.localStorage,
): StoredVehicleModel[] {
  const models = loadVehicleModels(ownerId, storage);
  const index = models.findIndex((model) => model.draftId === draft.draftId);
  const current = index >= 0 ? models[index] : { draftId: draft.draftId, revisions: [] };
  const revisions = [draft, ...current.revisions.filter((item) => item.revision !== draft.revision)]
    .sort((left, right) => right.revision - left.revision)
    .slice(0, MAX_REVISIONS);
  const next = { draftId: draft.draftId, revisions };
  if (index >= 0) models[index] = next;
  else models.unshift(next);
  storage.setItem(storageKey(ownerId), JSON.stringify(models));
  return models;
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
