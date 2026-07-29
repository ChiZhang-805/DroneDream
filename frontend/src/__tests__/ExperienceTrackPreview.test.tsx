import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("3 m")).toBeVisible();
    expect(screen.getByText(/no Job created/i)).toBeVisible();
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
  });
});
