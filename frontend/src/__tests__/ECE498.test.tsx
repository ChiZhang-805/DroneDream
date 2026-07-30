import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { I18nProvider } from "../i18n/I18nProvider";
import { ECE498 } from "../pages/ECE498";
import { lastLineOccupancy, renderedLineCount } from "../pages/ece498Layout";

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
    vi.restoreAllMocks();
  });

  it("measures paragraph line fragments without per-character layout reads", () => {
    const selectNodeContents = vi.fn();
    const getClientRects = vi.fn(() => [
      new DOMRect(0, 0, 100, 16),
      new DOMRect(0, 16, 84, 16),
    ]);
    const range = {
      selectNodeContents,
      getClientRects,
    } as unknown as Range;
    vi.spyOn(document, "createRange").mockReturnValue(range);
    const paragraph = document.createElement("p");
    paragraph.textContent = "A paragraph long enough to wrap onto two measured lines.";
    Object.defineProperty(paragraph, "clientWidth", { value: 100 });

    expect(lastLineOccupancy(paragraph)).toBe(0.84);
    expect(selectNodeContents).toHaveBeenCalledTimes(1);
    expect(getClientRects).toHaveBeenCalledTimes(1);
  });

  it("counts distinct rendered lines without relying on fixed heights or clipping", () => {
    const selectNodeContents = vi.fn();
    const getClientRects = vi.fn(() => [
      new DOMRect(0, 0, 100, 16),
      new DOMRect(0, 16, 100, 16),
      new DOMRect(0, 32, 72, 16),
    ]);
    vi.spyOn(document, "createRange").mockReturnValue({
      selectNodeContents,
      getClientRects,
    } as unknown as Range);
    const paragraph = document.createElement("p");
    paragraph.textContent = "Three real rendered lines.";

    expect(renderedLineCount(paragraph)).toBe(3);
    expect(selectNodeContents).toHaveBeenCalledTimes(1);
    expect(getClientRects).toHaveBeenCalledTimes(1);
  });

  it.each(["en", "zh-CN"] as const)(
    "renders four unclipped nine-line targets for every %s stage",
    (locale) => {
      renderCourse(locale);
      const tabs = screen.getAllByRole("tab");
      expect(tabs).toHaveLength(7);

      for (const tab of tabs) {
        fireEvent.click(tab);
        const panel = screen.getByRole("tabpanel");
        const cards = panel.querySelectorAll(".ece498-stage-copy-section");
        const bodies = panel.querySelectorAll<HTMLParagraphElement>(
          ".ece498-stage-body[data-target-lines=\"9\"]",
        );
        expect(cards).toHaveLength(4);
        expect(bodies).toHaveLength(4);
        for (const body of bodies) {
          expect(body.textContent?.trim().length).toBeGreaterThan(
            locale === "en" ? 75 : 45,
          );
          expect(body.querySelector("br")).toBeNull();
        }
      }
    },
  );

  it("renders a one-line English course introduction and seven-stage timeline", () => {
    renderCourse("en");

    expect(
      screen.getByRole("heading", { name: /ECE498BH.*LLM Reasoning for Engineering/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Professor Bin Hu" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read the classroom story" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(7);
    expect(screen.queryByText("特别致谢")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run Baseline/i })).not.toBeInTheDocument();
  });

  it("renders a fully separate Chinese copy set", () => {
    renderCourse("zh-CN");

    expect(
      screen.getByRole("heading", { name: /ECE498BH.*大语言模型在工程推理中的应用/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "胡斌教授" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开这段课堂故事" })).toBeInTheDocument();
    expect(
      screen.queryByText("From plausible answers to verified engineering systems"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("WITH DEEP GRATITUDE")).not.toBeInTheDocument();
  });

  it("keeps milestone details stable until a milestone is selected", () => {
    renderCourse("en");
    const panel = screen.getByRole("tabpanel");
    const productTab = screen.getByRole("tab", { name: /DRONEDREAM/i });

    expect(productTab).toHaveAttribute("aria-selected", "true");
    expect(
      within(panel).getByRole("heading", { name: "Make the verified loop usable" }),
    ).toBeInTheDocument();

    const hw2Tab = screen.getByRole("tab", { name: /HW2/i });
    fireEvent.mouseEnter(hw2Tab);
    expect(productTab).toHaveAttribute("aria-selected", "true");

    const hw1Tab = screen.getByRole("tab", { name: /HW1/i });
    fireEvent.focus(hw1Tab);
    expect(productTab).toHaveAttribute("aria-selected", "true");

    const hw5Tab = screen.getByRole("tab", { name: /HW5/i });
    fireEvent.click(hw5Tab);
    expect(hw5Tab).toHaveAttribute("aria-selected", "true");
    expect(
      within(panel).getByRole("heading", {
        name: "Remember experience, distrust bad memory",
      }),
    ).toBeInTheDocument();
    expect(within(panel).getByText("What this stage changed")).toBeInTheDocument();
    expect(within(panel).getByText("Measured evidence")).toBeInTheDocument();
    expect(within(panel).getByText("Engineering method")).toBeInTheDocument();
    expect(within(panel).getByText("Boundary to retain")).toBeInTheDocument();
    expect(panel.querySelector(".ece498-stage-flow")).not.toBeInTheDocument();
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
      name: "Professor Bin Hu",
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

  it("keeps only the course website icon and removes the redundant footer links", () => {
    renderCourse("en");

    expect(screen.getByRole("link", { name: /Course website/i })).toHaveAttribute(
      "href",
      "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
    );
    expect(screen.queryByRole("link", { name: /Professor Hu's homepage/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Beyond drones, the method travels/i)).not.toBeInTheDocument();
    expect(document.querySelector(".ece498-node-index")).not.toBeInTheDocument();
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    }
    expect(screen.queryByText(/not an official UIUC or course webpage/i)).not.toBeInTheDocument();
  });
});
