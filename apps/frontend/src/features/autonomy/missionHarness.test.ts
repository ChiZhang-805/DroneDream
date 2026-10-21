import { describe, expect, it } from "vitest";

import type { AutonomyCompileRequest } from "../../types/api";
import { loadAutonomyAssetLibrary } from "./assetLibraryStore";
import { createLocalAutonomyPreview } from "./missionAutonomy";
import {
  defaultAutonomyWorkspace,
  isAutonomyAircraftProfileValid,
  normalizeAutonomyWorkspace,
} from "./workspaceStore";
import {
  autonomyHarnessRequest,
  localAutonomyHarnessInspection,
  parseAutonomyPlannerArtifact,
  autonomyPlannerBindingIssues,
} from "./missionHarness";

describe("autonomy mission harness", () => {
  it("keeps public assets unqualified until the owner receives server credentials", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));

    expect(isAutonomyAircraftProfileValid(workspace.aircraft)).toBe(true);
    expect(workspace.aircraft.status).toBe("draft");
    expect(workspace.aircraft.qualificationReceiptId).toBeNull();
    expect(workspace.aircraft.qualificationContentHash).toBeNull();
    expect(workspace.mapPack.status).toBe("draft");
    expect(workspace.mapPack.qualificationReceiptId).toBeNull();
    expect(workspace.mapPack.contentHash).toBeNull();
  });

  it("invalidates legacy bundled qualification placeholders during migration", () => {
    const legacy = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    legacy.aircraft.status = "signed";
    legacy.aircraft.qualificationReceiptId = "bundled-public-vehicle-my-drone-v1";
    legacy.aircraft.qualificationContentHash = "a".repeat(64);
    legacy.mapPack.status = "qualified";
    legacy.mapPack.qualificationReceiptId = "bundled-public-map-school-campus-v1";
    legacy.mapPack.contentHash = "b".repeat(64);

    const migrated = normalizeAutonomyWorkspace(legacy);

    expect(migrated.aircraft.status).toBe("draft");
    expect(migrated.aircraft.qualificationReceiptId).toBeNull();
    expect(migrated.aircraft.qualificationContentHash).toBeNull();
    expect(migrated.mapPack.status).toBe("draft");
    expect(migrated.mapPack.qualificationReceiptId).toBeNull();
    expect(migrated.mapPack.contentHash).toBeNull();
  });

  it("preserves a real imported map that happens to share the retired placeholder name", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    workspace.mapPack = {
      ...workspace.mapPack,
      id: "map-user-import",
      version: 3,
      name: "5 environment",
      status: "assets-admitted",
      compilerSceneId: null,
      calibrated: false,
      confidencePercent: 0,
      sourceFiles: [{
        name: "campus.glb",
        bytes: 1024,
        format: "glb",
        importedAt: "2026-08-15T00:00:00.000Z",
        sha256: "a".repeat(64),
        receiptId: "receipt-user-import",
        admission: "admitted",
        parser: "gltf",
        layers: ["mesh"],
      }],
    };

    const normalized = normalizeAutonomyWorkspace(workspace);

    expect(normalized.mapPack.id).toBe("map-user-import");
    expect(normalized.mapPack.name).toBe("5 environment");
    expect(normalized.mapPack.version).toBe(1);
    expect(normalized.mapPack.sourceFiles).toHaveLength(1);
  });

  it("keeps one replace-in-place map identity instead of creating visible revisions", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    workspace.mapPack.version = 9;
    workspace.mapPack.status = "qualified";
    workspace.mapPack.contentHash = "a".repeat(64);
    workspace.mapPack.qualificationReceiptId = "old-map-receipt";

    const normalized = normalizeAutonomyWorkspace(workspace);

    expect(normalized.mapPack.id).toBe("map-school");
    expect(normalized.mapPack.name).toBe("Kumpula Campus");
    expect(normalized.mapPack.version).toBe(1);
    expect(normalized.mapPack.status).toBe("draft");
    expect(normalized.mapPack.qualificationReceiptId).toBeNull();
  });

  it("migrates retired bundled presets to the one canonical Kumpula Campus", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    workspace.mission.compiledPlan = {
      readiness: "simulation_ready",
      canExecute: true,
    } as unknown as NonNullable<typeof workspace.mission.compiledPlan>;
    workspace.mapPack = {
      ...workspace.mapPack,
      name: "Building stairwell · pickup · return v3",
      compilerSceneId: "stairwell-coffee-return",
      boundsM: { x: 42, y: 28, z: 11 },
      floorCount: 3,
      status: "qualified",
      contentHash: "a".repeat(64),
      qualificationReceiptId: "old-stairwell-receipt",
    };

    const normalized = normalizeAutonomyWorkspace(workspace);

    expect(normalized.mapPack.name).toBe("Kumpula Campus");
    expect(normalized.mapPack.compilerSceneId).toBe("school-campus-v1");
    expect(normalized.mapPack.boundsM).toEqual({ x: 500, y: 500, z: 35 });
    expect(normalized.mapPack.status).toBe("draft");
    expect(normalized.mapPack.contentHash).toBeNull();
    expect(normalized.mapPack.qualificationReceiptId).toBeNull();
    expect(normalized.mission.compiledPlan).toBeNull();
  });

  it("restores public assets when the persisted asset library is malformed", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    workspace.aircraft = {
      ...workspace.aircraft,
      id: "aircraft-custom",
      name: "Custom aircraft",
      agentCoreAssetId: null,
    };
    workspace.mapPack = {
      ...workspace.mapPack,
      id: "map-custom",
      name: "Custom map",
      agentCoreAssetId: null,
    };

    const library = loadAutonomyAssetLibrary("local", "universal", workspace, {
      getItem: () => "{malformed-json",
    });

    expect(library.aircraft.map((aircraft) => aircraft.id)).toEqual([
      "aircraft-custom",
      "aircraft-my-drone",
    ]);
    expect(library.maps.map((mapPack) => mapPack.id)).toEqual([
      "map-custom",
      "map-school",
    ]);
  });

  it("publishes only the GPS mount present in the qualified PX4 Gazebo vehicle", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    const mounts = Object.fromEntries(workspace.aircraft.sensorMounts.map((mount) => [mount.id, mount]));

    expect(workspace.aircraft.sensors).toEqual(["gps"]);
    expect(Object.keys(mounts)).toEqual(["gps-primary"]);
    expect(mounts["gps-primary"].positionM).toEqual({ x: -0.07, y: 0, z: 0.2 });
  });

  it("keeps every public mission preset grounded in Kumpula Campus", () => {
    const request: AutonomyCompileRequest = {
      edition: "sim",
      locale: "en",
      execution_target: "simulation",
      natural_language: "Use the selected Kumpula Campus mission preset.",
      scene_id: "school-campus-v1",
      perception_mode: "fusion",
      vehicle: {
        dry_mass_kg: 1.86,
        launch_payload_kg: 0.1,
        pickup_payload_kg: 0.35,
        max_takeoff_mass_kg: 2.8,
        max_total_thrust_n: 44,
        radius_m: 0.381,
        max_speed_mps: 4,
        max_acceleration_mps2: 2.5,
        reserve_battery_percent: 30,
      },
      evidence: {
        simulation_qualified: false,
        signed_vehicle_pack_id: null,
        operator_confirmed: false,
        localization_ready: false,
        link_ready: false,
        geofence_ready: false,
        battery_ready: false,
      },
      asset_context: null,
    };

    for (const missionId of ["coffee", "gates", "narrow"] as const) {
      const preview = createLocalAutonomyPreview(missionId, request);
      expect(preview.scene.id).toBe("school-campus-v1");
      expect(preview.scene.bounds_m).toEqual({ x: 500, y: 500, z: 35 });
      expect(preview.scene.name).not.toMatch(/forest|service corridor/i);
    }
  });

  it("uses the verified outdoor transfer actions for Kumpula Campus", () => {
    const request: AutonomyCompileRequest = {
      edition: "sim",
      locale: "en",
      execution_target: "simulation",
      natural_language: "Transfer the item from Exactum to Chemicum and return.",
      scene_id: "school-campus-v1",
      perception_mode: "fusion",
      vehicle: {
        dry_mass_kg: 1.86,
        launch_payload_kg: 0.1,
        pickup_payload_kg: 0.35,
        max_takeoff_mass_kg: 2.8,
        max_total_thrust_n: 44,
        radius_m: 0.381,
        max_speed_mps: 4,
        max_acceleration_mps2: 2.5,
        reserve_battery_percent: 30,
      },
      evidence: {
        simulation_qualified: false,
        signed_vehicle_pack_id: null,
        operator_confirmed: false,
        localization_ready: false,
        link_ready: false,
        geofence_ready: false,
        battery_ready: false,
      },
      asset_context: null,
    };

    const preview = createLocalAutonomyPreview("narrow", request);

    expect(preview.contract.steps.map((step) => step.action)).toEqual([
      "takeoff",
      "transit",
      "land",
    ]);
    expect(preview.contract.task_graph.nodes.some((node) => (
      node.task_id.startsWith("mission-02-transit-")
    ))).toBe(true);
  });

  it("recognizes the public assets but still fails closed without the server registry", async () => {
    const request = autonomyHarnessRequest(
      "universal",
      defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z")),
      "Fly from the office to the pickup cabinet and return.",
    );

    const inspection = await localAutonomyHarnessInspection(request);

    expect(inspection.status).toBe("needs_assets");
    expect(inspection.planning_ready).toBe(false);
    expect(inspection.blockers).toContain("aircraft.qualification-registry.unavailable");
    expect(inspection.blockers).toContain("map.qualification-registry.unavailable");
    expect(inspection.eligible_tool_ids).toEqual([
      "vehicle.inspect_binding",
      "map.inspect_binding",
      "mission.validate_asset_readiness",
    ]);
  });

  it("requires the server registry even when local assets look qualified", async () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));
    workspace.aircraft.status = "signed";
    workspace.aircraft.qualificationReceiptId = "vehicle-receipt-1";
    workspace.aircraft.qualificationContentHash = "b".repeat(64);
    workspace.mapPack.status = "qualified";
    workspace.mapPack.contentHash = "a".repeat(64);
    workspace.mapPack.qualificationReceiptId = "map-receipt-1";
    workspace.mapPack.compilerSceneId = "stairwell-coffee-return";
    const request = autonomyHarnessRequest(
      "sim",
      workspace,
      "Inspect pickup cabinet 7 and return to the office.",
    );

    const inspection = await localAutonomyHarnessInspection(request);

    expect(inspection.status).toBe("needs_assets");
    expect(inspection.planning_ready).toBe(false);
    expect(inspection.blockers).toContain("aircraft.qualification-registry.unavailable");
    expect(inspection.blockers).toContain("map.qualification-registry.unavailable");
    expect(inspection.eligible_tool_ids).not.toContain("map.resolve_entity");
    expect(inspection.eligible_tool_ids).not.toContain("mission.validate_plan");
  });

  it("rejects planner output that weakens the safety or repair contract", () => {
    const valid = {
      schema_version: "dronedream.autonomy.planner-response.v1",
      status: "draft",
      goal: "Retrieve the package and return.",
      asset_bindings: {
        aircraft_id: "aircraft-primary",
        aircraft_version: 1,
        map_id: "map-primary",
        map_version: 1,
        context_sha256: "b".repeat(64),
      },
      grounded_entities: [],
      task_graph: {
        nodes: [
          { node_id: "takeoff", action: "takeoff", target: "office-drone-launch-pad", depends_on: [], success_evidence: ["airborne telemetry"] },
          { node_id: "pickup", action: "pickup", target: "takeout-pickup", depends_on: ["takeoff"], success_evidence: ["payload attached"] },
          { node_id: "return", action: "return", target: "office-drone-launch-pad", depends_on: ["pickup"], success_evidence: ["office return reached"] },
          { node_id: "land", action: "land", target: "office-drone-launch-pad", depends_on: ["return"], success_evidence: ["landed telemetry"] },
        ],
      },
      tool_requests: [],
      tool_receipts: [],
      assumptions: [],
      blockers: [],
      repair: {
        attempt: 0,
        max_attempts: 3,
        repeated_plan_hashes: 0,
        stop_reason: null,
      },
      safety_policy: {
        actuator_authority: false,
        may_relax_constraints: false,
        execution_requires_deterministic_validation: true,
      },
    } as const;

    expect(parseAutonomyPlannerArtifact(valid)).not.toBeNull();
    expect(parseAutonomyPlannerArtifact({
      ...valid,
      safety_policy: { ...valid.safety_policy, actuator_authority: true },
    })).toBeNull();
    expect(parseAutonomyPlannerArtifact({
      ...valid,
      repair: { ...valid.repair, max_attempts: 99 },
    })).toBeNull();
    expect(parseAutonomyPlannerArtifact({
      ...valid,
      task_graph: { nodes: [] },
    })).toBeNull();
    expect(parseAutonomyPlannerArtifact({
      ...valid,
      task_graph: {
        nodes: valid.task_graph.nodes.map((node) => ({
          ...node,
          depends_on: [node.node_id],
        })),
      },
    })).toBeNull();
    expect(parseAutonomyPlannerArtifact({
      ...valid,
      task_graph: {
        nodes: valid.task_graph.nodes.map((node) => (
          node.node_id === "pickup"
            ? { ...node, depends_on: ["takeoff", "takeoff"] }
            : node
        )),
      },
    })).toBeNull();
  });

  it("fails closed when a planner draft changes an inspected asset binding", async () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-18T00:00:00.000Z"));
    const request = autonomyHarnessRequest("sim", workspace, "Retrieve the parcel and return.");
    const inspection = await localAutonomyHarnessInspection(request);
    const artifact = parseAutonomyPlannerArtifact({
      schema_version: "dronedream.autonomy.planner-response.v1",
      status: "draft",
      goal: "Retrieve the parcel and return.",
      asset_bindings: {
        aircraft_id: request.aircraft.asset_id,
        aircraft_version: request.aircraft.version,
        map_id: request.map_pack.asset_id,
        map_version: request.map_pack.version,
        context_sha256: inspection.context_sha256,
      },
      grounded_entities: [],
      task_graph: {
        nodes: [
          { node_id: "takeoff", action: "takeoff", target: "office-drone-launch-pad", depends_on: [], success_evidence: ["airborne telemetry"] },
          { node_id: "pickup", action: "pickup", target: "takeout-pickup", depends_on: ["takeoff"], success_evidence: ["payload attached"] },
          { node_id: "return", action: "return", target: "office-drone-launch-pad", depends_on: ["pickup"], success_evidence: ["office return reached"] },
          { node_id: "land", action: "land", target: "office-drone-launch-pad", depends_on: ["return"], success_evidence: ["landed telemetry"] },
        ],
      },
      tool_requests: [],
      tool_receipts: [],
      assumptions: [],
      blockers: [],
      repair: { attempt: 0, max_attempts: 3, repeated_plan_hashes: 0, stop_reason: null },
      safety_policy: {
        actuator_authority: false,
        may_relax_constraints: false,
        execution_requires_deterministic_validation: true,
      },
    });
    expect(artifact).not.toBeNull();
    expect(autonomyPlannerBindingIssues(artifact!, request, inspection)).toEqual([]);
    expect(autonomyPlannerBindingIssues({
      ...artifact!,
      asset_bindings: { ...artifact!.asset_bindings, map_version: request.map_pack.version + 1 },
    }, request, inspection)).toContain("planner.map-version.mismatch");
    expect(autonomyPlannerBindingIssues({
      ...artifact!,
      task_graph: {
        nodes: artifact!.task_graph.nodes.map((node) => (
          node.action === "pickup" ? { ...node, target: "cafeteria-counter" } : node
        )),
      },
    }, request, inspection)).toContain(
      "planner.route-target.missing.pickup:takeout-pickup",
    );
    expect(autonomyPlannerBindingIssues({
      ...artifact!,
      task_graph: {
        nodes: [
          ...artifact!.task_graph.nodes,
          {
            node_id: "detour",
            action: "navigate",
            target: "cafeteria-counter",
            depends_on: ["takeoff"],
            success_evidence: ["detour reached"],
          },
        ],
      },
    }, request, inspection)).toContain("planner.route-profile.unsupported");
    expect(autonomyPlannerBindingIssues({
      ...artifact!,
      task_graph: {
        nodes: artifact!.task_graph.nodes.map((node) => (
          node.action === "return" ? { ...node, depends_on: ["takeoff"] } : node
        )),
      },
    }, request, inspection)).toContain("planner.route-profile.unsupported");
  });
});
