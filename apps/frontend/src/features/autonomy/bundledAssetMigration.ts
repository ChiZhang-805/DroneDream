import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type { AgentCoreBootstrap, AgentCoreBundledAssetMigration } from "./agentCore";
import { forgetAgentCoreThreadBinding, resolveAgentCoreAssetPair } from "./agentCorePlanning";
import { bindVerifiedAssetPair } from "./assetPairBinding";
import { readStoredAutonomyAssetLibrary, saveAutonomyAssetLibrary, type AutonomyAssetLibrary } from "./assetLibraryStore";
import { migrateAutonomyConversations } from "./conversationStore";
import { defaultAutonomyWorkspace, loadAutonomyWorkspace, saveAutonomyWorkspace, type AutonomyWorkspaceState } from "./workspaceStore";

type MigrationStorage = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;
type VerifiedReplacement = {
  record: AgentCoreBundledAssetMigration;
  binding: NonNullable<ReturnType<typeof bindVerifiedAssetPair>>;
};

function migrationKey(kind: string, id: string | null | undefined, hash: string | null | undefined): string {
  return JSON.stringify([kind === "world" ? "map" : kind, id ?? null, hash ?? null]);
}

function validateRecord(record: AgentCoreBundledAssetMigration): void {
  const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/u.test(value);
  if (!record || record.schema_version !== "dronedream.bundled-asset-migration.v1"
    || !["map", "vehicle"].includes(record.kind)
    || ![record.asset_id, record.map_asset_id, record.vehicle_asset_id].every((id) => typeof id === "string" && id.length > 0)
    || ![record.from_content_sha256, record.to_content_sha256, record.index_sha256, record.receipt_sha256,
      record.map_content_sha256, record.vehicle_content_sha256].every(hash)
    || !/^asset-qualification-[0-9a-f]{24}$/u.test(record.qualification_id)
    || record.from_content_sha256 === record.to_content_sha256
    || record.asset_id !== (record.kind === "map" ? record.map_asset_id : record.vehicle_asset_id)
    || record.to_content_sha256 !== (record.kind === "map" ? record.map_content_sha256 : record.vehicle_content_sha256)) {
    throw new Error("AGENT_CORE_BUNDLED_MIGRATION_INVALID");
  }
}

/** Only Core's packaged supersedes records authorize a pin change; never choose latest. */
export async function prepareBundledAssetMigration(bootstrap: AgentCoreBootstrap) {
  const replacements = new Map<string, VerifiedReplacement>();
  const pairs = new Map<string, VerifiedReplacement["binding"]>();
  for (const record of bootstrap.bundled_asset_migrations ?? []) {
    validateRecord(record);
    const key = migrationKey(record.kind, record.asset_id, record.from_content_sha256);
    const pairKey = JSON.stringify([record.map_asset_id, record.map_content_sha256, record.vehicle_asset_id,
      record.vehicle_content_sha256, record.qualification_id, record.receipt_sha256]);
    const previous = replacements.get(key);
    if (previous && JSON.stringify(previous.record) !== JSON.stringify(record)) {
      throw new Error("AGENT_CORE_BUNDLED_MIGRATION_CONFLICT");
    }
    let binding = pairs.get(pairKey);
    if (!binding) {
      const target = defaultAutonomyWorkspace();
      target.mapPack = { ...target.mapPack, agentCoreAssetId: record.map_asset_id,
        agentCoreContentSha256: record.map_content_sha256, qualificationReceiptId: record.qualification_id };
      target.aircraft = { ...target.aircraft, agentCoreAssetId: record.vehicle_asset_id,
        agentCoreContentSha256: record.vehicle_content_sha256, qualificationReceiptId: record.qualification_id };
      const pair = await resolveAgentCoreAssetPair(target, bootstrap);
      if (pair.job.qualification_id !== record.qualification_id || pair.evidence.evidence_sha256 !== record.receipt_sha256) {
        throw new Error("AGENT_CORE_BUNDLED_MIGRATION_EVIDENCE_MISMATCH");
      }
      binding = bindVerifiedAssetPair(target, { schemaVersion: 2, aircraft: [], maps: [], externalAssets: [] },
        pair.job, pair.mapVersion, pair.vehicleVersion, pair.evidence.runtime_contracts) ?? undefined;
      if (!binding) throw new Error("AGENT_CORE_BUNDLED_MIGRATION_BINDING_INVALID");
      pairs.set(pairKey, binding);
    }
    replacements.set(key, { record, binding });
  }

  const aircraft = (previous: AutonomyWorkspaceState["aircraft"]) => {
    const replacement = replacements.get(migrationKey("vehicle", previous.agentCoreAssetId, previous.agentCoreContentSha256));
    return replacement ? { ...replacement.binding.workspace.aircraft, id: previous.id } : previous;
  };
  const mapPack = (previous: AutonomyWorkspaceState["mapPack"]) => {
    const replacement = replacements.get(migrationKey("map", previous.agentCoreAssetId, previous.agentCoreContentSha256));
    return replacement ? { ...replacement.binding.workspace.mapPack, id: previous.id } : previous;
  };
  return {
    hasReplacements: replacements.size > 0,
    workspace(previous: AutonomyWorkspaceState): AutonomyWorkspaceState {
      const nextAircraft = aircraft(previous.aircraft);
      const nextMap = mapPack(previous.mapPack);
      if (nextAircraft === previous.aircraft && nextMap === previous.mapPack) return previous;
      // Keep the conversation and completed evidence; revoke every executable old-plan hint.
      const messages = previous.mission.messages.map((message) => ({ ...message, planContractId: null }));
      if (!messages.length && previous.mission.compiledPlan) messages.push({
        id: crypto.randomUUID(), role: "user", content: previous.mission.intent,
        createdAt: previous.mission.updatedAt, planContractId: null,
      });
      return { ...previous, aircraft: nextAircraft, mapPack: nextMap, mission: {
        ...previous.mission, compiledPlan: null, planningRunId: null, planningBrief: "", planningError: null,
        mapRefinement: null, currentStep: 0, messages,
        aircraftProfileId: nextAircraft.id, mapPackId: nextMap.id,
      } };
    },
    library(previous: AutonomyAssetLibrary): AutonomyAssetLibrary {
      const nextAircraft = previous.aircraft.map(aircraft);
      const nextMaps = previous.maps.map(mapPack);
      const externalAssets = previous.externalAssets.map((asset) => {
        const replacement = replacements.get(migrationKey(asset.kind, asset.id, asset.contentSha256));
        if (!replacement) return asset;
        return replacement.record.kind === "map" ? replacement.binding.mapAsset : replacement.binding.vehicleAsset;
      });
      if (nextAircraft.every((value, i) => value === previous.aircraft[i])
        && nextMaps.every((value, i) => value === previous.maps[i])
        && externalAssets.every((value, i) => value === previous.externalAssets[i])) return previous;
      return { schemaVersion: 2, aircraft: nextAircraft, maps: nextMaps, externalAssets };
    },
  };
}

/** Run before rendering any task or Live route; all writes are idempotent on reload. */
export function migrateStoredBundledAssets(
  ownerId: string,
  edition: BrandEditionId,
  migration: Awaited<ReturnType<typeof prepareBundledAssetMigration>>,
  storage: MigrationStorage = window.localStorage,
): void {
  if (!migration.hasReplacements) return;
  const migrateWorkspace = (previous: AutonomyWorkspaceState) => {
    const next = migration.workspace(previous);
    if (next !== previous && previous.mission.conversationId) {
      // Delete the execution lookup before committing the new asset hashes, also on retry.
      forgetAgentCoreThreadBinding({ accountId: ownerId, edition, conversationId: previous.mission.conversationId }, storage);
    }
    return next;
  };
  migrateAutonomyConversations(ownerId, edition, migrateWorkspace, storage);
  const previous = loadAutonomyWorkspace(ownerId, edition, storage);
  const next = migrateWorkspace(previous);
  const library = readStoredAutonomyAssetLibrary(ownerId, edition, storage);
  const nextLibrary = migration.library(library);
  if (nextLibrary !== library) saveAutonomyAssetLibrary(ownerId, edition, nextLibrary, storage);
  if (next !== previous) saveAutonomyWorkspace(ownerId, edition, next, storage);
}
