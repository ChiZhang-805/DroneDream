import { webcrypto } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as core from "../features/autonomy/agentCore";
import { inspectAgentCoreAssetBindings, resolveAgentCoreAssetPair } from "../features/autonomy/agentCorePlanning";
import { bindVerifiedAssetPair, reconcileAgentCoreWorkspace } from "../features/autonomy/assetPairBinding";
import { autonomyHarnessRequest } from "../features/autonomy/missionHarness";
import { defaultAutonomyWorkspace, normalizeAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import { loadAutonomyAssetLibrary } from "../features/autonomy/assetLibraryStore";
import sample from "./fixtures/qualifiedAssetPair.json";

// 来源为本机 Core 返回的历史认证合同，仅用于复现协议错误，不是本次飞行验收。
let fixture: typeof sample;
beforeEach(() => {
  fixture = structuredClone(sample);
  vi.stubGlobal("crypto", webcrypto);
  vi.spyOn(core, "getAgentCoreBootstrap").mockImplementation(async () => ({
    asset_versions: fixture.versions,
    asset_qualification_jobs: [fixture.job],
  }) as unknown as Awaited<ReturnType<typeof core.getAgentCoreBootstrap>>);
  vi.spyOn(core, "getAgentCoreAssetQualificationEvidence").mockImplementation(async () => (
    fixture.evidence as core.AgentCoreAssetQualificationEvidence
  ));
});

describe("qualified map and vehicle bindings", () => {
  it("restores an unbound selected pair, then passes real harness inspection", async () => {
    const original = defaultAutonomyWorkspace();
    const bound = await reconcileAgentCoreWorkspace(original, loadAutonomyAssetLibrary("test", "autonomy", original));
    expect(original.mapPack.qualificationReceiptId).toBeNull();
    expect(bound.mapPack.qualificationReceiptId).toBe(fixture.job.qualification_id);
    expect(bound.aircraft.qualificationReceiptId).toBe(fixture.job.qualification_id);
    expect(bound.aircraft.agentCoreContentSha256).toBe(fixture.job.result_vehicle_content_sha256);
    expect(bound.aircraft.dryMassKg).toBe(fixture.evidence.runtime_contracts.vehicle.dry_mass_kg);
    expect(bound.aircraft.sensors).toContain("depth");
    expect(normalizeAutonomyWorkspace(bound).mapPack).toEqual(bound.mapPack);
    expect(normalizeAutonomyWorkspace(bound).aircraft).toEqual(bound.aircraft);
    const inspection = await inspectAgentCoreAssetBindings(autonomyHarnessRequest("autonomy", bound, "拿下快递"), bound);
    expect(inspection.planning_ready).toBe(true);
  });

  it("preserves a genuinely qualified sensor upgrade of the default aircraft", async () => {
    const original = defaultAutonomyWorkspace();
    const bound = await reconcileAgentCoreWorkspace(original, loadAutonomyAssetLibrary("test", "autonomy", original));
    bound.aircraft.id = "aircraft-my-drone";
    const library = loadAutonomyAssetLibrary("test-upgrade", "autonomy", bound);
    library.aircraft = [bound.aircraft];
    const pair = await resolveAgentCoreAssetPair(bound);
    const result = bindVerifiedAssetPair(bound, library, pair.job, pair.mapVersion, pair.vehicleVersion, pair.evidence.runtime_contracts);
    expect(result).not.toBeNull();
    expect(result!.workspace.aircraft.id).toBe("aircraft-my-drone");
    expect(result!.workspace.aircraft.sensors).toEqual(["gps", "depth"]);
    expect(result!.workspace.aircraft.qualificationReceiptId).toBe(fixture.job.qualification_id);
    expect(normalizeAutonomyWorkspace(result!.workspace).aircraft.sensors).toContain("depth");
  });

  it("accepts distinct source/result hashes and a map without autopilot", async () => {
    expect(fixture.job.map_content_sha256).not.toBe(fixture.job.result_map_content_sha256);
    expect(fixture.evidence.runtime_contracts.map.simulation_targets[0].autopilot).toBe("none");
    expect((await resolveAgentCoreAssetPair(defaultAutonomyWorkspace())).job.job_id).toBe(fixture.job.job_id);
  });

  it("repairs stale receipt hints only when the content pins still match", async () => {
    const workspace = defaultAutonomyWorkspace();
    workspace.mapPack.agentCoreContentSha256 = fixture.job.result_map_content_sha256;
    workspace.aircraft.agentCoreContentSha256 = fixture.job.result_vehicle_content_sha256;
    workspace.mapPack.qualificationReceiptId = `asset-qualification-${"a".repeat(24)}`;
    workspace.aircraft.qualificationReceiptId = `asset-qualification-${"b".repeat(24)}`;
    const bound = await reconcileAgentCoreWorkspace(workspace, loadAutonomyAssetLibrary("test", "autonomy", workspace));
    expect(bound.mapPack.qualificationReceiptId).toBe(fixture.job.qualification_id);
    expect(bound.mapPack.agentCoreContentSha256).toBe(workspace.mapPack.agentCoreContentSha256);
  });

  it("never replaces a pinned old or missing version with the latest asset", async () => {
    const workspace = defaultAutonomyWorkspace();
    workspace.mapPack.agentCoreContentSha256 = "a".repeat(64);
    await expect(resolveAgentCoreAssetPair(workspace)).rejects.toThrow("ASSET_VERSION_NOT_FOUND");
    expect(core.getAgentCoreAssetQualificationEvidence).not.toHaveBeenCalled();
  });

  it.each(["state", "progress", "output-map", "output-vehicle", "asset-id"])("rejects a job with invalid %s", async (field) => {
    if (field === "state") fixture.job.state = "failed";
    if (field === "progress") fixture.job.progress_percent = 99;
    if (field === "output-map") fixture.job.result_map_content_sha256 = "a".repeat(64);
    if (field === "output-vehicle") fixture.job.result_vehicle_content_sha256 = "b".repeat(64);
    if (field === "asset-id") fixture.job.map_asset_id = "another-map";
    await expect(resolveAgentCoreAssetPair(defaultAutonomyWorkspace())).rejects.toThrow("QUALIFICATION_JOB_NOT_FOUND");
  });

  it.each(["source-map", "source-vehicle", "result-map", "runtime-hash", "gate", "autopilot", "simulator"])("rejects inconsistent evidence: %s", async (field) => {
    if (field === "source-map") fixture.evidence.receipt.map_content_sha256 = "a".repeat(64);
    if (field === "source-vehicle") fixture.evidence.receipt.vehicle_content_sha256 = "b".repeat(64);
    if (field === "result-map") fixture.evidence.map_content_sha256 = "c".repeat(64);
    if (field === "runtime-hash") fixture.evidence.runtime_contracts.vehicle.content_sha256 = "d".repeat(64);
    if (field === "gate") Object.assign(fixture.evidence.receipt.runtime_evidence.gates, { required_gate: false });
    if (field === "autopilot") fixture.evidence.runtime_contracts.map.simulation_targets[0].autopilot = "ardupilot";
    if (field === "simulator") fixture.evidence.runtime_contracts.map.simulation_targets[0].simulator_version = "different";
    await expect(resolveAgentCoreAssetPair(defaultAutonomyWorkspace())).rejects.toThrow("EVIDENCE_INVALID");
  });

  it("does not treat absent binding as a mismatch or contact a model", async () => {
    const workspace = defaultAutonomyWorkspace();
    await expect(inspectAgentCoreAssetBindings(autonomyHarnessRequest("autonomy", workspace, "拿下快递"), workspace)).rejects.toThrow("BINDING_REQUIRED");
    expect(core.getAgentCoreBootstrap).not.toHaveBeenCalled();
  });

  it("rejects a request carrying a different content hash after reconciliation", async () => {
    const original = defaultAutonomyWorkspace();
    const bound = await reconcileAgentCoreWorkspace(original, loadAutonomyAssetLibrary("test", "autonomy", original));
    const request = autonomyHarnessRequest("autonomy", bound, "拿下快递");
    request.map_pack.content_hash = "f".repeat(64);
    await expect(inspectAgentCoreAssetBindings(request, bound)).rejects.toThrow("QUALIFICATION_ID_MISMATCH");
  });
});
