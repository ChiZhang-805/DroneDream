import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComparisonChart } from "../components/ComparisonChart";
import type { ComparisonPoint } from "../types/api";

describe("ComparisonChart", () => {
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
