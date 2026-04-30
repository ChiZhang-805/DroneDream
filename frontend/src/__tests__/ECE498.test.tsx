import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "../AppShell";
import { ECE498, buildEce498JobRequest, type Ece498FormState } from "../pages/ECE498";

const form: Ece498FormState = {
  display_name: "",
  track_type: "circle", reference_track_json: "", start_x: "0", start_y: "0", altitude_m: "3",
  baseline_kp_xy: "1", baseline_kd_xy: "0.2", baseline_ki_xy: "0.05", baseline_vel_limit: "5", baseline_accel_limit: "4", baseline_disturbance_rejection: "0.5",
  circle_radius_m: "5", u_turn_straight_length_m: "10", u_turn_turn_radius_m: "3", lemniscate_scale_m: "4",
  wind_north: "0", wind_east: "0", wind_south: "0", wind_west: "0", sensor_noise_level: "medium",
  objective_profile: "robust", advanced_scenario_config_json: "", target_rmse: "0.5", target_max_error: "", min_pass_rate: "0.8", simulator_backend: "mock",
};

describe("ECE498", () => {
  it("renders three run buttons", () => {
    render(<MemoryRouter><ECE498 /></MemoryRouter>);
    expect(screen.getByRole("button", { name: /Run Baseline \(No Tool\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Tool-Augmented \(CMA-ES\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Tool \+ Refinement \(CMA-ES Loop\)/i })).toBeInTheDocument();
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

  it("shows nav link label", () => {
    render(<MemoryRouter><AppShell /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "ECE498" })).toBeInTheDocument();
  });
});
