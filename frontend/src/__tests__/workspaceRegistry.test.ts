import { beforeEach, describe, expect, it } from "vitest";

import { clearExperimentDraft, saveExperimentDraft } from "../features/experiment/draftStorage";
import {
  experimentWorkspacePath,
  isExperimentWorkspaceNameAvailable,
  listExperimentWorkspaces,
  reorderExperimentWorkspace,
  reorderExperimentWorkspaceItems,
  registerExperimentWorkspace,
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
  });

  it("isolates workspaces by account and resumes each scoped draft", () => {
    saveWorkspaceDraft(FIRST_ID, "First experiment");
    saveWorkspaceDraft(SECOND_ID, "Second experiment");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      name: "First experiment",
      source: "manual",
      activeStep: 2,
      completedSteps: [0, 1],
    });
    registerExperimentWorkspace({
      id: SECOND_ID,
      ownerId: OWNER_B,
      name: "Second experiment",
      source: "assistant",
      activeStep: 3,
      completedSteps: [0, 1, 2],
    });

    expect(listExperimentWorkspaces(OWNER_A)).toMatchObject([
      {
        id: FIRST_ID,
        name: "First experiment",
        activeStep: 2,
        source: "manual",
      },
    ]);
    expect(listExperimentWorkspaces(OWNER_B)).toMatchObject([
      {
        id: SECOND_ID,
        name: "Second experiment",
        activeStep: 3,
        source: "assistant",
      },
    ]);
    expect(experimentWorkspacePath(listExperimentWorkspaces(OWNER_A)[0]))
      .toBe(`/jobs/new?experiment=${FIRST_ID}`);
  });

  it("sorts pinned workspaces first and retains created jobs without a draft", () => {
    saveWorkspaceDraft(FIRST_ID, "Draft");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      name: "Draft",
      source: "manual",
    });
    saveWorkspaceDraft(SECOND_ID, "Created job");
    registerExperimentWorkspace({
      id: SECOND_ID,
      ownerId: OWNER_A,
      name: "Created job",
      source: "assistant",
    });
    updateExperimentWorkspace(OWNER_A, SECOND_ID, {
      status: "created",
      jobId: "job-42",
      pinned: true,
      activeStep: 4,
      completedSteps: [0, 1, 2, 3, 4],
    });
    clearExperimentDraft(SECOND_ID);

    const workspaces = listExperimentWorkspaces(OWNER_A);
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
      name: "Temporary",
      source: "manual",
    });
    expect(listExperimentWorkspaces(OWNER_A)).toHaveLength(1);

    clearExperimentDraft(FIRST_ID);

    expect(listExperimentWorkspaces(OWNER_A)).toEqual([]);
  });

  it("scopes active names by account and releases them after archive", () => {
    saveWorkspaceDraft(FIRST_ID, "Wind Study");
    registerExperimentWorkspace({
      id: FIRST_ID,
      ownerId: OWNER_A,
      name: "Wind Study",
      source: "manual",
    });

    expect(isExperimentWorkspaceNameAvailable(OWNER_A, " wind   study ")).toBe(false);
    expect(isExperimentWorkspaceNameAvailable(OWNER_B, "Wind Study")).toBe(true);
    expect(
      isExperimentWorkspaceNameAvailable(OWNER_A, "Wind Study", FIRST_ID),
    ).toBe(true);

    updateExperimentWorkspace(OWNER_A, FIRST_ID, { archived: true });
    expect(isExperimentWorkspaceNameAvailable(OWNER_A, "WIND STUDY")).toBe(true);
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
        name,
        source: "manual",
      });
      updateExperimentWorkspace(OWNER_A, id, { pinned, order });
    }

    expect(
      reorderExperimentWorkspace(OWNER_A, "experiment-normal-a", 1)
        .map((workspace) => [workspace.name, workspace.pinned]),
    ).toEqual([
      ["Pinned A", true],
      ["Normal", true],
      ["Pinned B", true],
    ]);
    expect(
      listExperimentWorkspaces(OWNER_A)
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

    expect(listExperimentWorkspaces(OWNER_A)).toEqual([]);
  });
});
