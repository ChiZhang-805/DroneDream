import { fireEvent, render, screen, within } from "@testing-library/react";
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

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fixed scenario library", () => {
  it("presents four compact common scenarios without creating a job", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob");
    const { router } = renderPage();

    expect(screen.getByRole("heading", { name: "Fixed Scenario Lab" })).toBeVisible();
    expect(screen.getAllByText("Simple")).toHaveLength(2);
    expect(screen.getAllByText("Medium")).toHaveLength(2);
    expect(document.querySelectorAll("[data-template-key]")).toHaveLength(4);
    expect(screen.queryByText("PX4 / GAZEBO STUDY")).not.toBeInTheDocument();
    expect(screen.queryByText("Scenario catalog v1")).not.toBeInTheDocument();
    expect(screen.queryByText(/Choose a common flight study/i)).not.toBeInTheDocument();
    expect(screen.queryByText("hover-basics@1")).not.toBeInTheDocument();
    expect(screen.queryByText("Vertical climb and stationary hover")).not.toBeInTheDocument();
    expect(screen.queryByText("Preview only")).not.toBeInTheDocument();
    expect(screen.queryByText(/generated points/i)).not.toBeInTheDocument();
    expect(screen.queryByText("What this tests")).not.toBeInTheDocument();

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

  it("renders independently authored Simplified Chinese scenario copy", () => {
    const { router } = renderPage("zh-CN");

    expect(screen.getByRole("heading", { name: "固定场景体验" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "稳定悬停" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "风与传感器噪声圆形" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "使用这个场景" })).toHaveLength(4);
    router.dispose();
  });
});
