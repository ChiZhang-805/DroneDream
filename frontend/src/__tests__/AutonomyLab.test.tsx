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
  AutonomySimulationExecution,
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

function previewForWorkspace(workspace: ReturnType<typeof qualifiedWorkspace>) {
  return createLocalAutonomyPreview("coffee", {
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
}

function mockQualifiedPlanning(workspace: ReturnType<typeof qualifiedWorkspace>) {
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
  let compileResponse = previewForWorkspace(workspace);
  vi.spyOn(apiClient, "compileAutonomyMission").mockImplementation(async (request) => {
    compileResponse = createLocalAutonomyPreview("coffee", request);
    return compileResponse;
  });
  return () => compileResponse;
}

function runtimeSessionFor(
  compileResponse: ReturnType<typeof createLocalAutonomyPreview>,
): AutonomyRuntimeSession {
  return {
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
}

function runningExecutionFor(runtime: AutonomyRuntimeSession): AutonomySimulationExecution {
  return {
    schema_version: "dronedream.autonomy.simulation-execution.v1",
    execution_id: `simexec-${"2".repeat(24)}`,
    runtime_session_id: runtime.session_id,
    contract_id: runtime.contract_id,
    planner_artifact_sha256: plannerBinding.artifact_sha256,
    state: "running",
    created_at: "2026-08-18T00:00:01.000Z",
    updated_at: "2026-08-18T00:00:02.000Z",
    progress: 0.1,
    phase: "takeoff",
    vehicle_model_root_world_enu_m: null,
    vehicle_envelope_center_world_enu_m: null,
    vehicle_speed_m_s: 0.4,
    payload_spawned: false,
    payload_attached: false,
    abort_reason: null,
    mission_evidence_sha256: null,
    mission_evidence: null,
  };
}

async function launchSimulation(
  executionState: AutonomySimulationExecution["state"] = "running",
) {
  const workspace = qualifiedWorkspace();
  const getCompileResponse = mockQualifiedPlanning(workspace);
  const createRuntime = vi.spyOn(apiClient, "createAutonomyRuntimeSession");
  const startExecution = vi.spyOn(apiClient, "startAutonomySimulationExecution");
  const abortExecution = vi.spyOn(apiClient, "abortAutonomySimulationExecution");
  const stopRuntime = vi.spyOn(apiClient, "stopAutonomyRuntimeSession");
  vi.spyOn(apiClient, "getAutonomySimulationExecution").mockImplementation(
    () => new Promise(() => undefined),
  );
  const view = render(
    <I18nProvider>
      <MemoryRouter>
        <AutonomyLab embedded workspace={workspace} />
      </MemoryRouter>
    </I18nProvider>,
  );

  fireEvent.click(screen.getByRole("button", { name: "Plan trajectory" }));
  await screen.findByRole("button", { name: "Replan trajectory" });
  const runtime = runtimeSessionFor(getCompileResponse());
  const execution = { ...runningExecutionFor(runtime), state: executionState };
  createRuntime.mockResolvedValue(runtime);
  startExecution.mockResolvedValue(execution);
  abortExecution.mockResolvedValue({ ...execution, state: "aborting" });
  stopRuntime.mockResolvedValue({ ...runtime, phase: "aborted", terminal: true });

  fireEvent.click(screen.getByRole("button", { name: "Fly mission" }));
  await waitFor(() => expect(startExecution).toHaveBeenCalledTimes(1));
  if (executionState === "running") {
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Tracking trajectory" }),
    ).toBeDisabled());
  } else {
    await act(async () => Promise.resolve());
  }
  return {
    abortExecution,
    execution,
    runtime,
    stopRuntime,
    view,
    workspace,
  };
}

describe("AutonomyLab launch cancellation", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.restoreAllMocks();
  });

  it("aborts a late runtime session and never starts simulation after Reset", async () => {
    const workspace = qualifiedWorkspace();
    const getCompileResponse = mockQualifiedPlanning(workspace);
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

    const runtimeSession = runtimeSessionFor(getCompileResponse());
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

  it("aborts an active simulator and runtime session when the workspace unmounts", async () => {
    const { abortExecution, execution, runtime, stopRuntime, view } = await launchSimulation();
    view.unmount();

    await waitFor(() => expect(abortExecution).toHaveBeenCalledWith(
      execution.execution_id,
      "Autonomy workspace closed while the simulation was active.",
    ));
    expect(stopRuntime).toHaveBeenCalledWith(
      runtime.session_id,
      "abort",
      "Autonomy workspace closed while the simulation was active.",
    );
  });

  it("aborts an active simulator and runtime session on Reset", async () => {
    const { abortExecution, execution, runtime, stopRuntime } = await launchSimulation();

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => expect(abortExecution).toHaveBeenCalledWith(
      execution.execution_id,
      "Operator reset the mission workspace.",
    ));
    expect(stopRuntime).toHaveBeenCalledWith(
      runtime.session_id,
      "abort",
      "Operator reset the mission workspace.",
    );
    expect(screen.getByRole("button", { name: "Fly mission" })).toBeEnabled();
  });

  it("aborts an active simulator when the mission contract changes", async () => {
    const { abortExecution, execution, runtime, stopRuntime, view, workspace } = await launchSimulation();
    const changedWorkspace = structuredClone(workspace);
    changedWorkspace.mission.intent = "Fly a changed mission contract.";
    changedWorkspace.mission.updatedAt = "2026-08-18T00:01:00.000Z";

    view.rerender(
      <I18nProvider>
        <MemoryRouter>
          <AutonomyLab embedded workspace={changedWorkspace} />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => expect(abortExecution).toHaveBeenCalledWith(
      execution.execution_id,
      "Autonomy mission contract changed while the simulation was active.",
    ));
    expect(stopRuntime).toHaveBeenCalledWith(
      runtime.session_id,
      "abort",
      "Autonomy mission contract changed while the simulation was active.",
    );
  });

  it("does not abort a verified execution when the workspace unmounts", async () => {
    const { abortExecution, stopRuntime, view } = await launchSimulation("verified");

    view.unmount();
    await act(async () => Promise.resolve());

    expect(abortExecution).not.toHaveBeenCalled();
    expect(stopRuntime).not.toHaveBeenCalled();
  });
});
