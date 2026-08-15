import { describe, expect, it } from "vitest";

import { defaultAutonomyWorkspace } from "./workspaceStore";
import {
  autonomyHarnessRequest,
  localAutonomyHarnessInspection,
  parseAutonomyPlannerArtifact,
} from "./missionHarness";

describe("autonomy mission harness", () => {
  it("fails closed while the default aircraft and map remain drafts", async () => {
    const request = autonomyHarnessRequest(
      "universal",
      defaultAutonomyWorkspace(new Date("2026-08-15T00:00:00.000Z")),
      "Fly from the office to the pickup cabinet and return.",
    );

    const inspection = await localAutonomyHarnessInspection(request);

    expect(inspection.status).toBe("needs_assets");
    expect(inspection.planning_ready).toBe(false);
    expect(inspection.blockers).toContain("aircraft.pack.not-validated");
    expect(inspection.blockers).toContain("map.pack.not-qualified");
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
