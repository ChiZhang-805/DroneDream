import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExperienceTrackPreview } from "../features/experiment/ExperienceTrackPreview";

const labels = {
  title: "Local track preview",
  hoverLabel: "Vertical climb and stationary hover",
  routeLabel: "Top-down route",
  pointCountLabel: "101 points",
  localOnlyLabel: "Preview only · no Job created",
};

describe("ExperienceTrackPreview", () => {
  it("renders hover as a vertical climb and stationary hold", () => {
    render(
      <ExperienceTrackPreview
        {...labels}
        trackType="hover"
        altitudeM={3}
        points={Array.from({ length: 101 }, () => ({ x: 0, y: 0, z: 3 }))}
      />,
    );

    expect(screen.getByTestId("hover-preview")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /3D view.*Vertical climb/i }))
      .toHaveAttribute("data-view", "3d");
    expect(screen.getByText(/no Job created/i)).toHaveClass("sr-only");
    expect(screen.queryByText("3 m")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    expect(screen.getByRole("img", { name: /XY view.*Vertical climb/i }))
      .toHaveAttribute("data-view", "xy");
    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    expect(screen.getByRole("img", { name: /XZ view.*Vertical climb/i }))
      .toHaveAttribute("data-view", "xz");
    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    expect(screen.getByRole("img", { name: /YZ view.*Vertical climb/i }))
      .toHaveAttribute("data-view", "yz");
    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    expect(screen.getByRole("img", { name: /3D view.*Vertical climb/i }))
      .toHaveAttribute("data-view", "3d");
  });

  it("renders a finite planar route when waypoint altitude is inherited", () => {
    render(
      <ExperienceTrackPreview
        {...labels}
        trackType="custom"
        altitudeM={3}
        points={[
          { x: 0, y: 0, z: null },
          { x: 5, y: 0, z: null },
          { x: 5, y: 5, z: null },
        ]}
      />,
    );

    expect(screen.getByTestId("route-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("hover-preview")).toBeNull();
    expect(screen.getByRole("group", { name: "Track view" })).toBeVisible();
  });
});
