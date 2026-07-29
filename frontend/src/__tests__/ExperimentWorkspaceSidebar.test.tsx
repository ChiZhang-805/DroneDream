import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import {
  ArchivedExperimentManager,
  ExperimentWorkspaceSidebar,
} from "../components/ExperimentWorkspaceSidebar";
import {
  listExperimentWorkspaces,
  registerExperimentWorkspace,
  updateExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

const OWNER_ID = "owner-sidebar-tests";

function createWorkspace(
  id: string,
  name: string,
  jobId: string | null,
  archived = false,
) {
  registerExperimentWorkspace({
    id,
    ownerId: OWNER_ID,
    name,
    source: "manual",
  });
  updateExperimentWorkspace(OWNER_ID, id, {
    status: "created",
    jobId,
    archived,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ExperimentWorkspaceSidebar", () => {
  it("does not crash on a malformed encoded job path", () => {
    render(
      <MemoryRouter initialEntries={["/jobs/%E0%A4%A"]}>
        <ExperimentWorkspaceSidebar ownerId={OWNER_ID} locale="en" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("region", { name: "Experiments" })).toBeInTheDocument();
  });

  it("submits a job rename only once when the button receives focus", async () => {
    createWorkspace("workspace-rename", "Original name", "job-rename");
    vi.spyOn(apiClient, "getJob").mockResolvedValue({
      control_version: 7,
    } as never);
    const updateJob = vi.spyOn(apiClient, "updateJob").mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/jobs/job-rename"]}>
        <ExperimentWorkspaceSidebar ownerId={OWNER_ID} locale="en" />
      </MemoryRouter>,
    );

    fireEvent.contextMenu(screen.getByText("Original name").closest(".app-workspace-row")!);
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename" });
    await user.clear(input);
    await user.type(input, "Renamed experiment");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() => expect(updateJob).toHaveBeenCalledOnce());
    expect(updateJob).toHaveBeenCalledWith(
      "job-rename",
      { display_name: "Renamed experiment" },
      7,
    );
    expect(listExperimentWorkspaces(OWNER_ID)[0]?.name).toBe("Renamed experiment");
  });
});

describe("ArchivedExperimentManager", () => {
  it("distinguishes removing a job link from permanently deleting a draft", async () => {
    createWorkspace("workspace-job", "Completed job", "job-complete", true);
    createWorkspace("workspace-draft", "Local draft", null, true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<ArchivedExperimentManager ownerId={OWNER_ID} locale="en" />);

    const removeJob = screen.getByRole("button", {
      name: "Remove: Completed job",
    });
    expect(
      screen.getByRole("button", { name: "Delete permanently: Local draft" }),
    ).toBeInTheDocument();
    await user.click(removeJob);
    expect(confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("job and trials will remain in History"),
    );
    expect(listExperimentWorkspaces(OWNER_ID)).toHaveLength(2);

    confirm.mockReturnValue(true);
    await user.click(removeJob);
    expect(listExperimentWorkspaces(OWNER_ID).map((item) => item.id)).toEqual([
      "workspace-draft",
    ]);

    await user.click(
      screen.getByRole("button", { name: "Delete permanently: Local draft" }),
    );
    expect(confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("cannot be undone"),
    );
    expect(listExperimentWorkspaces(OWNER_ID)).toEqual([]);
  });
});
