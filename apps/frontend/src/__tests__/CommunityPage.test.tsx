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

import {
  CommunityPage,
  paginateCommunityTopics,
  type CommunityTopic,
} from "../site/CommunityPage";

function rpcResult(data: unknown) {
  return {
    abortSignal: vi.fn().mockResolvedValue({ data, error: null }),
  };
}

function makeTopic(index: number, title = `Topic ${index}`): CommunityTopic {
  return {
    id: `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    author_id: "00000000-0000-0000-0000-000000000002",
    author_name: "Pilot",
    title,
    body: "A compact evidence summary.",
    tags: ["PX4"],
    image_urls: [],
    created_at: "2026-07-25T12:00:00Z",
    comment_count: index,
    like_count: index,
    liked_by_viewer: false,
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
      if (name === "community_count_topics") return rpcResult(1);
      return rpcResult([
        {
          id: "00000000-0000-0000-0000-000000000001",
          author_id: "bc77348a-90e9-4c0c-92eb-9db31301cdbd",
          author_name: "cz91",
          author_avatar_url: "/chi-avatar.png",
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
    const { container } = render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    expect(await screen.findByRole("heading", {
      name: "Stable hover evidence",
    })).toBeVisible();
    expect(supabaseMock.rpc).toHaveBeenCalledWith(
      "community_list_topics_v2",
      expect.objectContaining({ p_offset: 0, p_limit: 50 }),
    );
    expect(screen.getByText("7")).toBeVisible();
    expect(screen.getByText("4")).toBeVisible();
    expect(screen.getByText("Chi Zhang")).toBeVisible();
    expect(container.querySelector(".community-topic-author img"))
      .toHaveAttribute("src", "/chi-avatar.png");
  });

  it("paginates the locally packed discovery topics without another server page request", async () => {
    const topics = Array.from({ length: 19 }, (_, index) =>
      makeTopic(index + 1, `Evidence topic ${index + 1}`)
    );
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_list_comments") return rpcResult([]);
      if (name === "community_count_topics") return rpcResult(topics.length);
      return rpcResult(topics);
    });
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    await screen.findByRole("heading", { name: "Evidence topic 1" });
    fireEvent.click(screen.getByRole("button", { name: "Page 2" }));

    expect(await screen.findByRole("heading", { name: "Evidence topic 6" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Evidence topic 1" })).not.toBeInTheDocument();
  });

  it("shows five uniform cards and pagination on the community landing page", async () => {
    window.history.replaceState(null, "", "/community/");
    const featuredTopics = Array.from({ length: 7 }, (_, index) => ({
      id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
      author_id: "00000000-0000-0000-0000-000000000002",
      author_name: "Pilot",
      title: `Featured topic ${index + 1}`,
      body: "A compact evidence summary.",
      tags: ["PX4"],
      image_urls: [],
      created_at: `2026-07-${String(25 - index).padStart(2, "0")}T12:00:00Z`,
      comment_count: index,
      like_count: index,
      liked_by_viewer: false,
    }));
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_list_comments") return rpcResult([]);
      return rpcResult(featuredTopics);
    });

    const { container } = render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    await screen.findByRole("button", { name: "Open card: Featured topic 1" });
    expect(container.querySelectorAll(".community-topic-grid article")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Page 2" })).toBeVisible();
  });

  it("shows the illustrated empty state while keeping the topic filters", async () => {
    window.history.replaceState(null, "", "/community/");
    supabaseMock.rpc.mockImplementation((name: string) => {
      if (name === "community_count_topics") return rpcResult(0);
      return rpcResult([]);
    });

    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );

    const illustration = await screen.findByRole("img", {
      name: "No topics yet. A child prepares a quadcopter beside a flight-planning chalkboard.",
    });
    expect(illustration).toHaveAttribute("src", "/community-empty-topics.webp");
    expect(screen.getByRole("button", { name: "# Simulation" })).toBeVisible();
    expect(screen.queryByText(/New English community cards/i)).not.toBeInTheDocument();
  });

  it("loads only the selected topic's comments when opening a discussion", async () => {
    render(
      <CommunityPage locale="en" account={null} onRequireAccount={vi.fn()} />,
    );
    const open = await screen.findByRole("button", {
      name: "Open card: Stable hover evidence",
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

  it("paginates every topic into the same five-card row", () => {
    const topics = Array.from({ length: 10 }, (_, index) => makeTopic(index + 1));
    const pages = paginateCommunityTopics(topics);

    expect(pages).toHaveLength(2);
    expect(pages.map((page) => page.length)).toEqual([5, 5]);
    expect(pages.flat().map(({ id }) => id)).toEqual(topics.map(({ id }) => id));
  });

  it("uses the signed-in author's avatar and does not render a redundant owner badge", async () => {
    const avatarUrl = "data:image/png;base64,avatar";
    const { container } = render(
      <CommunityPage
        locale="en"
        account={{
          id: "bc77348a-90e9-4c0c-92eb-9db31301cdbd",
          email: "pilot@example.com",
          displayName: "Pilot",
          avatarUrl,
        }}
        onRequireAccount={vi.fn()}
      />,
    );

    await screen.findByRole("heading", { name: "Stable hover evidence" });
    expect(container.querySelector(".community-topic-author img")).toHaveAttribute("src", avatarUrl);
    expect(screen.queryByText("Your topic")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: "Open card: Stable hover evidence",
    }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector(".community-topic-author img")).toHaveAttribute("src", avatarUrl);
    const dialogArtwork = dialog.querySelector(".community-topic-dialog-visual .community-cover-art");
    expect(dialogArtwork).toHaveClass("is-dialog");
    expect(dialogArtwork).not.toHaveClass("is-long");
  });

  it("lets only the topic owner delete a topic", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <CommunityPage
        locale="en"
        account={{
          id: "bc77348a-90e9-4c0c-92eb-9db31301cdbd",
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
      "bc77348a-90e9-4c0c-92eb-9db31301cdbd",
    );
    confirm.mockRestore();
  });
});
