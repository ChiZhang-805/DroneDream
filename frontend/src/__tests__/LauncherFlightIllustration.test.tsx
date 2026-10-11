import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LauncherFlightIllustration } from "../components/LauncherFlightIllustration";

describe("LauncherFlightIllustration", () => {
  it("renders a lightweight route illustration without WebGL or a canvas", () => {
    const { container } = render(
      <LauncherFlightIllustration
        active
        description="Runtime preparation continues in the background."
        progress={45}
        title="Autonomous flight, ready when you are"
      />,
    );

    expect(screen.getByRole("heading", { name: "Autonomous flight, ready when you are" }))
      .toBeInTheDocument();
    expect(container.querySelector("svg.launcher-flight-map")).toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    expect(container.querySelector(".drone-launch-scene")).not.toBeInTheDocument();
    expect(container.querySelector(".launcher-flight-illustration"))
      .toHaveAttribute("data-progress", "45");
  });

  it("clamps progress before drawing the route", () => {
    const { container, rerender } = render(
      <LauncherFlightIllustration description="Description" progress={-8} title="Title" />,
    );
    expect(container.querySelector(".launcher-flight-illustration"))
      .toHaveAttribute("data-progress", "0");

    rerender(
      <LauncherFlightIllustration description="Description" progress={140} title="Title" />,
    );
    expect(container.querySelector(".launcher-flight-illustration"))
      .toHaveAttribute("data-progress", "100");
  });
});
