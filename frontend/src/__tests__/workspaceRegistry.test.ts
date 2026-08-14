import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearExperimentDraft, saveExperimentDraft } from "../features/experiment/draftStorage";
import {
  activeAssistantTenantContext,
  experimentWorkspacePath,
  hydrateAssistantWorkspaceIndex,
  isExperimentWorkspaceNameAvailable,
  listExperimentWorkspaces,
  reorderExperimentWorkspace,
  reorderExperimentWorkspaceItems,
  registerExperimentWorkspace,
  setActiveAssistantTenantContext,
  subscribeActiveAssistantTenantContext,
  updateExperimentWorkspace,
  type ExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

const OWNER_A = "account-a";
const OWNER_B = "account-b";
const FIRST_ID = "experiment-first";
const SECOND_ID = "experiment-second";

function saveWorkspaceDraft(workspaceId: string, name: string): void {
  saveExperimentDraft(
    {
      active_step: 0,
      completed_steps: [],
      form: { display_name: name, llm_api_key: "" },
      selections: {},
      conversation: null,
    },
    workspaceId,
  );
}

describe("experiment workspace registry", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    setActiveAssistantTenantContext(OWNER_A, { tenantId: OWNER_A, organizationId: null });
    setActiveAssistantTenantContext(OWNER_B, { tenantId: OWNER_B, organizationId: null });
  });

  it("notifies reactive consumers when an account changes tenant boundaries", () => {
    const ownerId = "reactive-tenant-owner";
    const listener = vi.fn();
    const unsubscribe = subscribeActiveAssistantTenantContext(ownerId, listener);

    expect(activeAssistantTenantContext(ownerId)).toEqual({
      tenantId: ownerId,
      organizationId: null,
    });
    setActiveAssistantTenantContext(ownerId, {
      tenantId: "organization-reactive",
      organizationId: "organization-reactive",
    });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(activeAssistantTenantContext(ownerId)).toEqual({
      tenantId: "organization-reactive",
      organizationId: "organization-reactive",
    });
    unsubscribe();
    setActiveAssistantTenantContext(ownerId, { tenantId: ownerId, organizationId: null });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("isolates workspaces by account and resumes each scoped draft", () => {
    saveWorkspaceDraft(FIRST_ID, "First experiment");
    saveWorkspaceDraft(SECOND_ID, "Second experiment");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "First experiment",
      source: "manual",
      activeStep: 2,
      completedSteps: [0, 1],
    });
    registerExperimentWorkspace({
      id: SECOND_ID,
      ownerId: OWNER_B,
      edition: "sim",
      name: "Second experiment",
      source: "assistant",
      activeStep: 3,
      completedSteps: [0, 1, 2],
    });

    expect(listExperimentWorkspaces(OWNER_A, "sim")).toMatchObject([
      {
        id: FIRST_ID,
        name: "First experiment",
        activeStep: 2,
        source: "manual",
      },
    ]);
    expect(listExperimentWorkspaces(OWNER_B, "sim")).toMatchObject([
      {
        id: SECOND_ID,
        name: "Second experiment",
        activeStep: 3,
        source: "assistant",
      },
    ]);
    expect(experimentWorkspacePath(listExperimentWorkspaces(OWNER_A, "sim")[0]))
      .toBe(`/jobs/new?experiment=${FIRST_ID}`);
  });

  it("hides assistant workspaces when the active organization boundary changes", async () => {
    setActiveAssistantTenantContext(OWNER_A, {
      tenantId: "org-alpha",
      organizationId: "org-alpha",
    });
    saveWorkspaceDraft(FIRST_ID, "Alpha tenant draft");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      tenantId: "org-alpha",
      organizationId: "org-alpha",
      edition: "sim",
      name: "Alpha tenant draft",
      source: "assistant",
    });
    expect(listExperimentWorkspaces(OWNER_A, "sim")).toHaveLength(1);

    setActiveAssistantTenantContext(OWNER_A, {
      tenantId: "org-beta",
      organizationId: "org-beta",
    });
    expect(listExperimentWorkspaces(OWNER_A, "sim")).toEqual([]);
  });

  it("sorts pinned workspaces first and retains created jobs without a draft", () => {
    saveWorkspaceDraft(FIRST_ID, "Draft");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "Draft",
      source: "manual",
    });
    saveWorkspaceDraft(SECOND_ID, "Created job");
    registerExperimentWorkspace({
      id: SECOND_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "Created job",
      source: "assistant",
    });
    updateExperimentWorkspace(OWNER_A, SECOND_ID, {
      status: "created",
      jobId: "job-42",
      pinned: true,
      activeStep: 4,
      completedSteps: [0, 1, 2, 3, 4],
    }, "sim");
    clearExperimentDraft(SECOND_ID);

    const workspaces = listExperimentWorkspaces(OWNER_A, "sim");
    expect(workspaces.map((workspace) => workspace.id)).toEqual([
      SECOND_ID,
      FIRST_ID,
    ]);
    expect(experimentWorkspacePath(workspaces[0])).toBe("/jobs/job-42");
  });

  it("prunes an abandoned draft entry once its session draft is gone", () => {
    saveWorkspaceDraft(FIRST_ID, "Temporary");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "Temporary",
      source: "manual",
    });
    expect(listExperimentWorkspaces(OWNER_A, "sim")).toHaveLength(1);

    clearExperimentDraft(FIRST_ID);

    expect(listExperimentWorkspaces(OWNER_A, "sim")).toEqual([]);
  });

  it("scopes active names by account and releases them after archive", () => {
    saveWorkspaceDraft(FIRST_ID, "Wind Study");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "Wind Study",
      source: "manual",
    });

    expect(isExperimentWorkspaceNameAvailable(OWNER_A, " wind   study ", "sim")).toBe(false);
    expect(isExperimentWorkspaceNameAvailable(OWNER_B, "Wind Study", "sim")).toBe(true);
    expect(
      isExperimentWorkspaceNameAvailable(OWNER_A, "Wind Study", "sim", FIRST_ID),
    ).toBe(true);

    updateExperimentWorkspace(OWNER_A, FIRST_ID, { archived: true }, "sim");
    expect(isExperimentWorkspaceNameAvailable(OWNER_A, "WIND STUDY", "sim")).toBe(true);
  });

  it("changes pin state only when a drag crosses into the other group", () => {
    const workspaces = [
      { id: "pinned-a", pinned: true, order: 0 },
      { id: "pinned-b", pinned: true, order: 1 },
      { id: "normal-a", pinned: false, order: 2 },
      { id: "normal-b", pinned: false, order: 3 },
      { id: "normal-c", pinned: false, order: 4 },
    ] as ExperimentWorkspace[];

    const normalAbovePinned = reorderExperimentWorkspaceItems(
      workspaces,
      "normal-b",
      0,
    );
    expect(normalAbovePinned[0]).toMatchObject({
      id: "normal-b",
      pinned: true,
    });

    const normalAfterLastPinned = reorderExperimentWorkspaceItems(
      workspaces,
      "normal-b",
      2,
    );
    expect(normalAfterLastPinned[2]).toMatchObject({
      id: "normal-b",
      pinned: false,
    });

    const pinnedAfterPinned = reorderExperimentWorkspaceItems(
      workspaces,
      "pinned-a",
      1,
    );
    expect(pinnedAfterPinned[1]).toMatchObject({
      id: "pinned-a",
      pinned: true,
    });

    const pinnedInsideNormal = reorderExperimentWorkspaceItems(
      workspaces,
      "pinned-a",
      2,
    );
    expect(pinnedInsideNormal[2]).toMatchObject({
      id: "pinned-a",
      pinned: false,
    });
    expect(pinnedInsideNormal.map((workspace) => workspace.order)).toEqual([
      0, 1, 2, 3, 4,
    ]);
  });

  it("persists a reordered workspace and its derived pin state", () => {
    for (const [id, name, pinned, order] of [
      ["experiment-pinned-a", "Pinned A", true, 0],
      ["experiment-pinned-b", "Pinned B", true, 1],
      ["experiment-normal-a", "Normal", false, 2],
    ] as const) {
      saveWorkspaceDraft(id, name);
      registerExperimentWorkspace({
        id,
        ownerId: OWNER_A,
        edition: "sim",
        name,
        source: "manual",
      });
      updateExperimentWorkspace(OWNER_A, id, { pinned, order }, "sim");
    }

    expect(
      reorderExperimentWorkspace(OWNER_A, "experiment-normal-a", 1, "sim")
        .map((workspace) => [workspace.name, workspace.pinned]),
    ).toEqual([
      ["Pinned A", true],
      ["Normal", true],
      ["Pinned B", true],
    ]);
    expect(
      listExperimentWorkspaces(OWNER_A, "sim")
        .map((workspace) => [workspace.name, workspace.pinned]),
    ).toEqual([
      ["Pinned A", true],
      ["Normal", true],
      ["Pinned B", true],
    ]);
  });

  it("rejects corrupted navigation and wizard-step state from local storage", () => {
    const base = {
      id: FIRST_ID,
      ownerId: OWNER_A,
      name: "Corrupted experiment",
      source: "manual",
      status: "created",
      activeStep: 4,
      pinned: false,
      archived: false,
      createdAt: "2026-07-29T12:00:00.000Z",
      updatedAt: "2026-07-29T12:00:00.000Z",
    };
    window.localStorage.setItem(
      `drone-dream:experiment-workspaces:v1:${encodeURIComponent(OWNER_A)}`,
      JSON.stringify({
        schemaVersion: 1,
        items: [
          {
            ...base,
            completedSteps: [0, 1, "2"],
            jobId: "job_safe",
          },
          {
            ...base,
            id: SECOND_ID,
            completedSteps: [0, 1, 2, 3, 4],
            jobId: "../account",
          },
        ],
      }),
    );

    expect(listExperimentWorkspaces(OWNER_A, "sim")).toEqual([]);
  });

  it("keeps SIM and FIELD workspaces in separate product registries", () => {
    const fieldId = "experiment-field";
    saveWorkspaceDraft(FIRST_ID, "SIM experiment");
    saveWorkspaceDraft(fieldId, "FIELD trial");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "sim",
      name: "SIM experiment",
      source: "assistant",
    });
    registerExperimentWorkspace({
      id: fieldId,
      ownerId: OWNER_A,
      edition: "field",
      name: "FIELD trial",
      source: "assistant",
    });

    expect(listExperimentWorkspaces(OWNER_A, "sim").map(({ id }) => id))
      .toEqual([FIRST_ID]);
    expect(listExperimentWorkspaces(OWNER_A, "field").map(({ id }) => id))
      .toEqual([fieldId]);
    expect(experimentWorkspacePath(listExperimentWorkspaces(OWNER_A, "field")[0]))
      .toBe(`/assistant?experiment=${fieldId}`);
    expect(isExperimentWorkspaceNameAvailable(OWNER_A, "SIM experiment", "field"))
      .toBe(true);
    expect(updateExperimentWorkspace(OWNER_A, FIRST_ID, {
      name: "Cross-edition rename",
    }, "field")).toBeNull();
    expect(() => registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      edition: "field",
      name: "Cross-edition replacement",
      source: "assistant",
    })).toThrow(/cannot move between editions/u);
  });

  it("hydrates only completed server objects in the active tenant boundary", () => {
    setActiveAssistantTenantContext(OWNER_A, {
      tenantId: OWNER_A,
      organizationId: null,
    });
    hydrateAssistantWorkspaceIndex(OWNER_A, [
      {
        conversation_id: "conversation-personal",
        tenant_id: OWNER_A,
        organization_id: null,
        edition: "sim",
        workspace_id: "server-sim-draft",
        title: "Server hover draft",
        summary: "Bounded hover draft",
        status: "active",
        latest_completed_sequence: 1,
        created_at: "2026-08-13T00:00:00.000Z",
        updated_at: "2026-08-13T00:00:01.000Z",
        latest_artifact: {
          artifact_id: "artifact-personal",
          artifact_kind: "simulation_experiment",
          title: "Server hover draft",
          version: 1,
          status: "draft",
          created_at: "2026-08-13T00:00:01.000Z",
          updated_at: "2026-08-13T00:00:01.000Z",
        },
      },
      {
        conversation_id: "conversation-other",
        tenant_id: "organization-other",
        organization_id: "organization-other",
        edition: "field",
        workspace_id: "server-field-task",
        title: "Other tenant task",
        summary: "Must not hydrate",
        status: "active",
        latest_completed_sequence: 1,
        created_at: "2026-08-13T00:00:00.000Z",
        updated_at: "2026-08-13T00:00:01.000Z",
        latest_artifact: {
          artifact_id: "artifact-other",
          artifact_kind: "field_task_plan",
          title: "Other tenant task",
          version: 1,
          status: "draft",
          created_at: "2026-08-13T00:00:01.000Z",
          updated_at: "2026-08-13T00:00:01.000Z",
        },
      },
    ]);

    expect(listExperimentWorkspaces(OWNER_A, "sim")).toMatchObject([{
      id: "server-sim-draft",
      tenantId: OWNER_A,
      organizationId: null,
      assistantArtifactKind: "simulation_experiment",
      status: "created",
    }]);
    expect(listExperimentWorkspaces(OWNER_A, "field")).toEqual([]);
    expect(experimentWorkspacePath(listExperimentWorkspaces(OWNER_A, "sim")[0]))
      .toBe("/assistant?experiment=server-sim-draft");
  });

  it("routes Universal assistant artifacts to their own editors", () => {
    const vehicleWorkspaceId = "universal-vehicle";
    const simulationWorkspaceId = "universal-simulation";
    saveWorkspaceDraft(vehicleWorkspaceId, "Vehicle model");
    saveWorkspaceDraft(simulationWorkspaceId, "Universal simulation");
    registerExperimentWorkspace({
      id: vehicleWorkspaceId,
      ownerId: OWNER_A,
      edition: "universal",
      name: "Vehicle model",
      source: "assistant",
      assistantArtifactKind: "universal_vehicle_model",
      vehicleDraftId: "vehicle-draft-42",
    });
    registerExperimentWorkspace({
      id: simulationWorkspaceId,
      ownerId: OWNER_A,
      edition: "universal",
      name: "Universal simulation",
      source: "assistant",
      assistantArtifactKind: "universal_simulation_experiment",
      vehicleDraftId: null,
    });

    const workspaces = listExperimentWorkspaces(OWNER_A, "universal");
    const vehicle = workspaces.find(({ id }) => id === vehicleWorkspaceId);
    const simulation = workspaces.find(({ id }) => id === simulationWorkspaceId);
    expect(vehicle && experimentWorkspacePath(vehicle))
      .toBe("/vehicle-studio?draft=vehicle-draft-42");
    expect(simulation && experimentWorkspacePath(simulation))
      .toBe(`/jobs/new?experiment=${simulationWorkspaceId}`);
  });

  it("migrates the legacy unscoped registry into SIM only", () => {
    saveWorkspaceDraft(FIRST_ID, "Legacy SIM experiment");
    window.localStorage.setItem(
      `drone-dream:experiment-workspaces:v1:${encodeURIComponent(OWNER_A)}`,
      JSON.stringify({
        schemaVersion: 1,
        items: [
          {
            id: FIRST_ID,
            ownerId: OWNER_A,
            name: "Legacy SIM experiment",
            source: "assistant",
            status: "draft",
            activeStep: 1,
            completedSteps: [0],
            jobId: null,
            pinned: false,
            archived: false,
            createdAt: "2026-08-01T00:00:00.000Z",
            updatedAt: "2026-08-01T00:00:00.000Z",
          },
        ],
      }),
    );

    expect(listExperimentWorkspaces(OWNER_A, "field")).toEqual([]);
    expect(listExperimentWorkspaces(OWNER_A, "sim")).toMatchObject([
      { id: FIRST_ID, edition: "sim", name: "Legacy SIM experiment" },
    ]);
    expect(window.localStorage.getItem(
      `drone-dream:experiment-workspaces:v1:${encodeURIComponent(OWNER_A)}`,
    )).toBeNull();
  });
});
