import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

const topicFixture = {
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
};

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
      return rpcResult([topicFixture]);
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
    expect(screen.getByRole("button", { name: "7 likes" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    const tagFilter = screen.getByRole("button", { name: "#Simulation" });
    expect(tagFilter).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(tagFilter);
    expect(tagFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("searchbox", {
      name: "Search topics, evidence, or tags",
    })).toBeVisible();
  });

  it("shows an actionable empty state without a dead-end more link", async () => {
    window.history.replaceState(null, "", "/community/");
    supabaseMock.rpc.mockImplementation(() => rpcResult([]));
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    expect(await screen.findByText(
      "No topic matches this view. Start the first evidence-backed discussion.",
    )).toHaveAttribute("role", "status");
    expect(screen.queryByRole("link", { name: "More topics" })).toBeNull();
  });

  it("offers up to five recent topics for the responsive four-or-five-column shelf", async () => {
    window.history.replaceState(null, "", "/community/");
    const topics = Array.from({ length: 6 }, (_, index) => ({
      ...topicFixture,
      id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
      title: `Recent topic ${index + 1}`,
    }));
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_list_comments") return rpcResult([]);
      return rpcResult(topics);
    });

    const { container } = render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    expect(await screen.findByRole("heading", { name: "Recent topic 1" })).toBeVisible();
    expect(container.querySelectorAll(".community-topic-grid > article")).toHaveLength(5);
    expect(screen.queryByRole("heading", { name: "Recent topic 6" })).toBeNull();
    expect(screen.getByRole("link", { name: "More topics" })).toBeVisible();
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

    const customTag = screen.getByRole("textbox", { name: "Add a custom tag" });
    fireEvent.change(customTag, { target: { value: "Wind tunnel" } });
    fireEvent.keyDown(customTag, { key: "Enter" });

    expect(screen.getByRole("button", { name: "#Wind tunnel" })).toHaveClass("is-active");
    expect(screen.getByRole("button", { name: "#Wind tunnel" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
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

  it("uses the matched editorial cover and an icon-only comment submit control", async () => {
    const { container } = render(
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
    expect(container.querySelector('[data-template="evidence"]')).toBeVisible();
    const trigger = screen.getByRole("button", {
      name: "Open discussion: Stable hover evidence",
    });
    trigger.focus();
    fireEvent.click(trigger);

    await waitFor(() => expect(
      screen.getByRole("dialog", { name: "Stable hover evidence" }),
    ).toBeVisible());
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Close" }),
    ).toHaveFocus());
    const topicDialog = screen.getByRole("dialog", { name: "Stable hover evidence" });
    expect(topicDialog.querySelector(
      ".community-topic-dialog-visual > .community-cover-art",
    )).toBeVisible();
    expect(within(topicDialog).getByRole("textbox", {
      name: "Add a useful observation or a reproducible next step…",
    })).toBeVisible();
    const enabledTopicControls = Array.from(
      topicDialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(enabledTopicControls.at(-1)).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    const submit = screen.getByRole("button", { name: "Post comment" });
    expect(submit.querySelector("svg")).not.toBeNull();
    expect(submit).toHaveTextContent("Post comment");
    expect(submit.querySelector(".site-sr-only")).toHaveTextContent("Post comment");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Stable hover evidence" })).toBeNull();
      expect(trigger).toHaveFocus();
      expect(document.body.style.overflow).toBe("");
    });
  });

  it("announces discussion errors inside the active dialog", async () => {
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_list_comments") {
        return {
          abortSignal: vi.fn().mockResolvedValue({
            data: null,
            error: { message: "Comment service failed." },
          }),
        };
      }
      return rpcResult([topicFixture]);
    });
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("button", {
      name: "Open discussion: Stable hover evidence",
    }));
    const dialog = await screen.findByRole("dialog", {
      name: "Stable hover evidence",
    });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The community connection is temporarily unavailable.",
    );
  });

  it("treats the topic composer as a trapped modal and restores its trigger", async () => {
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

    const trigger = await screen.findByRole("button", { name: "Create a topic" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Create a topic" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(
      screen.getByRole("textbox", { name: "Topic title" }),
    ).toHaveFocus());
    const close = screen.getByRole("button", { name: "Close" });
    close.focus();
    const composerControls = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(composerControls.at(-1)).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Create a topic" })).toBeNull();
      expect(trigger).toHaveFocus();
      expect(document.body.style.overflow).toBe("");
    });
  });
});
