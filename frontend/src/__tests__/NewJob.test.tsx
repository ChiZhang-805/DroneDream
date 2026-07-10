import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewJob } from "../pages/NewJob";
import { apiClient, ApiClientError } from "../api/client";
import type { Job } from "../types/api";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return { ...actual, useNavigate: () => navigateMock };
});
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewJob />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function openStep(name: RegExp): void {
  fireEvent.click(screen.getByRole("button", { name }));
}

function createExperiment(): void {
  fireEvent.click(screen.getByRole("button", { name: /Create Experiment/i }));
}

beforeEach(() => {
  navigateMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NewJob experiment wizard", () => {
  it("renders seven steps, three modes, and a safe non-GPT default", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: /New Tuning Experiment/i })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /Vehicle & PX4|Objective|Parameters|Scenarios|Flight track|Constraints & budget|Review/i })).toHaveLength(7);
    expect(screen.getByRole("radio", { name: /^Basic/i })).toHaveAttribute("aria-checked", "true");

    openStep(/Constraints & budget/i);
    expect(screen.getByLabelText(/Optimizer Strategy/i)).toHaveValue("heuristic");
    expect(screen.queryByLabelText(/LLM API Key/i)).toBeNull();
    expect(screen.getByLabelText(/Maximum total trials/i)).toHaveValue(100);
    expect(screen.getByLabelText(/Max Iterations/i)).toHaveAttribute("max", "100");
    expect(screen.getByLabelText(/Maximum total trials/i)).toHaveAttribute("max", "10000");
  });

  it("submits per-job Gazebo runtime controls for reproducible parallel runs", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_runtime" } as Job);
    renderPage();
    expect(screen.getByLabelText(/Disable Gazebo rendering/i)).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    fireEvent.change(screen.getByLabelText(/Simulation speed factor/i), {
      target: { value: "2.5" },
    });
    fireEvent.change(screen.getByLabelText(/PX4 instance ID/i), {
      target: { value: "7" },
    });

    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].vehicle_profile).toMatchObject({
      headless: true,
      simulation_speed_factor: 2.5,
      instance_id: 7,
    });
  });

  it("moves to the hidden field's step and surfaces validation errors", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();

    openStep(/Flight track/i);
    fireEvent.change(screen.getByLabelText(/Altitude/i), { target: { value: "25" } });
    openStep(/Vehicle & PX4/i);
    createExperiment();

    expect(await screen.findByText(/Must be between 1.0 and 20.0/i)).toBeVisible();
    expect(screen.getByLabelText(/Altitude/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("fails closed when the selected PX4 version has no matching parameter catalog", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    fireEvent.change(screen.getByLabelText(/PX4 Version/i), {
      target: { value: "v1.17" },
    });

    createExperiment();

    expect(await screen.findByText(/No compatible parameter catalog is loaded for PX4 v1.17/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("validates custom JSON and keeps it synchronized with the waypoint editor", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Flight track/i);

    fireEvent.change(screen.getByLabelText(/Track Type/i), { target: { value: "custom" } });
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: /Add waypoint/i }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: /Undo/i }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(3);

    fireEvent.change(screen.getByLabelText(/Reference track \(JSON\)/i), {
      target: { value: '[{"x":0,"y":0}]' },
    });
    createExperiment();
    expect(await screen.findByText(/Custom track requires at least 2 points/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("lets advanced users choose real PX4 dimensions and validates ranges", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Parameters/i);

    expect(screen.getByLabelText(/Tune MPC_XY_P/i)).toBeChecked();
    expect(screen.getByLabelText(/MPC_XY_P search minimum/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText(/MPC_XY_P search minimum/i), {
      target: { value: "1.4" },
    });
    fireEvent.change(screen.getByLabelText(/MPC_XY_P search maximum/i), {
      target: { value: "0.7" },
    });
    createExperiment();

    expect(await screen.findByText(/Search minimum must be less than maximum/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("applies objective profile weights and marks manual edits as custom", () => {
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Objective/i);

    fireEvent.click(screen.getByRole("button", { name: /^Fast/i }));
    expect(screen.getByLabelText(/Tracking accuracy weight/i)).toHaveValue(0.75);
    expect(screen.getByLabelText(/Completion speed weight/i)).toHaveValue(1);
    expect(screen.getByLabelText(/Robust aggregation/i)).toHaveValue("mean");

    fireEvent.change(screen.getByLabelText(/Completion speed weight/i), {
      target: { value: "0.9" },
    });
    expect(screen.getByLabelText(/Objective Profile/i)).toHaveValue("custom");
  });

  it("does not submit stale inactive tail-risk values", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_mean" } as Job);
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Objective/i);
    fireEvent.change(screen.getByLabelText(/CVaR alpha/i), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/Robust aggregation/i), {
      target: { value: "mean" },
    });

    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].objective_config).toMatchObject({
      robust_aggregation: "mean",
      cvar_alpha: 0.2,
      percentile: 95,
    });
  });

  it("keeps empty parameter inputs invalid instead of coercing them to zero", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Parameters/i);

    fireEvent.change(screen.getByLabelText(/MPC_XY_P search minimum/i), {
      target: { value: "" },
    });
    expect(screen.getByLabelText(/MPC_XY_P search minimum/i)).toHaveValue(null);
    createExperiment();

    expect(await screen.findByText(/must be finite numbers/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("surfaces and includes recommended companion parameters", () => {
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Parameters/i);

    fireEvent.change(screen.getByLabelText(/Find a PX4 parameter/i), {
      target: { value: "MC_ROLLRATE_I" },
    });
    fireEvent.click(screen.getByLabelText(/Tune MC_ROLLRATE_I/i));
    expect(screen.getByText(/Recommended companion parameters are not selected/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Include companions/i }));
    fireEvent.change(screen.getByLabelText(/Find a PX4 parameter/i), {
      target: { value: "" },
    });
    expect(screen.getByLabelText(/Tune MC_ROLLRATE_P/i)).toBeChecked();
  });

  it("rejects a budget that cannot run the baseline matrix and first candidate", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Constraints & budget/i);
    expect(screen.getByText(/Estimated upper-bound plan: 99 trials/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText(/Maximum total trials/i), {
      target: { value: "21" },
    });

    createExperiment();

    expect(await screen.findByText(/Requires at least 22 trials/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("applies scenario presets and validates obstacle geometry", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Scenarios/i);
    fireEvent.click(screen.getByRole("button", { name: /Combined stress/i }));
    expect(screen.getByLabelText(/Enable advanced scenario/i)).toHaveValue("yes");
    expect(screen.getByLabelText(/Gust magnitude/i)).toHaveValue(10);
    fireEvent.change(screen.getByLabelText(/Obstacles JSON/i), {
      target: {
        value: '[{"type":"cylinder","x":0,"y":0,"z":0,"radius":-1,"height":2}]',
      },
    });

    createExperiment();

    expect(await screen.findByText(/radius must be greater than 0/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("requires a search case and submits only the explicitly enabled scenario matrix", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_scenario_matrix" } as Job);
    renderPage();
    openStep(/Scenarios/i);

    fireEvent.click(screen.getByLabelText(/Nominal search/i));
    fireEvent.click(screen.getByLabelText(/Wind search/i));
    fireEvent.click(screen.getByLabelText(/Sensor-noise search/i));
    createExperiment();

    expect(await screen.findByText(/Enable at least one search scenario/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText(/Nominal search/i));
    fireEvent.click(screen.getByLabelText(/Nominal holdout/i));
    fireEvent.click(screen.getByLabelText(/Combined-stress holdout/i));
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].scenario_suite?.cases).toEqual([
      expect.objectContaining({ id: "nominal-search", scenario_type: "nominal", holdout: false }),
      expect.objectContaining({ id: "nominal-holdout", scenario_type: "nominal", holdout: true }),
    ]);
  });

  it("offers a one-click nominal-only matrix for the bundled real runner", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_real_nominal" } as Job);
    renderPage();
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Simulator Backend/i), {
      target: { value: "real_cli" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Use bundled nominal-only matrix/i }));
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].scenario_suite?.cases).toEqual([
      expect.objectContaining({ id: "nominal-search", scenario_type: "nominal", holdout: false }),
      expect.objectContaining({ id: "nominal-holdout", scenario_type: "nominal", holdout: true }),
    ]);
    expect(createSpy.mock.calls[0][0].sensor_noise_level).toBe("medium");
    expect(createSpy.mock.calls[0][0].advanced_scenario_config).toBeNull();
  });

  it("saves and restores a local draft without persisting an LLM secret", () => {
    const first = renderPage();
    fireEvent.change(screen.getByLabelText(/Experiment Name/i), {
      target: { value: "draft-study" },
    });
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "gpt" },
    });
    fireEvent.change(screen.getByLabelText(/LLM API Key/i), {
      target: { value: "sk-never-store-this" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save draft/i }));

    const raw = window.localStorage.getItem("drone-dream:experiment-draft:v1");
    expect(raw).toContain("draft-study");
    expect(raw).not.toContain("sk-never-store-this");

    first.unmount();
    renderPage();
    expect(screen.getByLabelText(/Experiment Name/i)).toHaveValue("draft-study");
    expect(screen.getByLabelText(/LLM API Key/i)).toHaveValue("");
  });

  it("normalizes type-mismatched draft fields instead of crashing", () => {
    window.localStorage.setItem(
      "drone-dream:experiment-draft:v1",
      JSON.stringify({
        schema_version: 1,
        saved_at: new Date().toISOString(),
        active_step: 3,
        form: {
          display_name: "recovered-study",
          tuning_mode: "unsafe-mode",
          search_seeds: null,
          advanced_enabled: "yes",
          llm_api_key: "must-not-restore",
        },
        selections: {
          MPC_XY_P: {
            name: "MPC_XY_P",
            baseline: "invalid",
            search_min: 0.5,
            search_max: 1.2,
            scale: "linear",
            selected: true,
          },
        },
      }),
    );

    renderPage();

    expect(screen.getByLabelText(/Experiment Name/i)).toHaveValue("recovered-study");
    expect(screen.getByRole("radio", { name: /^Basic/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByLabelText(/Search seeds/i)).toHaveValue("101, 202, 303");
  });

  it("discards unsupported or structurally invalid draft envelopes", () => {
    window.localStorage.setItem(
      "drone-dream:experiment-draft:v1",
      JSON.stringify({
        schema_version: 2,
        saved_at: "not-a-date",
        active_step: "review",
        form: { display_name: "must-not-load" },
        selections: {},
      }),
    );

    renderPage();

    expect(screen.getByLabelText(/Experiment Name/i)).toHaveValue("");
    expect(screen.queryByDisplayValue("must-not-load")).not.toBeInTheDocument();
  });

  it("submits the advanced experiment contract with PX4, objectives and holdout scenarios", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_created" } as Job);
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /^Advanced/i }));
    openStep(/Parameters/i);
    fireEvent.click(screen.getByLabelText(/Tune MC_AIRMODE/i));
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Simulator Backend/i), {
      target: { value: "real_cli" },
    });
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.vehicle_profile).toMatchObject({
      px4_version: "v1.16",
      airframe: "x500",
      simulator_model: "gz_x500",
    });
    expect(payload.parameter_space?.map((parameter) => parameter.name)).toEqual(
      expect.arrayContaining(["MPC_XY_P", "MPC_XY_VEL_P_ACC", "MPC_XY_VEL_D_ACC", "MC_AIRMODE"]),
    );
    expect(payload.parameter_space?.find((parameter) => parameter.name === "MC_AIRMODE")).toMatchObject({
      value_type: "integer",
      baseline: 0,
      minimum: 0,
      maximum: 2,
      step: 1,
      choices: [0, 1, 2],
    });
    expect(payload.objective_config?.objectives.map((objective) => objective.metric)).toEqual(
      expect.arrayContaining(["rmse", "completion_time", "pass_flag"]),
    );
    expect(payload.scenario_suite?.common_random_numbers).toBe(true);
    expect(payload.scenario_suite?.cases.some((scenario) => scenario.holdout)).toBe(true);
    expect(payload.max_total_trials).toBe(100);
    expect(payload.simulator_backend).toBe("real_cli");
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job_created", { replace: false });
  }, 10_000);

  it("supports an OpenAI-compatible Qwen optimizer only when the user opts into GPT", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_llm" } as Job);
    renderPage();
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "gpt" },
    });
    fireEvent.change(screen.getByLabelText(/LLM Provider/i), {
      target: { value: "deepseek" },
    });
    expect(screen.getByLabelText(/Compatible API Base URL/i)).toHaveValue(
      "https://api.deepseek.com",
    );
    expect(screen.getByLabelText(/LLM Model/i)).toHaveValue("deepseek-v4-flash");
    fireEvent.change(screen.getByLabelText(/LLM Provider/i), {
      target: { value: "qwen" },
    });
    expect(screen.getByLabelText(/Compatible API Base URL/i)).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    expect(screen.getByLabelText(/LLM Model/i)).toHaveValue("qwen-plus");
    createExperiment();
    expect(await screen.findByText(/API key required when strategy is gpt/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/LLM API Key/i), {
      target: { value: "dashscope-key" },
    });
    fireEvent.change(screen.getByLabelText(/LLM Model/i), {
      target: { value: "qwen-plus" },
    });
    createExperiment();
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].llm).toEqual({
      provider: "qwen",
      api_key: "dashscope-key",
      model: "qwen-plus",
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    });
  });

  it("rejects an invalid custom LLM endpoint before submission", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "gpt" },
    });
    fireEvent.change(screen.getByLabelText(/LLM Provider/i), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByLabelText(/LLM API Key/i), {
      target: { value: "custom-key" },
    });
    fireEvent.change(screen.getByLabelText(/LLM Model/i), {
      target: { value: "custom-model" },
    });
    fireEvent.change(screen.getByLabelText(/Compatible API Base URL/i), {
      target: { value: "ftp://example.com/v1?key=bad" },
    });
    createExperiment();

    expect(
      await screen.findByText(/absolute HTTP\(S\) URL without credentials, query, or fragment/i),
    ).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("submits an interactive custom track and advanced scenario configuration", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_custom" } as Job);
    renderPage();
    openStep(/Flight track/i);
    fireEvent.change(screen.getByLabelText(/Track Type/i), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText(/Waypoint 2 X/i), { target: { value: "8" } });
    openStep(/Scenarios/i);
    fireEvent.click(screen.getByRole("button", { name: /Show Advanced scenario/i }));
    fireEvent.change(screen.getByLabelText(/Enable advanced scenario/i), { target: { value: "yes" } });
    fireEvent.change(screen.getByLabelText(/Dropout rate/i), { target: { value: "0.2" } });
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.track_type).toBe("custom");
    expect(payload.reference_track?.[1].x).toBe(8);
    expect(payload.advanced_scenario_config?.sensor_degradation?.dropout_rate).toBe(0.2);
  });

  it("falls back to the legacy contract only when an old backend rejects advanced fields", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockRejectedValueOnce(
        new ApiClientError("INVALID_INPUT", "Unknown advanced fields", null, 422),
      )
      .mockResolvedValueOnce({ id: "job_legacy" } as Job);
    renderPage();
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(2));
    expect(createSpy.mock.calls[0][0].parameter_space).toBeDefined();
    expect(createSpy.mock.calls[1][0].parameter_space).toBeUndefined();
    expect(createSpy.mock.calls[1][0].vehicle_profile).toBeUndefined();
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job_legacy", { replace: false });
  });

  it("does not hide a normal PX4 validation failure behind the legacy fallback", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockRejectedValue(
        new ApiClientError("INVALID_INPUT", "Unknown PX4 parameter MPC_BAD", null, 422),
      );
    renderPage();

    createExperiment();

    expect(await screen.findByText(/Unknown PX4 parameter MPC_BAD/i)).toBeVisible();
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("keeps explicit legacy baselines for PX4 parameters that are not selected", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_legacy_baseline" } as Job);
    renderPage();
    openStep(/Parameters/i);
    fireEvent.click(screen.getByText(/Legacy Job API baseline mapping/i));
    fireEvent.change(screen.getByLabelText(/^kd_xy$/i), { target: { value: "0.7" } });

    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].baseline_parameters?.kd_xy).toBe(0.7);
  });

  it("preserves user input and surfaces a structured API failure", async () => {
    vi.spyOn(apiClient, "createJob").mockRejectedValue(
      new ApiClientError("NETWORK_ERROR", "Backend is unreachable.", null, 0),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText(/Experiment Name/i), {
      target: { value: "keep-me" },
    });
    createExperiment();

    expect(await screen.findByText(/Backend is unreachable/i)).toBeVisible();
    expect(screen.getByLabelText(/Experiment Name/i)).toHaveValue("keep-me");
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
