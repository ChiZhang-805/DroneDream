import { beforeEach, describe, expect, it, vi } from "vitest";
import * as core from "../features/autonomy/agentCore";
import { getBoundAgentCoreThread, resolveAgentCoreAssetPair } from "../features/autonomy/agentCorePlanning";
import { loadAutonomyAssetLibrary, saveAutonomyAssetLibrary } from "../features/autonomy/assetLibraryStore";
import { migrateStoredBundledAssets, prepareBundledAssetMigration } from "../features/autonomy/bundledAssetMigration";
import { deleteAutonomyConversation, listAutonomyConversations, loadAutonomyConversation, saveAutonomyConversation, setAutonomyConversationPinned } from "../features/autonomy/conversationStore";
import { defaultAutonomyWorkspace, loadAutonomyWorkspace, normalizeAutonomyWorkspace, saveAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import sample from "./fixtures/qualifiedAssetPair.json";

// Protocol fixtures exercise an upgrade; they are not evidence of a new flight.
const OLD_MAP = "a".repeat(64);
const OLDER_MAP = "b".repeat(64);
const OLD_VEHICLE = "c".repeat(64);
let bootstrap: core.AgentCoreBootstrap;
let evidence: core.AgentCoreAssetQualificationEvidence;

function record(kind: "map" | "vehicle", oldHash: string): core.AgentCoreBundledAssetMigration {
  return {
    schema_version: "dronedream.bundled-asset-migration.v1", kind,
    asset_id: kind === "map" ? sample.job.map_asset_id : sample.job.vehicle_asset_id,
    from_content_sha256: oldHash,
    to_content_sha256: kind === "map" ? sample.job.result_map_content_sha256 : sample.job.result_vehicle_content_sha256,
    index_sha256: "d".repeat(64), receipt_sha256: sample.evidence.evidence_sha256,
    qualification_id: sample.job.qualification_id,
    map_asset_id: sample.job.map_asset_id, map_content_sha256: sample.job.result_map_content_sha256,
    vehicle_asset_id: sample.job.vehicle_asset_id, vehicle_content_sha256: sample.job.result_vehicle_content_sha256,
  };
}

function oldWorkspace(id = "saved", hash = OLD_MAP) {
  const workspace = defaultAutonomyWorkspace();
  workspace.mapPack.agentCoreContentSha256 = hash;
  workspace.aircraft.agentCoreContentSha256 = OLD_VEHICLE;
  return normalizeAutonomyWorkspace({ ...workspace, mission: {
    ...workspace.mission, conversationId: id, intent: "Bring the chemistry sample home.",
    planningRunId: "old-run", planningBrief: "Old plan", currentStep: 4,
    messages: [{ id: `${id}-user`, role: "user", content: "Bring the chemistry sample home.",
      createdAt: "2026-10-01T00:00:00.000Z", planContractId: "old-plan" }],
    compiledPlan: { source: "agent-core", contractId: "old-plan", canExecute: true, readiness: "simulation_ready",
      taskGraph: { nodes: [{ task_id: "old-takeoff", label: "Takeoff", status: "ready", executor: "px4_bridge",
        risk: "low", fallback: "land", inserted_by: "compiler", depends_on: [] }] } },
  } });
}

beforeEach(() => {
  localStorage.clear();
  evidence = structuredClone(sample.evidence) as core.AgentCoreAssetQualificationEvidence;
  bootstrap = {
    asset_versions: structuredClone(sample.versions), asset_qualification_jobs: [structuredClone(sample.job)],
    bundled_asset_migrations: [record("map", OLD_MAP), record("map", OLDER_MAP), record("vehicle", OLD_VEHICLE)],
  } as unknown as core.AgentCoreBootstrap;
  vi.spyOn(core, "getAgentCoreBootstrap").mockImplementation(async () => bootstrap);
  vi.spyOn(core, "getAgentCoreAssetQualificationEvidence").mockImplementation(async () => evidence);
});

describe("trusted bundled asset upgrades", () => {
  it.each(["universal", "autonomy"] as const)("migrates %s caches across generations and revokes old executable plans", async (edition) => {
    const previous = oldWorkspace();
    expect(previous.mission.compiledPlan?.canExecute).toBe(true);
    saveAutonomyWorkspace("owner", edition, previous);
    saveAutonomyConversation("owner", edition, previous);
    saveAutonomyConversation("owner", edition, oldWorkspace("older", OLDER_MAP));
    setAutonomyConversationPinned("owner", edition, "older", true);
    saveAutonomyAssetLibrary("owner", edition, { schemaVersion: 2,
      aircraft: [previous.aircraft], maps: [previous.mapPack], externalAssets: [] });
    localStorage.setItem(`dronedream:agent-core-thread:v1:owner:${edition}:saved`, "old-core-thread");
    const untouchedEdition = edition === "universal" ? "autonomy" : "universal";
    saveAutonomyWorkspace("owner", untouchedEdition, previous);
    saveAutonomyWorkspace("other-owner", edition, previous);

    const migration = await prepareBundledAssetMigration(bootstrap);
    migrateStoredBundledAssets("owner", edition, migration);
    const next = loadAutonomyWorkspace("owner", edition);
    expect(next.mapPack.agentCoreContentSha256).toBe(sample.job.result_map_content_sha256);
    expect(next.aircraft.agentCoreContentSha256).toBe(sample.job.result_vehicle_content_sha256);
    expect(next.mapPack.agentCoreRuntimeContract?.nodeCount).toBe(evidence.runtime_contracts.map.node_count);
    expect(next.mapPack.sourceFiles.map((source) => source.sha256)).toEqual([sample.job.result_map_content_sha256]);
    expect(next.mission).toMatchObject({ compiledPlan: null, planningRunId: null, planningBrief: "", currentStep: 0 });
    expect(next.mission.messages[0]).toMatchObject({ content: previous.mission.intent, planContractId: null });
    expect(next.mapPack.id).toBe(previous.mapPack.id);
    expect(await getBoundAgentCoreThread({ accountId: "owner", edition, conversationId: "saved" })).toBeNull();
    const history = loadAutonomyConversation("owner", edition, "older")!;
    expect(history.mapPack.agentCoreContentSha256).toBe(sample.job.result_map_content_sha256);
    expect(history.mission.compiledPlan).toBeNull();
    expect(listAutonomyConversations("owner", edition)[0]).toMatchObject({ id: "older", pinned: true });
    expect(loadAutonomyAssetLibrary("owner", edition, next).maps[0].agentCoreContentSha256).toBe(sample.job.result_map_content_sha256);
    expect(loadAutonomyWorkspace("owner", untouchedEdition).mapPack.agentCoreContentSha256).toBe(OLD_MAP);
    expect(loadAutonomyWorkspace("other-owner", edition).mapPack.agentCoreContentSha256).toBe(OLD_MAP);
    expect((await resolveAgentCoreAssetPair(next)).job.qualification_id).toBe(sample.job.qualification_id);
    expect(core.getAgentCoreAssetQualificationEvidence).toHaveBeenCalledTimes(2); // Once per pair, then the planning check.

    const writes = vi.spyOn(Storage.prototype, "setItem");
    migrateStoredBundledAssets("owner", edition, await prepareBundledAssetMigration(bootstrap));
    expect(writes).not.toHaveBeenCalled();
  });

  it("keeps custom pins, including another hash under the same logical asset ID", async () => {
    const custom = oldWorkspace("custom", "e".repeat(64));
    custom.aircraft.agentCoreContentSha256 = "f".repeat(64);
    const migration = await prepareBundledAssetMigration(bootstrap);
    expect(migration.workspace(custom)).toBe(custom);
    await expect(resolveAgentCoreAssetPair(custom)).rejects.toThrow("ASSET_VERSION_NOT_FOUND");
    const library = { schemaVersion: 2 as const, aircraft: [custom.aircraft], maps: [custom.mapPack], externalAssets: [] };
    expect(migration.library(library)).toBe(library);
    custom.aircraft.agentCoreContentSha256 = OLD_VEHICLE;
    const partial = migration.workspace(custom);
    expect(partial.mapPack).toBe(custom.mapPack);
    expect(partial.aircraft.agentCoreContentSha256).toBe(sample.job.result_vehicle_content_sha256);
    expect(partial.mission.compiledPlan).toBeNull();
  });

  it("does not resurrect deleted conversations or overwrite preserved corrupt records", async () => {
    saveAutonomyConversation("owner", "autonomy", oldWorkspace("deleted"));
    deleteAutonomyConversation("owner", "autonomy", "deleted");
    const corruptKey = "dronedream:autonomy-conversation:v1:owner:autonomy:corrupt";
    localStorage.setItem(corruptKey, "not-json");
    migrateStoredBundledAssets("owner", "autonomy", await prepareBundledAssetMigration(bootstrap));
    expect(listAutonomyConversations("owner", "autonomy")).toEqual([]);
    expect(localStorage.getItem(corruptKey)).toBe("not-json");
    expect(loadAutonomyConversation("owner", "autonomy", "deleted")).toBeNull();
  });

  it("updates inactive bundled library cards without replacing the selected custom map", async () => {
    const previous = oldWorkspace();
    const custom = oldWorkspace("custom");
    custom.mapPack = { ...custom.mapPack, id: "custom-map", agentCoreAssetId: "customer.map.v1", agentCoreContentSha256: "f".repeat(64) };
    custom.aircraft = { ...custom.aircraft, id: "custom-vehicle", agentCoreAssetId: "customer.vehicle.v1", agentCoreContentSha256: "e".repeat(64) };
    saveAutonomyWorkspace("owner", "autonomy", custom);
    saveAutonomyAssetLibrary("owner", "autonomy", { schemaVersion: 2,
      maps: [previous.mapPack, custom.mapPack], aircraft: [previous.aircraft, custom.aircraft], externalAssets: [] });
    migrateStoredBundledAssets("owner", "autonomy", await prepareBundledAssetMigration(bootstrap));
    const next = loadAutonomyWorkspace("owner", "autonomy");
    expect(next.mapPack.agentCoreContentSha256).toBe("f".repeat(64));
    expect(next.mission.compiledPlan).not.toBeNull();
    const library = loadAutonomyAssetLibrary("owner", "autonomy", next);
    expect(library.maps.find((item) => item.agentCoreAssetId === previous.mapPack.agentCoreAssetId)?.agentCoreContentSha256)
      .toBe(sample.job.result_map_content_sha256);
    expect(library.aircraft.find((item) => item.agentCoreAssetId === previous.aircraft.agentCoreAssetId)?.agentCoreContentSha256)
      .toBe(sample.job.result_vehicle_content_sha256);
  });

  it("removes old execution lookup before a failed cache write and safely resumes the upgrade", async () => {
    saveAutonomyWorkspace("owner", "autonomy", oldWorkspace());
    const threadKey = "dronedream:agent-core-thread:v1:owner:autonomy:saved";
    localStorage.setItem(threadKey, "old-core-thread");
    const migration = await prepareBundledAssetMigration(bootstrap);
    const writes = vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => { throw new Error("quota"); });
    expect(() => migrateStoredBundledAssets("owner", "autonomy", migration)).toThrow("quota");
    expect(localStorage.getItem(threadKey)).toBeNull();
    writes.mockRestore();
    migrateStoredBundledAssets("owner", "autonomy", migration);
    expect(loadAutonomyWorkspace("owner", "autonomy").mission.compiledPlan).toBeNull();
  });

  it.each(["receipt", "pair", "target", "schema", "evidence"])("rejects an invalid %s before changing any cached pin", async (field) => {
    saveAutonomyWorkspace("owner", "autonomy", oldWorkspace());
    if (field === "receipt") bootstrap.bundled_asset_migrations![0].receipt_sha256 = "f".repeat(64);
    if (field === "pair") bootstrap.asset_qualification_jobs[0].state = "failed";
    if (field === "target") bootstrap.bundled_asset_migrations![0].to_content_sha256 = "f".repeat(64);
    if (field === "schema") Object.assign(bootstrap.bundled_asset_migrations![0], { schema_version: "unknown" });
    if (field === "evidence") evidence.runtime_contracts.map.content_sha256 = "f".repeat(64);
    await expect(prepareBundledAssetMigration(bootstrap)).rejects.toThrow();
    expect(loadAutonomyWorkspace("owner", "autonomy").mapPack.agentCoreContentSha256).toBe(OLD_MAP);
  });

  it("is a no-op without a trusted migration list and preserves generic pin failure", async () => {
    delete bootstrap.bundled_asset_migrations;
    const previous = oldWorkspace();
    const migration = await prepareBundledAssetMigration(bootstrap);
    expect(migration.workspace(previous)).toBe(previous);
    expect(core.getAgentCoreAssetQualificationEvidence).not.toHaveBeenCalled();
    await expect(resolveAgentCoreAssetPair(previous)).rejects.toThrow("ASSET_VERSION_NOT_FOUND");
  });
});
