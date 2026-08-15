import { describe, expect, it } from "vitest";

import type { AutonomyCompileRequest } from "../../types/api";
import { createLocalAutonomyPreview } from "./missionAutonomy";
import { defaultAutonomyWorkspace, normalizeAutonomyWorkspace } from "./workspaceStore";
import {
  autonomyHarnessRequest,
  localAutonomyHarnessInspection,
  parseAutonomyPlannerArtifact,
} from "./missionHarness";

describe("autonomy mission harness", () => {
  it("keeps public assets unqualified until the owner receives server credentials", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z"));

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

  it("keeps every public mission preset grounded in School Map", () => {
    const request: AutonomyCompileRequest = {
      edition: "sim",
      execution_target: "simulation",
      natural_language: "Use the selected School Map mission preset.",
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
      expect(preview.scene.bounds_m).toEqual({ x: 120, y: 90, z: 12.6 });
      expect(preview.scene.name).not.toMatch(/forest|service corridor/i);
    }
  });

  it("uses the same stair-traversal action in local and backend School Map contracts", () => {
    const request: AutonomyCompileRequest = {
      edition: "sim",
      execution_target: "simulation",
      natural_language: "Descend both switchback stairs and land in the lobby.",
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
      "traverse_stairs",
      "land",
    ]);
    expect(preview.contract.task_graph.nodes.some((node) => (
      node.task_id.startsWith("mission-02-traverse-stairs-")
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
      task_graph: {},
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
  });
});
