import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import { I18nProvider } from "../i18n/I18nProvider";
import { FixedScenarios } from "../pages/FixedScenarios";

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  const router = createMemoryRouter([
    { path: "/scenarios", element: <FixedScenarios /> },
    { path: "/jobs/new", element: <LocationProbe /> },
  ], { initialEntries: ["/scenarios"] });
  const result = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...result, router };
}

const originalInnerWidth = window.innerWidth;

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
    writable: true,
  });
  fireEvent(window, new Event("resize"));
}

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(2048);
});

afterEach(() => {
  setViewportWidth(originalInnerWidth);
  vi.restoreAllMocks();
});

describe("fixed scenario library", () => {
  it("presents compact common scenarios in switchable groups without creating a job", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob");
    const { router } = renderPage();

    expect(screen.getByRole("heading", { name: "Fixed Scenario Lab" })).toBeVisible();
    expect(document.querySelectorAll(".fixed-scenario-difficulty")).toHaveLength(4);
    expect(document.querySelectorAll(".fixed-scenario-simple")).toHaveLength(2);
    expect(document.querySelectorAll(".fixed-scenario-medium")).toHaveLength(2);
    expect(document.querySelectorAll("[data-template-key]")).toHaveLength(4);
    expect(screen.queryByText("PX4 / GAZEBO STUDY")).not.toBeInTheDocument();
    expect(screen.queryByText("Scenario catalog v1")).not.toBeInTheDocument();
    expect(screen.queryByText(/Choose a common flight study/i)).not.toBeInTheDocument();
    expect(screen.queryByText("hover-basics@1")).not.toBeInTheDocument();
    expect(screen.queryByText("Vertical climb and stationary hover")).not.toBeInTheDocument();
    expect(screen.queryByText("Preview only")).not.toBeInTheDocument();
    expect(screen.queryByText(/generated points/i)).not.toBeInTheDocument();
    expect(screen.queryByText("What this tests")).not.toBeInTheDocument();

    const hoverCard = screen.getByRole("heading", { name: "Stable hover" }).closest("article");
    expect(hoverCard).not.toBeNull();
    expect(within(hoverCard as HTMLElement).getAllByRole("term")).toHaveLength(6);
    expect(within(hoverCard as HTMLElement).getAllByRole("definition")).toHaveLength(6);
    const preview = (hoverCard as HTMLElement).querySelector(".scenario-track-preview");
    expect(preview).toHaveAttribute("data-view", "xy");
    for (const view of ["XZ", "YZ", "3D"] as const) {
      const button = within(hoverCard as HTMLElement).getByRole("button", {
        name: `${view} view`,
      });
      fireEvent.click(button);
      expect(preview).toHaveAttribute("data-view", view.toLowerCase());
      expect(button).toHaveAttribute("aria-pressed", "true");
    }

    fireEvent.click(screen.getByRole("button", { name: "Show next scenarios" }));
    expect(document.querySelectorAll("[data-template-key]")).toHaveLength(4);
    expect(screen.getByRole("heading", { name: "Precision hover" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Crosswind figure eight" })).toBeVisible();
    expect(screen.getByText("2 / 2")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Show previous scenarios" }));
    expect(screen.getByRole("heading", { name: "Stable hover" })).toBeVisible();
    expect(screen.getByText("1 / 2")).toBeVisible();

    const combinedCard = screen.getByRole("heading", {
      name: "Wind and sensor-noise circle",
    }).closest("article");
    expect(combinedCard).not.toBeNull();
    const useLink = within(combinedCard as HTMLElement).getByRole("link", {
      name: /Use this scenario/i,
    });
    expect(useLink).toHaveAttribute(
      "href",
      "/jobs/new?scenario=wind-sensor-circle%401",
    );
    fireEvent.click(useLink);
    expect(await screen.findByLabelText("location"))
      .toHaveTextContent("/jobs/new?scenario=wind-sensor-circle%401");
    expect(createSpy).not.toHaveBeenCalled();
    router.dispose();
  });

  it("adapts each scenario group to four, three, two, or one card without leaving a partial row", async () => {
    setViewportWidth(1440);
    const { router } = renderPage();
    expect(document.querySelectorAll("[data-template-key]")).toHaveLength(3);
    expect(screen.getByText("1 / 3")).toBeVisible();

    setViewportWidth(760);
    await waitFor(() => {
      expect(document.querySelectorAll("[data-template-key]")).toHaveLength(2);
      expect(screen.getByText("1 / 4")).toBeVisible();
    });

    setViewportWidth(390);
    await waitFor(() => {
      expect(document.querySelectorAll("[data-template-key]")).toHaveLength(1);
      expect(screen.getByText("1 / 8")).toBeVisible();
    });

    setViewportWidth(2048);
    await waitFor(() => {
      expect(document.querySelectorAll("[data-template-key]")).toHaveLength(4);
      expect(screen.getByText("1 / 2")).toBeVisible();
    });
    router.dispose();
  });

  it("renders independently authored Simplified Chinese scenario copy", () => {
    const { router } = renderPage("zh-CN");

    expect(screen.getByRole("heading", { name: "固定场景体验" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "稳定悬停" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "风与传感器噪声圆形" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "使用这个场景" })).toHaveLength(4);
    router.dispose();
  });
});
