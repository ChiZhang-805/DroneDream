import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import { createLocalAutonomyPreview } from "../features/autonomy/missionAutonomy";
import {
  defaultAutonomyWorkspace,
  type AutonomyMissionPlanSnapshot,
} from "../features/autonomy/workspaceStore";
import { I18nProvider } from "../i18n/I18nProvider";
import { AutonomyLab } from "../pages/AutonomyLab";
import type {
  AutonomyCompileAssetContext,
  AutonomyRuntimeSession,
} from "../types/api";

const plannerBinding: NonNullable<AutonomyCompileAssetContext["planner_binding"]> = {
  schema_version: "dronedream.autonomy.planner-binding.v1",
  status: "draft",
  run_id: "planner-run-reset-race",
  provider: "test",
  model: "test-model",
  artifact_sha256: "d".repeat(64),
  goal: "Fly from the office to the takeout pickup and return.",
  aircraft_id: "aircraft-my-drone",
  aircraft_version: 1,
  map_id: "map-school",
  map_version: 1,
  context_sha256: "a".repeat(64),
  task_graph: {
    nodes: [
      { node_id: "takeoff", action: "takeoff", target: "office-drone-launch-pad", depends_on: [], success_evidence: ["airborne"] },
      { node_id: "pickup", action: "pickup", target: "takeout-pickup", depends_on: ["takeoff"], success_evidence: ["payload attached"] },
      { node_id: "return", action: "return", target: "office-drone-launch-pad", depends_on: ["pickup"], success_evidence: ["office reached"] },
      { node_id: "land", action: "land", target: "office-drone-launch-pad", depends_on: ["return"], success_evidence: ["landed"] },
    ],
  },
};

function qualifiedWorkspace() {
  const workspace = defaultAutonomyWorkspace(new Date("2026-08-18T00:00:00.000Z"));
  workspace.aircraft.status = "validated-unsigned";
  workspace.aircraft.qualificationReceiptId = "vehicle-receipt-reset-race";
  workspace.aircraft.qualificationContentHash = "b".repeat(64);
  workspace.mapPack.status = "qualified";
  workspace.mapPack.contentHash = "c".repeat(64);
  workspace.mapPack.qualificationReceiptId = "map-receipt-reset-race";
  workspace.mission.compiledPlan = {
    plannerBinding,
  } as AutonomyMissionPlanSnapshot;
  return workspace;
}

describe("AutonomyLab launch cancellation", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.restoreAllMocks();
  });

  it("aborts a late runtime session and never starts simulation after Reset", async () => {
    const workspace = qualifiedWorkspace();
    vi.spyOn(apiClient, "inspectAutonomyHarness").mockResolvedValue({
      schema_version: "dronedream.autonomy.harness-context.v1",
      prompt_version: "dronedream.autonomy.system.v1",
      tool_registry_version: "dronedream.autonomy.tools.v1",
      context_sha256: "a".repeat(64),
      status: "draft",
      planning_ready: true,
      blockers: [],
      required_next_actions: [],
      eligible_tool_ids: [],
      tool_receipts: [],
      repair_policy: {
        schema_version: "dronedream.autonomy.repair-policy.v1",
        semantic_attempt_limit: 3,
        trajectory_attempt_limit: 3,
        repeated_plan_hash_limit: 2,
        may_relax_safety_constraints: false,
      },
    });
    let compileResponse = createLocalAutonomyPreview("coffee", {
      edition: "universal",
      execution_target: "simulation",
      natural_language: workspace.mission.intent,
      scene_id: "school-campus-v1",
      perception_mode: "fusion",
      vehicle: {
        dry_mass_kg: workspace.aircraft.dryMassKg,
        launch_payload_kg: 0,
        pickup_payload_kg: workspace.aircraft.maximumPickupPayloadKg,
        max_takeoff_mass_kg: workspace.aircraft.maximumTakeoffMassKg,
        max_total_thrust_n: workspace.aircraft.maximumThrustN,
        radius_m: 0.38,
        max_speed_mps: workspace.aircraft.maximumSpeedMps,
        max_acceleration_mps2: workspace.aircraft.maximumAccelerationMps2,
        reserve_battery_percent: workspace.aircraft.reserveBatteryPercent,
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
    });
    vi.spyOn(apiClient, "compileAutonomyMission").mockImplementation(async (request) => {
      compileResponse = createLocalAutonomyPreview("coffee", request);
      return compileResponse;
    });
    let resolveRuntime: ((session: AutonomyRuntimeSession) => void) | undefined;
    vi.spyOn(apiClient, "createAutonomyRuntimeSession").mockReturnValue(new Promise((resolve) => {
      resolveRuntime = resolve;
    }));
    const startExecution = vi.spyOn(apiClient, "startAutonomySimulationExecution");
    const stopRuntime = vi.spyOn(apiClient, "stopAutonomyRuntimeSession");

    render(
      <I18nProvider>
        <MemoryRouter>
          <AutonomyLab embedded workspace={workspace} />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Plan trajectory" }));
    await screen.findByRole("button", { name: "Replan trajectory" });
    fireEvent.click(screen.getByRole("button", { name: "Fly mission" }));
    await waitFor(() => expect(apiClient.createAutonomyRuntimeSession).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    const runtimeSession: AutonomyRuntimeSession = {
      schema_version: "dronedream.autonomy.runtime-session.v1",
      session_id: `runtime-${"1".repeat(24)}`,
      contract_id: compileResponse.contract.contract_id,
      execution_target: "simulation",
      phase: "ready",
      bridge: "px4_gazebo",
      command_authority: true,
      created_at: "2026-08-18T00:00:00.000Z",
      updated_at: "2026-08-18T00:00:00.000Z",
      latest_sequence: 0,
      latest_monotonic_ms: 0,
      observation_count: 0,
      decision: { action: "hold", accepted: true, codes: ["runtime.awaiting-first-observation"] },
      task_graph: compileResponse.contract.task_graph,
      perceived_entities: [],
      stream_health: [],
      decision_events: [],
      evidence_chain_head: "e".repeat(64),
      terminal: false,
    };
    stopRuntime.mockResolvedValue({ ...runtimeSession, phase: "aborted", terminal: true });
    await act(async () => {
      resolveRuntime?.(runtimeSession);
      await Promise.resolve();
    });

    await waitFor(() => expect(stopRuntime).toHaveBeenCalledWith(
      runtimeSession.session_id,
      "abort",
      "Launch was cancelled before simulator startup.",
    ));
    expect(startExecution).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Fly mission" })).toBeEnabled();
  });
});
