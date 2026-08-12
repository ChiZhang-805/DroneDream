import {
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
    edition: "sim",
    name,
    source: "manual",
  });
  updateExperimentWorkspace(OWNER_ID, id, {
    status: "created",
    jobId,
    archived,
  }, "sim");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ExperimentWorkspaceSidebar", () => {
  it("does not crash on a malformed encoded job path", () => {
    render(
      <MemoryRouter initialEntries={["/jobs/%E0%A4%A"]}>
        <ExperimentWorkspaceSidebar ownerId={OWNER_ID} locale="en" edition="sim" />
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
        <ExperimentWorkspaceSidebar ownerId={OWNER_ID} locale="en" edition="sim" />
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
    expect(listExperimentWorkspaces(OWNER_ID, "sim")[0]?.name).toBe("Renamed experiment");
  });

  it("shows a persistent pin marker and previews a drag insertion before reordering", async () => {
    createWorkspace("workspace-pinned-a", "Pinned A", "job-pinned-a");
    createWorkspace("workspace-pinned-b", "Pinned B", "job-pinned-b");
    createWorkspace("workspace-normal", "Normal", "job-normal");
    updateExperimentWorkspace(OWNER_ID, "workspace-pinned-a", {
      pinned: true,
      order: 0,
    }, "sim");
    updateExperimentWorkspace(OWNER_ID, "workspace-pinned-b", {
      pinned: true,
      order: 1,
    }, "sim");
    updateExperimentWorkspace(OWNER_ID, "workspace-normal", {
      pinned: false,
      order: 2,
    }, "sim");
    render(
      <MemoryRouter>
        <ExperimentWorkspaceSidebar ownerId={OWNER_ID} locale="en" edition="sim" />
      </MemoryRouter>,
    );

    const pinnedRow = screen.getByText("Pinned A").closest(".app-workspace-row");
    expect(pinnedRow?.querySelector(".app-workspace-pinned-indicator"))
      .toBeInTheDocument();

    const rows = screen.getAllByText(/Pinned A|Pinned B|Normal/)
      .map((label) => label.closest<HTMLElement>(".app-workspace-row"))
      .filter((row): row is HTMLElement => Boolean(row));
    const byName = new Map(
      rows.map((row) => [row.textContent?.trim(), row]),
    );
    const pinnedA = byName.get("Pinned A");
    const pinnedB = byName.get("Pinned B");
    const normal = byName.get("Normal");
    if (!pinnedA || !pinnedB || !normal) {
      throw new Error("Expected workspace rows were not rendered.");
    }
    vi.spyOn(pinnedA, "getBoundingClientRect").mockReturnValue({
      top: 0,
      bottom: 38,
      left: 0,
      right: 220,
      width: 220,
      height: 38,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    vi.spyOn(pinnedB, "getBoundingClientRect").mockReturnValue({
      top: 40,
      bottom: 78,
      left: 0,
      right: 220,
      width: 220,
      height: 38,
      x: 0,
      y: 40,
      toJSON: () => ({}),
    });
    const dataTransfer = {
      effectAllowed: "none",
      dropEffect: "none",
      setData: vi.fn(),
      getData: vi.fn(),
    };

    fireEvent.dragStart(normal, { dataTransfer });
    const list = normal.closest(".app-workspace-list");
    if (!list) throw new Error("Workspace list was not rendered.");
    const dragOver = createEvent.dragOver(list, { dataTransfer });
    Object.defineProperty(dragOver, "clientY", { value: 45 });
    fireEvent(list, dragOver);
    expect(list.querySelector(".app-workspace-drop-preview")).toBeInTheDocument();
    expect(normal).toHaveClass("is-drag-source");
    fireEvent.drop(list, { clientY: 45, dataTransfer });

    await waitFor(() => {
      expect(list.querySelector(".app-workspace-drop-preview")).toBeNull();
      expect(listExperimentWorkspaces(OWNER_ID, "sim")
        .filter((workspace) => !workspace.archived)
        .map((workspace) => [workspace.name, workspace.pinned]))
        .toEqual([
          ["Pinned A", true],
          ["Normal", true],
          ["Pinned B", true],
        ]);
    });
  });
});

describe("ArchivedExperimentManager", () => {
  it("distinguishes removing a job link from permanently deleting a draft", async () => {
    createWorkspace("workspace-job", "Completed job", "job-complete", true);
    createWorkspace("workspace-draft", "Local draft", null, true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(
      <ArchivedExperimentManager ownerId={OWNER_ID} locale="en" edition="sim" />,
    );

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
    expect(listExperimentWorkspaces(OWNER_ID, "sim")).toHaveLength(2);

    confirm.mockReturnValue(true);
    await user.click(removeJob);
    expect(listExperimentWorkspaces(OWNER_ID, "sim").map((item) => item.id)).toEqual([
      "workspace-draft",
    ]);

    await user.click(
      screen.getByRole("button", { name: "Delete permanently: Local draft" }),
    );
    expect(confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("cannot be undone"),
    );
    expect(listExperimentWorkspaces(OWNER_ID, "sim")).toEqual([]);
  });
});
