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
  isLongCommunityTopicTitle,
  packCommunityTopicPages,
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
      "community_list_topics_v2",
      expect.objectContaining({ p_offset: 0, p_limit: 50 }),
    );
    expect(screen.getByText("7")).toBeVisible();
    expect(screen.getByText("4")).toBeVisible();
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

    expect(await screen.findByRole("heading", { name: "Evidence topic 11" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Evidence topic 1" })).not.toBeInTheDocument();
  });

  it("shows exactly five featured cards on the community landing page", async () => {
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

    await screen.findByRole("button", { name: "Open discussion: Featured topic 1" });
    expect(container.querySelectorAll(".community-topic-grid article")).toHaveLength(5);
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

  it("classifies long titles and packs them as two visual units after page one", () => {
    expect(isLongCommunityTopicTitle("一二三四五六七八九十一二三四五六七八")).toBe(false);
    expect(isLongCommunityTopicTitle("一二三四五六七八九十一二三四五六七八九")).toBe(true);
    expect(isLongCommunityTopicTitle("1234567890123456789012345678")).toBe(false);
    expect(isLongCommunityTopicTitle("12345678901234567890123456789")).toBe(true);

    const topics = [
      ...Array.from({ length: 10 }, (_, index) => makeTopic(index + 1, `First page ${index + 1}`)),
      makeTopic(11, "Short ranked first"),
      makeTopic(12, "This title is deliberately longer than twenty eight characters"),
      ...Array.from({ length: 7 }, (_, index) => makeTopic(index + 13, `Short ${index + 2}`)),
    ];
    const pages = packCommunityTopicPages(topics);

    expect(pages).toHaveLength(2);
    expect(pages[0]).toHaveLength(10);
    expect(pages[0].every(({ isLong }) => !isLong)).toBe(true);
    expect(pages[1]).toHaveLength(9);
    expect(pages[1].map(({ topic }) => topic.id)).toEqual(
      topics.slice(10).map(({ id }) => id),
    );
    expect(pages[1][0].isLong).toBe(false);
    expect(pages[1][1].isLong).toBe(true);
    expect(pages[1].reduce((units, topic) => units + (topic.isLong ? 2 : 1), 0)).toBe(10);
  });

  it("uses the signed-in author's avatar and does not render a redundant owner badge", async () => {
    const avatarUrl = "data:image/png;base64,avatar";
    const { container } = render(
      <CommunityPage
        locale="en"
        account={{
          id: "00000000-0000-0000-0000-000000000002",
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
      name: "Open discussion: Stable hover evidence",
    }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector(".community-topic-author img")).toHaveAttribute("src", avatarUrl);
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
