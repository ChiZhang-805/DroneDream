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
    });
    expect(payload.objective_config?.objectives.map((objective) => objective.metric)).toEqual(
      expect.arrayContaining(["rmse", "completion_time", "pass_flag"]),
    );
    expect(payload.scenario_suite?.common_random_numbers).toBe(true);
    expect(payload.scenario_suite?.cases.some((scenario) => scenario.holdout)).toBe(true);
    expect(payload.max_total_trials).toBe(100);
    expect(payload.simulator_backend).toBe("real_cli");
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job_created", { replace: false });
  });

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
