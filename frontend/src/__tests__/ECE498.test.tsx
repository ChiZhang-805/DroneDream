import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { I18nProvider } from "../i18n/I18nProvider";
import { ECE498 } from "../pages/ECE498";

function renderCourse(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <ECE498 />
    </I18nProvider>,
  );
}

describe("ECE498 course tribute", () => {
  afterEach(() => {
    window.localStorage.removeItem("drone-dream:locale");
  });

  it("renders the English course story, gratitude, and seven-stage timeline", () => {
    renderCourse("en");

    expect(
      screen.getByRole("heading", { name: /ECE 498 BH.*LLM Reasoning for Engineering/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Professor Bin Hu" })).toBeInTheDocument();
    expect(screen.getByText(/harness engineering/i)).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(7);
    expect(screen.queryByText("特别致谢")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run Baseline/i })).not.toBeInTheDocument();
  });

  it("renders a fully separate Chinese copy set", () => {
    renderCourse("zh-CN");

    expect(
      screen.getByRole("heading", { name: /ECE 498 BH.*大语言模型在工程推理中的应用/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "胡斌教授" })).toBeInTheDocument();
    expect(screen.getByText(/一段学生亲历的课堂记忆/)).toBeInTheDocument();
    expect(screen.getByText(/harness engineering/i)).toBeInTheDocument();
    expect(
      screen.queryByText("From plausible answers to verified engineering systems"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("WITH DEEP GRATITUDE")).not.toBeInTheDocument();
  });

  it("switches the evidence panel on hover, focus, and click", () => {
    renderCourse("en");
    const panel = screen.getByRole("tabpanel");
    const productTab = screen.getByRole("tab", { name: /DRONEDREAM/i });

    expect(productTab).toHaveAttribute("aria-selected", "true");
    expect(
      within(panel).getByRole("heading", { name: "Make the verified loop usable" }),
    ).toBeInTheDocument();

    const hw2Tab = screen.getByRole("tab", { name: /HW2/i });
    fireEvent.mouseEnter(hw2Tab);
    expect(hw2Tab).toHaveAttribute("aria-selected", "true");
    expect(
      within(panel).getByRole("heading", { name: "Put the answer inside an engineering loop" }),
    ).toBeInTheDocument();

    const hw1Tab = screen.getByRole("tab", { name: /HW1/i });
    fireEvent.focus(hw1Tab);
    expect(hw1Tab).toHaveAttribute("aria-selected", "true");

    const hw5Tab = screen.getByRole("tab", { name: /HW5/i });
    fireEvent.click(hw5Tab);
    expect(hw5Tab).toHaveAttribute("aria-selected", "true");
    expect(within(panel).getByText(/Memory is a soft prior, never proof/i)).toBeInTheDocument();
  });

  it("supports arrow, Home, and End navigation across the milestone tabs", () => {
    renderCourse("en");
    const tabs = screen.getAllByRole("tab");
    const productTab = tabs[6];

    productTab.focus();
    fireEvent.keyDown(productTab, { key: "ArrowRight" });
    expect(tabs[0]).toHaveFocus();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(tabs[0], { key: "End" });
    expect(tabs[6]).toHaveFocus();
    fireEvent.keyDown(tabs[6], { key: "Home" });
    expect(tabs[0]).toHaveFocus();
  });

  it("opens the extended professor tribute without crowding the one-screen overview", async () => {
    renderCourse("en");

    fireEvent.click(screen.getByRole("button", { name: "Read the classroom story" }));
    const dialog = screen.getByRole("dialog", {
      name: "Why Professor Hu's course stayed with me",
    });
    expect(within(dialog).getByText(/two readings about what was then still an unfamiliar idea/i))
      .toBeInTheDocument();
    expect(within(dialog).getByText(/PX4 and Gazebo execute/i)).toBeInTheDocument();
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Close classroom story" }),
    ).toHaveFocus());
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Close classroom story" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Close classroom story" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links only to the course and professor sources and labels the page as unofficial", () => {
    renderCourse("en");

    expect(screen.getByRole("link", { name: /Course website/i })).toHaveAttribute(
      "href",
      "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
    );
    expect(screen.getByRole("link", { name: /Professor Hu's homepage/i })).toHaveAttribute(
      "href",
      "https://binhu7.github.io/",
    );
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    }
    expect(screen.getByText(/not an official UIUC or course webpage/i)).toBeInTheDocument();
  });
});
