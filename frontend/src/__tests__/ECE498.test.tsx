import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "../AppShell";
import {
  ECE498,
  buildEce498JobRequest,
  summarizeCandidateTurns,
  type Ece498FormState,
} from "../pages/ECE498";
import type { Trial } from "../types/api";

const form: Ece498FormState = {
  display_name: "",
  track_type: "circle",
  reference_track_json: "",
  start_x: "0",
  start_y: "0",
  altitude_m: "3",
  baseline_kp_xy: "1",
  baseline_kd_xy: "0.2",
  baseline_ki_xy: "0.05",
  baseline_vel_limit: "5",
  baseline_accel_limit: "4",
  baseline_disturbance_rejection: "0.5",
  circle_radius_m: "5",
  u_turn_straight_length_m: "10",
  u_turn_turn_radius_m: "3",
  lemniscate_scale_m: "4",
  wind_north: "0",
  wind_east: "0",
  wind_south: "0",
  wind_west: "0",
  sensor_noise_level: "medium",
  objective_profile: "robust",
  advanced_scenario_config_json: "",
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
  simulator_backend: "mock",
};

function mkTrial(overrides: Partial<Trial>): Trial {
  return {
    id: "t1",
    job_id: "j1",
    candidate_id: "c1",
    seed: 1,
    scenario_type: "nominal",
    status: "COMPLETED",
    score: 1,
    pass_flag: true,
    candidate_label: "cand",
    candidate_source_type: "baseline",
    candidate_is_baseline: true,
    candidate_is_best: false,
    candidate_generation_index: 0,
    attempt_count: 1,
    worker_id: null,
    simulator_backend: "mock",
    failure_code: null,
    failure_reason: null,
    log_excerpt: null,
    metrics: {
      rmse: 0.3,
      max_error: 0.4,
      overshoot_count: 0,
      completion_time: 1,
      crash_flag: false,
      timeout_flag: false,
      score: 1,
      final_error: 0.1,
      pass_flag: true,
      instability_flag: false,
    },
    queued_at: null,
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe("ECE498", () => {
  it("renders three run buttons", () => {
    render(
      <MemoryRouter>
        <ECE498 />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: /Run Baseline \(No Tool\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Tool-Augmented \(CMA-ES\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Tool \+ Refinement \(CMA-ES Loop\)/i })).toBeInTheDocument();
  });

  it("shows empty results state before runs", () => {
    render(
      <MemoryRouter>
        <ECE498 />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Run one of the three modes to see results\./i)).toBeInTheDocument();
    expect(screen.queryByText("Candidate / Refinement Turns")).not.toBeInTheDocument();
    expect(screen.queryByText("Run Results")).not.toBeInTheDocument();
  });

  it("maps baseline mode to optimizer none", () => {
    expect(buildEce498JobRequest(form, "baseline_no_tool").optimizer_strategy).toBe("none");
  });

  it("maps tool_augmented to cma_es with max_iterations=1", () => {
    const req = buildEce498JobRequest(form, "tool_augmented");
    expect(req.optimizer_strategy).toBe("cma_es");
    expect(req.max_iterations).toBe(1);
  });

  it("maps tool_refinement to cma_es with max_iterations=3", () => {
    const req = buildEce498JobRequest(form, "tool_refinement");
    expect(req.optimizer_strategy).toBe("cma_es");
    expect(req.max_iterations).toBe(3);
  });

  it("builds generated track with more than 2 points for non-custom track", () => {
    const req = buildEce498JobRequest(form, "baseline_no_tool");
    expect((req.reference_track ?? []).length).toBeGreaterThan(2);
  });

  it("aggregates candidate turn metrics", () => {
    const trials: Trial[] = [
      mkTrial({ id: "t1", candidate_id: "c1", metrics: { ...mkTrial({}).metrics!, rmse: 0.3, score: 1 } }),
      mkTrial({ id: "t2", candidate_id: "c1", metrics: { ...mkTrial({}).metrics!, rmse: 0.5, score: 2 } }),
      mkTrial({ id: "t3", candidate_id: "c1", status: "FAILED", metrics: null, pass_flag: null }),
    ];
    const turns = summarizeCandidateTurns("baseline_no_tool", trials, form);
    expect(turns).toHaveLength(1);
    expect(turns[0].completedTrialCount).toBe(2);
    expect(turns[0].failedTrialCount).toBe(1);
    expect(turns[0].passingTrialCount).toBe(2);
    expect(turns[0].passRate).toBe(1);
    expect(turns[0].meanRmse).toBeCloseTo(0.4);
  });

  it("shows nav link label", () => {
    render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "ECE498" })).toBeInTheDocument();
  });
});
