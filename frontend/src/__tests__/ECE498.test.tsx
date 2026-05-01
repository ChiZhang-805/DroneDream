import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "../AppShell";
import { apiClient } from "../api/client";
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
  advanced_enabled: false,
  gust_enabled: false,
  gust_magnitude_mps: "0",
  gust_direction_deg: "0",
  gust_period_s: "10",
  gps_noise_m: "0",
  baro_noise_m: "0",
  imu_noise_scale: "1",
  dropout_rate: "0",
  battery_initial_percent: "100",
  battery_voltage_sag: false,
  mass_payload_kg: "",
  obstacles_json: "[]",
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


  it("renders extended config fields", () => {
    render(<MemoryRouter><ECE498 /></MemoryRouter>);
    expect(screen.getByLabelText("Wind North")).toBeInTheDocument();
    expect(screen.getByLabelText("Wind East")).toBeInTheDocument();
    expect(screen.getByLabelText("Wind South")).toBeInTheDocument();
    expect(screen.getByLabelText("Wind West")).toBeInTheDocument();
    expect(screen.getByLabelText("Sensor Noise Level")).toBeInTheDocument();
    expect(screen.getByLabelText("Objective Profile")).toBeInTheDocument();
    expect(screen.getByLabelText("Target Max Error")).toBeInTheDocument();
    expect(screen.getByLabelText("Min Pass Rate")).toBeInTheDocument();
    expect(screen.getByLabelText("Simulator Backend")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show Advanced scenario" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show Advanced scenario" }));
    expect(screen.getByLabelText("Enable advanced scenario")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable gust")).toBeInTheDocument();
    expect(screen.getByLabelText("Dropout rate")).toBeInTheDocument();
    expect(screen.getByLabelText("Obstacles JSON")).toBeInTheDocument();
    expect(screen.getByText("Example obstacles JSON")).toBeInTheDocument();
  });

  it("shows validation errors for invalid inputs", () => {
    render(<MemoryRouter><ECE498 /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("accel_limit"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Circle Radius (m)"), { target: { value: "abc" } });
    fireEvent.change(screen.getByLabelText("Min Pass Rate"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: /Run Baseline/i }));
    expect(screen.getByText(/accel_limit must be between 2 and 8/i)).toBeInTheDocument();
    expect(screen.getByText(/Circle radius must be between/i)).toBeInTheDocument();
    expect(screen.getByText(/Min pass rate must be between 0 and 1/i)).toBeInTheDocument();
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
  it("does not include advanced_scenario_config when advanced is disabled", () => {
    expect(buildEce498JobRequest(form, "baseline_no_tool").advanced_scenario_config).toBeNull();
  });
  it("builds advanced_scenario_config when advanced is enabled", () => {
    const req = buildEce498JobRequest({
      ...form, advanced_enabled: true, gust_enabled: true, dropout_rate: "0.2", baro_noise_m: "0.3", imu_noise_scale: "2", obstacles_json: "[]",
    }, "baseline_no_tool");
    expect(req.advanced_scenario_config?.sensor_degradation?.dropout_rate).toBe(0.2);
    expect(req.advanced_scenario_config?.sensor_degradation?.baro_noise_m).toBe(0.3);
    expect(req.advanced_scenario_config?.sensor_degradation?.imu_noise_scale).toBe(2);
  });
  it("blocks run when advanced enabled and obstacles JSON invalid", () => {
    const createSpy = vi.spyOn(apiClient, "createJob");
    render(<MemoryRouter><ECE498 /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Show Advanced scenario" }));
    fireEvent.change(screen.getByLabelText("Enable advanced scenario"), { target: { value: "yes" } });
    fireEvent.change(screen.getByLabelText("Obstacles JSON"), { target: { value: "{\"a\":1}" } });
    fireEvent.click(screen.getByRole("button", { name: /Run Baseline/i }));
    expect(screen.getByText(/Obstacles JSON must be a JSON array/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
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
      <MemoryRouter initialEntries={["/batches/new"]}>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "ECE498" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New Batch" })).toHaveClass("active");
    expect(screen.getByRole("link", { name: "Batches" })).not.toHaveClass("active");
  });
  it("sets batches nav active for /batches and /batches/:id", () => {
    const { rerender } = render(<MemoryRouter initialEntries={["/batches"]}><AppShell /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Batches" })).toHaveClass("active");
    rerender(<MemoryRouter initialEntries={["/batches/bat_123"]}><AppShell /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Batches" })).toHaveClass("active");
  });
});
