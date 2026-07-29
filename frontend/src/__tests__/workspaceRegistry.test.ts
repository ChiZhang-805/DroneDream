import { beforeEach, describe, expect, it } from "vitest";

import { clearExperimentDraft, saveExperimentDraft } from "../features/experiment/draftStorage";
import {
  experimentWorkspacePath,
  listExperimentWorkspaces,
  registerExperimentWorkspace,
  updateExperimentWorkspace,
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
