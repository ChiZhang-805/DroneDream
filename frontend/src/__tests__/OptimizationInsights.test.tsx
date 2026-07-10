import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptimizationInsights } from "../components/OptimizationInsights";
import type { OptimizationHistory } from "../types/api";

const history: OptimizationHistory = {
  pareto_candidate_ids: ["candidate-balanced", "candidate-robust"],
  recommendations: {
    balanced: "candidate-balanced",
    robust: "candidate-robust",
  },
  objective_directions: {
    rmse: "minimize",
    pass_flag: "maximize",
  },
  items: [
    {
      id: "baseline",
      generation_index: 0,
      source_type: "baseline",
      label: "Baseline",
      parameters: {},
      proposal_reason: null,
      parent_candidate_id: null,
      aggregated_score: 2.4,
      aggregated_metrics: { rmse: 1.2 },
      objective_values: { rmse: 1.2, pass_flag: 0.75 },
      feasible: false,
      total_constraint_violation: 0.05,
      trial_count: 4,
      completed_trial_count: 4,
      failed_trial_count: 0,
      rank_in_job: 3,
      is_best: false,
      is_baseline: true,
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
    },
    {
      id: "candidate-balanced",
      generation_index: 1,
      source_type: "optimizer",
      label: "Balanced",
      parameters: { MPC_XY_P: 1.05 },
      proposal_reason: "lower tracking error",
      parent_candidate_id: "baseline",
      aggregated_score: 1.4,
      aggregated_metrics: { rmse: 0.7 },
      objective_values: { rmse: 0.7, pass_flag: 0.9 },
      feasible: true,
      total_constraint_violation: 0,
      trial_count: 4,
      completed_trial_count: 4,
      failed_trial_count: 0,
      rank_in_job: 1,
      is_best: true,
      is_baseline: false,
      created_at: "2026-07-10T00:01:00Z",
      updated_at: "2026-07-10T00:01:00Z",
    },
    {
      id: "candidate-robust",
      generation_index: 2,
      source_type: "optimizer",
      label: "Robust",
      parameters: { MPC_XY_P: 0.9 },
      proposal_reason: "higher holdout pass rate",
      parent_candidate_id: "candidate-balanced",
      aggregated_score: 1.5,
      aggregated_metrics: { rmse: 0.8 },
      objective_values: { rmse: 0.8, pass_flag: 1 },
      feasible: true,
      total_constraint_violation: 0,
      trial_count: 4,
      completed_trial_count: 4,
      failed_trial_count: 0,
      rank_in_job: 2,
      is_best: false,
      is_baseline: false,
      created_at: "2026-07-10T00:02:00Z",
      updated_at: "2026-07-10T00:02:00Z",
    },
  ],
};

describe("OptimizationInsights", () => {
  it("prefers backend multi-objective history and renders its Pareto recommendations", () => {
    render(<OptimizationInsights trials={[]} history={history} />);

    expect(screen.getByRole("img", { name: /multi-objective candidate Pareto front/i })).toBeInTheDocument();
    expect(screen.getByText(/Backend Pareto front/i)).toBeInTheDocument();
    expect(screen.getAllByText(/balanced/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/robust/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pareto")).toHaveLength(2);
  });

  it("shows an explicit empty state before completed evidence exists", () => {
    render(<OptimizationInsights trials={[]} />);
    expect(screen.getByTestId("optimization-insights-empty")).toHaveTextContent(
      /No completed candidate metrics/i,
    );
  });
});
