import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ArchivedConversationManager } from "../components/ArchivedConversationManager";
import {
  listExperimentWorkspaces,
  registerExperimentWorkspace,
  updateExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

const OWNER_ID = "owner-archived-conversation-tests";

function createConversation(
  id: string,
  name: string,
  jobId: string | null,
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
    archived: true,
  }, "sim");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ArchivedConversationManager", () => {
  it("uses conversation language while preserving completed job history", async () => {
    createConversation("conversation-job", "Completed tuning", "job-complete");
    createConversation("conversation-draft", "Local draft", null);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    render(
      <ArchivedConversationManager ownerId={OWNER_ID} locale="en" edition="sim" />,
    );

    expect(screen.getByRole("region", { name: "Archived conversations" }))
      .toBeInTheDocument();
    const removeJob = screen.getByRole("button", {
      name: "Remove: Completed tuning",
    });
    expect(
      screen.getByRole("button", { name: "Delete permanently: Local draft" }),
    ).toBeInTheDocument();

    await user.click(removeJob);
    expect(confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("from Conversations"),
    );
    expect(confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("job and trials will remain in History"),
    );
    expect(listExperimentWorkspaces(OWNER_ID, "sim")).toHaveLength(2);

    confirm.mockReturnValue(true);
    await user.click(removeJob);
    expect(listExperimentWorkspaces(OWNER_ID, "sim").map((item) => item.id)).toEqual([
      "conversation-draft",
    ]);

    await user.click(
      screen.getByRole("button", { name: "Delete permanently: Local draft" }),
    );
    expect(listExperimentWorkspaces(OWNER_ID, "sim")).toEqual([]);
  });
});
