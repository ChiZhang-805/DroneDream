import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LauncherFlightIllustration } from "../components/LauncherFlightIllustration";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

describe("LauncherFlightIllustration", () => {
  it.each([
    ["universal", "launcher-campus-universal.png"],
    ["sim", "launcher-campus-sim.png"],
    ["lab", "launcher-campus-lab.png"],
    ["field", "launcher-campus-field.png"],
    ["autonomy", "launcher-campus.png"],
  ] as const)("uses the approved %s raster variant without procedural drawing", (edition, filename) => {
    const { container } = render(
      <EditionThemeProvider edition={edition}>
        <LauncherFlightIllustration
          active
          description="Runtime preparation continues in the background."
          progress={45}
          title="Autonomous flight, ready when you are"
        />
      </EditionThemeProvider>,
    );

    expect(screen.getByRole("region", { name: "Autonomous flight, ready when you are" }))
      .toBeInTheDocument();
    expect(container.querySelector("img.launcher-flight-image"))
      .toHaveAttribute("src", expect.stringContaining(filename));
    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    expect(container.querySelector(".drone-launch-scene")).not.toBeInTheDocument();
    expect(container.querySelector(".launcher-flight-illustration"))
      .toHaveAttribute("data-progress", "45");
  });

  it("clamps progress metadata", () => {
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
