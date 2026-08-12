import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const supabaseMock = vi.hoisted(() => {
  const rpc = vi.fn();
  const deleteAuthorEq = vi.fn();
  const deleteTopicEq = vi.fn(() => ({ eq: deleteAuthorEq }));
  const deleteTopic = vi.fn(() => ({ eq: deleteTopicEq }));
  const from = vi.fn(() => ({ delete: deleteTopic }));
  return {
    client: {
      rpc,
      from,
      storage: { from: vi.fn() },
    },
    rpc,
    from,
    deleteTopic,
    deleteTopicEq,
    deleteAuthorEq,
  };
});

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: supabaseMock.client,
}));

import { CommunityPage } from "../site/CommunityPage";

function rpcResult(data: unknown[]) {
  return {
    abortSignal: vi.fn().mockResolvedValue({ data, error: null }),
  };
}

describe("CommunityPage public data loading", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/community/?view=all");
    supabaseMock.rpc.mockReset();
    supabaseMock.from.mockClear();
    supabaseMock.deleteTopic.mockClear();
    supabaseMock.deleteTopicEq.mockClear();
    supabaseMock.deleteAuthorEq.mockReset();
    supabaseMock.deleteAuthorEq.mockResolvedValue({ error: null });
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_list_comments") return rpcResult([]);
      return rpcResult([
        {
          id: "00000000-0000-0000-0000-000000000001",
          author_id: "00000000-0000-0000-0000-000000000002",
          author_name: "Pilot",
          title: "Stable hover evidence",
          body: "The full reproducible test description.",
          tags: ["PX4"],
          image_urls: [],
          created_at: "2026-07-25T12:00:00Z",
          comment_count: 4,
          like_count: 7,
          liked_by_viewer: false,
        },
      ]);
    });
  });

  it("loads a bounded topic page with database-side counts", async () => {
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    expect(await screen.findByRole("heading", {
      name: "Stable hover evidence",
    })).toBeVisible();
    expect(supabaseMock.rpc).toHaveBeenCalledWith(
      "community_list_topics",
      expect.objectContaining({ p_offset: 0, p_limit: 25 }),
    );
    expect(screen.getByText("7")).toBeVisible();
    expect(screen.getByText("4")).toBeVisible();
  });

  it("loads only the selected topic's comments when opening a discussion", async () => {
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );
    const open = await screen.findByRole("button", {
      name: "Open discussion: Stable hover evidence",
    });
    fireEvent.click(open);

    await waitFor(() =>
      expect(supabaseMock.rpc).toHaveBeenCalledWith(
        "community_list_comments",
        expect.objectContaining({
          p_topic_id: "00000000-0000-0000-0000-000000000001",
          p_offset: 0,
          p_limit: 101,
        }),
      )
    );
  });

  it("shows the cancel action and commits a custom tag with Enter", async () => {
    render(
      <CommunityPage
        locale="en"
        account={{
          id: "00000000-0000-0000-0000-000000000003",
          email: "pilot@example.com",
          displayName: "Pilot",
          avatarUrl: null,
        }}
        onRequireAccount={vi.fn()}
      />,
    );

    await screen.findByRole("heading", { name: "Stable hover evidence" });
    fireEvent.click(screen.getAllByRole("button", { name: "Create a topic" })[0]);

    expect(screen.getByRole("button", { name: "Cancel" })).toBeVisible();
    expect(screen.getByPlaceholderText(
      "Describe the aircraft, route, parameters, observed result, evidence already checked, and the exact comparison you want the community to review.",
    )).toBeVisible();

    const customTag = screen.getByPlaceholderText("Add a custom tag");
    fireEvent.change(customTag, { target: { value: "Wind tunnel" } });
    fireEvent.keyDown(customTag, { key: "Enter" });

    expect(screen.getByRole("button", { name: "# Wind tunnel" })).toHaveClass("is-active");
    expect(customTag).toHaveValue("");
  });

  it("lets only the topic owner delete a topic", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <CommunityPage
        locale="en"
        account={{
          id: "00000000-0000-0000-0000-000000000002",
          email: "pilot@example.com",
          displayName: "Pilot",
          avatarUrl: null,
        }}
        onRequireAccount={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", {
      name: "Stable hover evidence",
    })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Delete topic" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", {
        name: "Stable hover evidence",
      })).not.toBeInTheDocument()
    );
    expect(supabaseMock.from).toHaveBeenCalledWith("community_topics");
    expect(supabaseMock.deleteTopicEq).toHaveBeenCalledWith(
      "id",
      "00000000-0000-0000-0000-000000000001",
    );
    expect(supabaseMock.deleteAuthorEq).toHaveBeenCalledWith(
      "author_id",
      "00000000-0000-0000-0000-000000000002",
    );
    confirm.mockRestore();
  });
});
