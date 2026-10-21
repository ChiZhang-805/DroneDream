import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComparisonChart } from "../components/ComparisonChart";
import type { ComparisonPoint } from "../types/api";

describe("ComparisonChart", () => {
  it.each([NaN, Infinity, -Infinity])("does not turn missing measurement %s into a winner", (value) => {
    const { container } = render(<ComparisonChart data={[{
      metric: "distance", label: "Distance", baseline: value, optimized: 1,
      lower_is_better: true, unit: "m",
    }]} />);
    expect(container.querySelectorAll(".bar-winner")).toHaveLength(0);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect((container.querySelector(".bar-baseline") as HTMLElement).style.width).toBe("0%");
    expect((container.querySelector(".bar-optimized") as HTMLElement).style.width).toBe("100%");
  });
  it("forces score to lower-is-better even when payload says otherwise", () => {
    const points: ComparisonPoint[] = [
      {
        metric: "score",
        label: "Score",
        baseline: 5,
        optimized: 4,
        lower_is_better: false,
        unit: null,
      },
    ];

    const { container } = render(<ComparisonChart data={points} />);
    expect(screen.getByText(/lower is better/i)).toBeInTheDocument();

    const optimizedBar = container.querySelector(".bar-optimized");
    expect(optimizedBar?.className).toContain("bar-winner");
  });
});
