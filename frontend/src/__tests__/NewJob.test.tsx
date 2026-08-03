import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewJob } from "../pages/NewJob";
import { apiClient, ApiClientError } from "../api/client";
import {
  EXPERIMENT_DRAFT_KEY,
  LEGACY_EXPERIMENT_DRAFT_KEY,
} from "../features/experiment/draftStorage";
import type { BackendCapabilitiesResponse, Job } from "../types/api";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import type { ModelAccessSettings } from "../features/settings/ModelAccessContext";
import {
  listExperimentWorkspaces,
  updateExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return { ...actual, useNavigate: () => navigateMock };
});
interface RenderPageOptions {
  confirmName?: boolean;
  experimentName?: string;
  modelSettings?: Partial<ModelAccessSettings>;
  initialEntry?: string;
}

function renderPage({
  confirmName = true,
  experimentName,
  modelSettings,
  initialEntry = "/jobs/new",
}: RenderPageOptions = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ModelAccessProvider initialSettings={modelSettings}>
          <NewJob />
        </ModelAccessProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  if (confirmName) {
    const input = within(screen.getByRole("dialog", { name: /New Tuning Experiment/i }))
      .getByRole("textbox") as HTMLInputElement;
    const nextName = experimentName ?? (input.value || "test-experiment");
    fireEvent.change(input, { target: { value: nextName } });
    fireEvent.click(screen.getByRole("button", { name: /^Continue$/i }));
  }
  return result;
}

function selectMode(mode: "basic" | "advanced" | "expert"): void {
  fireEvent.change(screen.getByLabelText(/Tuning experience level/i), {
    target: { value: mode },
  });
}

function selectObjective(profile: "stable" | "fast" | "smooth" | "robust" | "custom"): void {
  fireEvent.change(screen.getByLabelText(/Objective profile/i), {
    target: { value: profile },
  });
}

const STEP_LABELS = [
  "Flight Setup",
  "Parameters",
  "Scenarios",
  "Constraints & budget",
  "Review",
] as const;

function activeStepIndex(): number {
  const progress = screen.getByRole("navigation", { name: /Experiment setup progress/i });
  const steps = within(progress).getAllByRole("listitem");
  return steps.findIndex((item) => item.getAttribute("aria-current") === "step");
}

function stepIndex(name: RegExp): number {
  return STEP_LABELS.findIndex((label) => name.test(label));
}

function openStep(name: RegExp): void {
  const target = stepIndex(name);
  if (target < 0) throw new Error(`Unknown wizard step: ${name}`);
  let current = activeStepIndex();
  for (let attempts = 0; current !== target && attempts < STEP_LABELS.length; attempts += 1) {
    fireEvent.click(
      screen.getByRole("button", { name: current < target ? /^Next$/i : /^Back$/i }),
    );
    const next = activeStepIndex();
    if (next === current) {
      throw new Error(`Wizard did not advance from ${STEP_LABELS[current]}`);
    }
    current = next;
  }
  expect(current).toBe(target);
}

function createExperiment(): void {
  openStep(/Review/i);
  fireEvent.click(screen.getByRole("button", { name: /Create Experiment/i }));
}

beforeEach(() => {
  navigateMock.mockReset();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("NewJob experiment wizard", () => {
  it("prefills an exact fixed scenario only after asking for a fresh experiment name", () => {
    const createSpy = vi.spyOn(apiClient, "createJob");
    renderPage({
      confirmName: false,
      initialEntry: "/jobs/new?scenario=wind-sensor-circle%401",
    });

    const nameDialog = screen.getByRole("dialog", { name: /New Tuning Experiment/i });
    expect(within(nameDialog).getByRole("textbox")).toHaveValue("");
    expect(screen.queryByRole("navigation", { name: /Experiment setup progress/i })).toBeNull();

    fireEvent.change(within(nameDialog).getByRole("textbox"), {
      target: { value: "combined-common-conditions" },
    });
    fireEvent.click(within(nameDialog).getByRole("button", { name: /^Continue$/i }));

    expect(screen.getByLabelText(/Track type/i)).toHaveValue("circle");
    expect(screen.getByText(/wind-sensor-circle@1/i)).toBeVisible();
    openStep(/Scenarios/i);
    expect(screen.getByLabelText(/East wind/i)).toHaveValue(3);
    expect(screen.getByLabelText(/Sensor noise level/i)).toHaveValue("medium");
    expect(screen.getByLabelText(/Wind search/i)).toHaveValue("true");
    expect(screen.getByLabelText(/Sensor-noise search/i)).toHaveValue("true");
    expect(screen.getByLabelText(/Combined-stress holdout/i)).toHaveValue("true");
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("ignores an unknown scenario key and retains safe defaults", () => {
    renderPage({
      initialEntry: "/jobs/new?scenario=unknown%40999",
    });

    expect(screen.getByLabelText(/Track type/i)).toHaveValue("circle");
    expect(screen.getByLabelText(/Objective profile/i)).toHaveValue("robust");
    expect(screen.queryByText(/unknown@999/i)).toBeNull();
  });

  it("collects the experiment name before entering the wizard and cancels back", () => {
    const first = renderPage({ confirmName: false });

    expect(screen.getByRole("dialog", { name: /New Tuning Experiment/i })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: /Experiment setup progress/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Continue$/i }));
    expect(screen.getByText(/^Required$/i)).toBeVisible();

    fireEvent.change(screen.getByLabelText(/Experiment name/i), {
      target: { value: "wind-study" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Continue$/i }));

    expect(screen.getByRole("navigation", { name: /Experiment setup progress/i })).toBeVisible();
    expect(screen.queryByLabelText(/Experiment name/i)).toBeNull();
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain("wind-study");

    first.unmount();
    window.sessionStorage.removeItem(EXPERIMENT_DRAFT_KEY);
    window.localStorage.removeItem(EXPERIMENT_DRAFT_KEY);
    renderPage({ confirmName: false });
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));
    expect(navigateMock).toHaveBeenCalledWith(-1);
  });

  it("renders five locked steps, a combined flight setup, and a safe non-GPT default", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: /New Tuning Experiment/i })).toBeVisible();
    const progress = screen.getByRole("navigation", { name: /Experiment setup progress/i });
    const progressItems = within(progress).getAllByRole("listitem");
    expect(progressItems).toHaveLength(5);
    expect(progressItems.map((item) => item.textContent?.replace(/^\d+/, "").trim())).toEqual(
      [...STEP_LABELS],
    );
    expect(within(progress).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Flight Setup" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Vehicle & PX4 Profile" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Optimization Objective" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Flight Track Configuration" })).toBeVisible();
    const modeSelector = screen.getByLabelText(/Tuning experience level/i);
    expect(modeSelector).toHaveValue("basic");
    expect(modeSelector.closest(".wizard-full-row")).not.toBeNull();
    expect(modeSelector.closest(".section-card")).not.toBeNull();
    expect(screen.getByLabelText(/Objective profile/i)).toHaveValue("robust");
    expect(screen.queryByLabelText(/Experiment name/i)).toBeNull();
    expect(screen.queryByText(/selected track is generated from these dimensions/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Convert to editable waypoints/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Create Experiment/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Save draft|Reset defaults/i })).toBeNull();

    openStep(/Constraints & budget/i);
    expect(
      screen.getByRole("region", { name: "Evidence-guided optimization loop" }),
    ).toHaveTextContent("Allocate budget across engines");
    expect(
      screen.getByRole("region", { name: "Evidence-guided optimization loop" }),
    ).toHaveTextContent("Verify with full simulations");
    expect(screen.getByLabelText(/Optimizer Strategy/i)).toHaveValue(
      "optimizer_portfolio",
    );
    expect(
      screen.getByRole("option", {
        name: "Accuracy-first optimizer portfolio (Recommended)",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "LLM tool orchestration harness" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Failure-aware constrained MOBO" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Multi-fidelity constrained MOBO" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "TuRBO-inspired trust-region BO" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "SAAS-inspired constrained BO" })).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Surrogate-assisted CMA-ES" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "BIPOP-inspired CMA-ES" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Model API key/i)).toBeNull();
    expect(screen.getByLabelText(/Maximum total trials/i)).toHaveValue(220);
    expect(screen.getByLabelText(/Maximum iterations/i)).toHaveAttribute("max", "100");
    expect(screen.getByLabelText(/Maximum total trials/i)).toHaveAttribute("max", "10000");
    expect(screen.queryByText("Synthetic workflow simulator")).not.toBeInTheDocument();
    expect(screen.queryByText("Experimental accuracy-first strategy")).not.toBeInTheDocument();
    expect(screen.queryByText("Estimated upper-bound plan")).not.toBeInTheDocument();
  });

  it("keeps selected PX4 parameters to one preview row and opens the complete list", async () => {
    const page = renderPage();
    openStep(/Parameters/i);
    fireEvent.click(screen.getByRole("button", {
      name: "Expand: Horizontal Motion Control",
    }));
    const availableParameters = screen.getAllByRole("checkbox");
    const additionalParameters = availableParameters
      .filter((checkbox) => !(checkbox as HTMLInputElement).checked)
      .slice(0, 3);
    expect(additionalParameters).toHaveLength(3);
    additionalParameters.forEach((checkbox) => fireEvent.click(checkbox));
    openStep(/Review/i);

    const trigger = screen.getByRole("button", { name: "View all parameters" });
    const preview = page.container.querySelector(".review-parameter-preview");
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveClass("review-parameter-chips");
    if (!(preview instanceof HTMLElement)) {
      throw new Error("Selected-parameter preview was not rendered.");
    }
    const previewItems = preview.querySelectorAll("code");
    expect(previewItems.length).toBeGreaterThanOrEqual(7);
    previewItems.forEach((item, index) => {
      Object.defineProperty(item, "offsetLeft", {
        configurable: true,
        value: index * 215,
      });
    });
    const scrollTo = vi.fn();
    Object.defineProperty(preview, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });

    fireEvent.wheel(preview, { deltaY: 12, deltaMode: 0 });
    expect(scrollTo).not.toHaveBeenCalled();
    fireEvent.wheel(preview, { deltaY: 28, deltaMode: 0 });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 215, behavior: "smooth" });
    fireEvent.wheel(preview, { deltaY: 100, deltaMode: 0 });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 430, behavior: "smooth" });
    fireEvent.wheel(preview, { deltaY: -100, deltaMode: 0 });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 215, behavior: "smooth" });
    fireEvent.wheel(preview, { deltaY: -100, deltaMode: 0 });
    fireEvent.wheel(preview, { deltaY: -100, deltaMode: 0 });
    expect(scrollTo).toHaveBeenLastCalledWith({
      left: (previewItems.length - 1) * 215,
      behavior: "smooth",
    });
    expect(screen.queryByRole("dialog", { name: "Selected PX4 parameters" }))
      .not.toBeInTheDocument();

    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Selected PX4 parameters" });
    expect(within(dialog).getByText(/tunable parameters/i)).toBeInTheDocument();
    expect(within(dialog).getAllByText(/MPC_/i).length).toBeGreaterThan(0);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Selected PX4 parameters" }))
      .not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());

    openStep(/Parameters/i);
    const selectedCheckbox = screen.getAllByRole("checkbox")
      .find((checkbox) => (checkbox as HTMLInputElement).checked);
    if (!selectedCheckbox) throw new Error("No selected PX4 parameter was found.");
    fireEvent.click(selectedCheckbox);
    openStep(/Review/i);
    const shortPreview = page.container.querySelector(".review-parameter-preview");
    if (!(shortPreview instanceof HTMLElement)) {
      throw new Error("Short selected-parameter preview was not rendered.");
    }
    expect(shortPreview.querySelectorAll("code")).toHaveLength(previewItems.length - 1);
    const shortScrollTo = vi.fn();
    Object.defineProperty(shortPreview, "scrollTo", {
      configurable: true,
      value: shortScrollTo,
    });
    fireEvent.wheel(shortPreview, { deltaY: 100, deltaMode: 0 });
    expect(shortScrollTo).not.toHaveBeenCalled();
  });

  it("persists a validated Next transition immediately and keeps completed steps after Back", () => {
    const first = renderPage({ experimentName: "step-state-study" });
    fireEvent.change(screen.getByLabelText(/Airframe/i), {
      target: { value: "quad_x" },
    });

    fireEvent.click(screen.getByRole("button", { name: /^Next$/i }));

    const saved = JSON.parse(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY) ?? "null") as {
      active_step: number;
      completed_steps: number[];
      form: { display_name: string; airframe: string };
    };
    expect(saved.active_step).toBe(1);
    expect(saved.completed_steps).toEqual([0]);
    expect(saved.form).toMatchObject({
      display_name: "step-state-study",
      airframe: "quad_x",
    });

    openStep(/Constraints & budget/i);
    fireEvent.click(screen.getByRole("button", { name: /^Back$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Back$/i }));
    expect(activeStepIndex()).toBe(1);

    const progress = screen.getByRole("navigation", { name: /Experiment setup progress/i });
    const progressItems = within(progress).getAllByRole("listitem");
    expect(progressItems[0]).toHaveClass("wizard-step-complete");
    expect(progressItems[0]).toHaveTextContent("✓");
    expect(progressItems[1]).toHaveAttribute("aria-current", "step");
    expect(progressItems[1]).not.toHaveClass("wizard-step-complete");
    expect(progressItems[2]).toHaveClass("wizard-step-complete");
    expect(progressItems[2]).toHaveTextContent("✓");
    expect(progressItems[3]).not.toHaveClass("wizard-step-complete");
    expect(progressItems[4]).not.toHaveClass("wizard-step-complete");

    const savedAfterBack = JSON.parse(
      window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY) ?? "null",
    ) as { active_step: number; completed_steps: number[] };
    expect(savedAfterBack).toMatchObject({
      active_step: 1,
      completed_steps: [0, 1, 2],
    });

    first.unmount();
    const workspace = listExperimentWorkspaces("local")[0];
    expect(workspace).toBeDefined();
    renderPage({
      confirmName: false,
      initialEntry: `/jobs/new?experiment=${workspace.id}`,
    });
    const restoredProgress = screen.getByRole("navigation", {
      name: /Experiment setup progress/i,
    });
    const restoredItems = within(restoredProgress).getAllByRole("listitem");
    expect(restoredItems[0]).toHaveClass("wizard-step-complete");
    expect(restoredItems[1]).toHaveAttribute("aria-current", "step");
    expect(restoredItems[2]).toHaveClass("wizard-step-complete");
    expect(restoredItems[3]).not.toHaveClass("wizard-step-complete");
    expect(restoredItems[4]).not.toHaveClass("wizard-step-complete");
  });

  it("keeps semantic option changes compact without helper paragraphs", () => {
    renderPage();

    expect(screen.queryByText("A full circle centered on X/Y with the chosen radius.")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Track Type/i), { target: { value: "u_turn" } });
    expect(screen.getByLabelText(/Straight length/i)).toBeVisible();
    expect(screen.queryByText("Two straight legs joined by one semicircular turn.")).toBeNull();

    fireEvent.change(screen.getByLabelText(/Airframe/i), { target: { value: "quad_x" } });
    expect(screen.getByLabelText(/Airframe/i)).toHaveValue("quad_x");
    expect(screen.queryByText("Generic X-layout quadrotor configuration.")).toBeNull();

    fireEvent.change(screen.getByLabelText(/^Gazebo rendering$/i), { target: { value: "false" } });
    expect(screen.getByLabelText(/^Gazebo rendering$/i)).toHaveValue("false");
    expect(screen.queryByText("Shows Gazebo graphics for visual observation.")).toBeNull();

    selectObjective("fast");
    expect(screen.queryByText("Rewards shorter completion time while staying valid.")).toBeNull();

    openStep(/Scenarios/i);
    fireEvent.change(screen.getByLabelText(/Sensor noise level/i), { target: { value: "high" } });
    expect(screen.getByLabelText(/Sensor noise level/i)).toHaveValue("high");
    expect(screen.queryByText("Applies severe sensor noise for stress testing.")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Matched random conditions/i), { target: { value: "false" } });
    expect(screen.getByLabelText(/Matched random conditions/i)).toHaveValue("false");

    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Simulator Backend/i), { target: { value: "real_cli" } });
    expect(screen.getByLabelText(/Simulator Backend/i)).toHaveValue("real_cli");
    expect(screen.queryByText("Runs real PX4 SITL and Gazebo flight physics.")).toBeNull();
  });

  it("submits per-job Gazebo runtime controls for reproducible parallel runs", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_runtime" } as Job);
    renderPage();
    expect(screen.getByLabelText(/^Gazebo rendering$/i)).toHaveValue("true");
    selectMode("advanced");
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

  it("disables Next while the current step is invalid", () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();

    openStep(/Flight Setup/i);
    fireEvent.change(screen.getByLabelText(/Altitude/i), { target: { value: "25" } });
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(screen.getByLabelText(/Altitude/i)).toBeVisible();
    expect(activeStepIndex()).toBe(0);
    expect(screen.queryByRole("button", { name: /Create Experiment/i })).toBeNull();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("fails closed when the selected PX4 version has no matching parameter catalog", () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    fireEvent.change(screen.getByLabelText(/PX4 Version/i), {
      target: { value: "v1.17" },
    });

    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(0);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("validates the tuning objective before leaving the combined flight setup", () => {
    renderPage();
    selectMode("advanced");
    for (const label of [
      /Tracking accuracy weight/i,
      /Completion speed weight/i,
      /Smoothness weight/i,
      /Robust pass-rate weight/i,
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: "0" } });
    }

    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(0);
  });

  it("validates custom JSON and keeps it synchronized with the waypoint editor", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Flight Setup/i);

    fireEvent.change(screen.getByLabelText(/Track Type/i), { target: { value: "custom" } });
    fireEvent.click(screen.getByRole("button", { name: /Edit custom track/i }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: /Add waypoint/i }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: /Undo/i }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint/i })).toHaveLength(3);

    const jsonTrigger = screen.getByRole("button", { name: /JSON import \/ export/i });
    expect(jsonTrigger.closest(".track-editor-data-action")).not.toBeNull();
    expect(jsonTrigger).toHaveAttribute("title", "JSON import / export");
    expect(jsonTrigger).not.toHaveAttribute("data-tooltip");
    fireEvent.click(jsonTrigger);
    expect(screen.getByRole("dialog", { name: /JSON import \/ export/i })).toBeVisible();
    fireEvent.change(screen.getByLabelText(/Reference track \(JSON\)/i), {
      target: { value: '[{"x":0,"y":0}]' },
    });
    fireEvent.click(screen.getByRole("button", { name: /Close JSON import \/ export/i }));
    expect(screen.queryByRole("dialog", { name: /JSON import \/ export/i })).toBeNull();
    expect(screen.getByRole("dialog", { name: /Edit custom track/i })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Close track editor/i }));
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(0);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("lets advanced users choose real PX4 dimensions and validates ranges", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    selectMode("advanced");
    openStep(/Parameters/i);
    fireEvent.click(screen.getByRole("button", { name: /Expand: Horizontal Motion Control/i }));

    expect(screen.getByLabelText(/Tune MPC_XY_P/i)).toBeChecked();
    expect(screen.getByLabelText(/MPC_XY_P search minimum/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText(/MPC_XY_P search minimum/i), {
      target: { value: "1.4" },
    });
    fireEvent.change(screen.getByLabelText(/MPC_XY_P search maximum/i), {
      target: { value: "0.7" },
    });
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(1);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("applies objective profile weights and marks manual edits as custom", () => {
    renderPage();
    selectMode("advanced");
    openStep(/Flight Setup/i);

    selectObjective("fast");
    expect(screen.getByLabelText(/Tracking accuracy weight/i)).toHaveValue(0.75);
    expect(screen.getByLabelText(/Completion speed weight/i)).toHaveValue(1);
    expect(screen.getByLabelText(/Robust aggregation/i)).toHaveValue("mean");

    fireEvent.change(screen.getByLabelText(/Completion speed weight/i), {
      target: { value: "0.9" },
    });
    expect(screen.getByLabelText(/Objective profile/i)).toHaveValue("custom");
  });

  it("does not submit stale inactive tail-risk values", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_mean" } as Job);
    renderPage();
    selectMode("advanced");
    openStep(/Flight Setup/i);
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
    selectMode("advanced");
    openStep(/Parameters/i);
    fireEvent.click(screen.getByRole("button", { name: /Expand: Horizontal Motion Control/i }));

    fireEvent.change(screen.getByLabelText(/MPC_XY_P search minimum/i), {
      target: { value: "" },
    });
    expect(screen.getByLabelText(/MPC_XY_P search minimum/i)).toHaveValue(null);
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(1);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("disables Next without showing an alert when no tuning parameter is selected", () => {
    renderPage();
    selectMode("advanced");
    openStep(/Parameters/i);

    fireEvent.click(screen.getByRole("button", { name: /Clear visible/i }));

    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(screen.queryByText("Select at least one parameter to tune.")).toBeNull();
  });

  it("allows explicit companion selection without a visible dependency alert", () => {
    renderPage();
    selectMode("advanced");
    openStep(/Parameters/i);

    fireEvent.change(screen.getByLabelText(/Find a PX4 parameter/i), {
      target: { value: "MC_ROLLRATE_I" },
    });
    fireEvent.click(screen.getByLabelText(/Tune MC_ROLLRATE_I/i));
    expect(screen.queryByText(/Recommended companion parameters are not selected/i)).toBeNull();
    fireEvent.change(screen.getByLabelText(/Find a PX4 parameter/i), {
      target: { value: "MC_ROLLRATE_P" },
    });
    fireEvent.click(screen.getByLabelText(/Tune MC_ROLLRATE_P/i));
    expect(screen.getByLabelText(/Tune MC_ROLLRATE_P/i)).toBeChecked();
  });

  it("rejects a budget that cannot run the baseline matrix and first candidate", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Maximum total trials/i), {
      target: { value: "1" },
    });

    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(3);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("applies scenario presets and validates obstacle geometry", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage();
    openStep(/Scenarios/i);
    expect(screen.queryByRole("button", { name: /Combined stress/i })).toBeNull();
    fireEvent.change(screen.getByLabelText(/Environment presets/i), {
      target: { value: "stress" },
    });
    expect(screen.queryByText("Combines wind, gust, sensor, battery and payload effects.")).toBeNull();
    expect(screen.getByLabelText(/^Advanced environment$/i)).toHaveValue("true");
    expect(screen.getByLabelText(/Gust magnitude/i)).toHaveValue(10);
    fireEvent.click(screen.getByRole("button", { name: /Edit obstacles/i }));
    const obstacleDialog = screen.getByRole("dialog", { name: /Obstacles.*JSON/i });
    fireEvent.change(within(obstacleDialog).getByRole("textbox"), {
      target: {
        value: '[{"type":"cylinder","x":0,"y":0,"z":0,"radius":-1,"height":2}]',
      },
    });

    const closeButton = screen.getByRole("button", { name: /Close advanced settings/i });
    expect(closeButton).toHaveAttribute("title", "Close advanced settings");
    fireEvent.click(closeButton);
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(2);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("requires a search case and submits only the explicitly enabled scenario matrix", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_scenario_matrix" } as Job);
    renderPage();
    openStep(/Scenarios/i);

    fireEvent.change(screen.getByLabelText(/Nominal search/i), { target: { value: "false" } });
    fireEvent.change(screen.getByLabelText(/Wind search/i), { target: { value: "false" } });
    fireEvent.change(screen.getByLabelText(/Sensor-noise search/i), { target: { value: "false" } });
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(2);
    expect(createSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Nominal search/i), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText(/Nominal holdout/i), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText(/Combined-stress holdout/i), { target: { value: "false" } });
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].scenario_suite?.cases).toEqual([
      expect.objectContaining({ id: "nominal-search", scenario_type: "nominal", holdout: false }),
      expect.objectContaining({ id: "nominal-holdout", scenario_type: "nominal", holdout: true }),
    ]);
  });

  it("shows verified and extension-gated PX4/Gazebo scenario capabilities", async () => {
    vi.stubEnv("VITE_CAPABILITIES_API", "true");
    vi.spyOn(apiClient, "getCapabilities").mockResolvedValue({
      service_version: "test",
      simulators: {
        configuration_scope: "api_process",
        authoritative: false,
        worker_override: null,
        worker_override_supported: true,
        items: {
          real_cli: {
            ready: true,
            status: "configured",
            scenario_effect_contract: {
              schema_version: "dronedream.scenario_effect_request.v1",
              physically_applied: ["obstacles"],
              requires_runtime_extension: ["wind vector and gust profile"],
            },
          },
        },
      },
      optimizers: { authoritative: false, items: {} },
      parameter_catalog: { catalog_version: "test", supported_px4_versions: ["v1.16"] },
    } satisfies BackendCapabilitiesResponse);
    renderPage();
    openStep(/Scenarios/i);
    expect(await screen.findByLabelText(/^Advanced environment$/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /Edit obstacles/i })).toBeEnabled();
    expect(screen.queryByText(/Obstacles: verified Gazebo injection/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wind, sensors, battery and payload: Runtime extension required/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Advanced effects require launcher evidence/i)).not.toBeInTheDocument();
  });

  it("autosaves and restores a session draft without persisting an LLM secret", async () => {
    const first = renderPage({
      experimentName: "draft-study",
      modelSettings: { apiKey: "sk-never-store-this" },
    });
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "gpt" },
    });
    await waitFor(() => {
      const raw = window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY);
      const draft = JSON.parse(raw ?? "null") as { form?: { optimizer_strategy?: string } } | null;
      expect(raw).toContain("draft-study");
      expect(raw).not.toContain("sk-never-store-this");
      expect(draft?.form?.optimizer_strategy).toBe("gpt");
    });

    first.unmount();
    const workspace = listExperimentWorkspaces("local")[0];
    expect(workspace).toBeDefined();
    renderPage({
      confirmName: false,
      initialEntry: `/jobs/new?experiment=${workspace.id}`,
    });
    expect(screen.queryByLabelText(/Experiment Name/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Configure model access/i })).toBeNull();
    expect(screen.queryByLabelText(/Model API key/i)).toBeNull();
    expect(screen.getByText(/API key required in Settings/i)).toBeVisible();
    expect(screen.queryByText("Uses OpenAI's compatible chat-completions API.")).toBeNull();
    expect(screen.queryByText("API keys are never stored in the local draft.")).toBeNull();
    expect(screen.queryByText("Leave blank to use the backend's default model.")).toBeNull();
    expect(screen.queryByText("Required only for a custom compatible endpoint.")).toBeNull();
  });

  it("restores the selected advanced environment preset with the draft", () => {
    const first = renderPage({ experimentName: "preset-draft" });
    openStep(/Scenarios/i);
    fireEvent.change(screen.getByLabelText(/Environment presets/i), {
      target: { value: "stress" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Next$/i }));

    first.unmount();
    const workspace = listExperimentWorkspaces("local")[0];
    expect(workspace).toBeDefined();
    renderPage({
      confirmName: false,
      initialEntry: `/jobs/new?experiment=${workspace.id}`,
    });
    fireEvent.click(screen.getByRole("button", { name: /^Back$/i }));
    expect(screen.getByLabelText(/Environment presets/i)).toHaveValue("stress");
  });

  it("starts blank instead of cloning a type-mismatched legacy active draft", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      JSON.stringify({
        schema_version: 1,
        saved_at: new Date().toISOString(),
        active_step: 6,
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

    renderPage({ confirmName: false });
    const nameDialog = screen.getByRole("dialog", {
      name: "New Tuning Experiment",
    });
    const nameInput = within(nameDialog).getByRole("textbox");
    expect(nameInput).toHaveValue("");
    fireEvent.change(nameInput, { target: { value: "fresh-study" } });
    fireEvent.click(within(nameDialog).getByRole("button", { name: "Continue" }));
    expect(activeStepIndex()).toBe(0);
    expect(screen.getByLabelText(/Tuning experience level/i)).toHaveValue("basic");
    expect(screen.getByLabelText(/Search seeds/i)).toHaveValue("101, 202, 303");
    expect(screen.queryByDisplayValue("recovered-study")).toBeNull();
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain(
      "fresh-study",
    );
  });

  it("keeps the current product default when a new draft ignores a legacy alias", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      JSON.stringify({
        schema_version: 1,
        saved_at: new Date().toISOString(),
        active_step: 5,
        form: {
          display_name: "pre-optimizer-draft",
        },
        selections: {},
      }),
    );

    renderPage({ confirmName: false });
    const nameDialog = screen.getByRole("dialog", {
      name: "New Tuning Experiment",
    });
    fireEvent.change(within(nameDialog).getByRole("textbox"), {
      target: { value: "new-portfolio-study" },
    });
    fireEvent.submit(nameDialog);
    expect(activeStepIndex()).toBe(0);
    expect(screen.getByLabelText(/Optimizer Strategy/i))
      .toHaveValue("optimizer_portfolio");
  });

  it("requires a unique active experiment name but permits reuse after archive", () => {
    const first = renderPage({ experimentName: "Wind Study" });
    first.unmount();

    renderPage({ confirmName: false });
    const dialog = screen.getByRole("dialog", { name: "New Tuning Experiment" });
    const input = within(dialog).getByRole("textbox");
    fireEvent.change(input, { target: { value: "  wind   study  " } });
    fireEvent.submit(dialog);
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "already used by an active experiment",
    );
    expect(screen.queryByRole("navigation", {
      name: "Experiment setup progress",
    })).toBeNull();

    const existing = listExperimentWorkspaces("local")[0];
    expect(existing).toBeDefined();
    updateExperimentWorkspace("local", existing.id, { archived: true });
    fireEvent.submit(dialog);
    expect(screen.getByRole("navigation", {
      name: "Experiment setup progress",
    })).toBeVisible();
    expect(listExperimentWorkspaces("local").filter((item) => !item.archived))
      .toHaveLength(1);
  });

  it("discards unsupported or structurally invalid draft envelopes", () => {
    window.sessionStorage.setItem(
      EXPERIMENT_DRAFT_KEY,
      JSON.stringify({
        schema_version: 2,
        saved_at: "not-a-date",
        active_step: "review",
        form: { display_name: "must-not-load" },
        selections: {},
      }),
    );

    renderPage({ confirmName: false });

    expect(within(screen.getByRole("dialog", { name: /New Tuning Experiment/i })).getByRole("textbox"))
      .toHaveValue("");
    expect(screen.queryByDisplayValue("must-not-load")).not.toBeInTheDocument();
  });

  it("submits the advanced experiment contract with PX4, objectives and holdout scenarios", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_created" } as Job);
    renderPage();
    selectMode("advanced");
    openStep(/Parameters/i);
    fireEvent.change(screen.getByLabelText(/Find a PX4 parameter/i), {
      target: { value: "MC_AIRMODE" },
    });
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
    expect(payload.max_total_trials).toBe(220);
    expect(payload.simulator_backend).toBe("real_cli");
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job_created", { replace: false });
  }, 10_000);

  it("submits an OpenAI-compatible Qwen model for the bounded LLM harness", async () => {
    window.localStorage.setItem("dronedream:model-access:v1", JSON.stringify({
      provider: "qwen",
      model: "qwen-plus",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }));
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_llm" } as Job);
    renderPage({
      modelSettings: {
        apiKey: "dashscope-key",
      },
    });
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "llm_harness" },
    });
    expect(screen.queryByRole("button", { name: /Configure model access/i })).toBeNull();
    expect(screen.getByText(/Qwen · qwen-plus/i)).toBeVisible();
    createExperiment();
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].optimizer_strategy).toBe("llm_harness");
    expect(createSpy.mock.calls[0][0].llm).toEqual({
      access_mode: "byok",
      provider: "qwen",
      api_key: "dashscope-key",
      platform_grant: null,
      model: "qwen-plus",
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    });
  });

  it("rejects an invalid custom LLM endpoint before submission", async () => {
    window.localStorage.setItem("dronedream:model-access:v1", JSON.stringify({
      provider: "custom",
      model: "custom-model",
      baseUrl: "ftp://example.com/v1?key=bad",
    }));
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "unused" } as Job);
    renderPage({
      modelSettings: {
        apiKey: "custom-key",
      },
    });
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "gpt" },
    });
    expect(screen.getByRole("button", { name: /^Next$/i })).toBeDisabled();
    expect(activeStepIndex()).toBe(3);
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("submits an interactive custom track and advanced scenario configuration", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_custom" } as Job);
    renderPage();
    openStep(/Flight Setup/i);
    fireEvent.change(screen.getByLabelText(/Track Type/i), { target: { value: "custom" } });
    fireEvent.click(screen.getByRole("button", { name: /Edit custom track/i }));
    fireEvent.change(screen.getByLabelText(/Waypoint 2 X/i), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: /Close track editor/i }));
    openStep(/Scenarios/i);
    fireEvent.change(screen.getByLabelText(/^Advanced environment$/i), { target: { value: "true" } });
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
    openStep(/Constraints & budget/i);
    fireEvent.change(screen.getByLabelText(/Optimizer Strategy/i), {
      target: { value: "heuristic" },
    });
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(2));
    expect(createSpy.mock.calls[0][0].parameter_space).toBeDefined();
    expect(createSpy.mock.calls[1][0].parameter_space).toBeUndefined();
    expect(createSpy.mock.calls[1][0].vehicle_profile).toBeUndefined();
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job_legacy", { replace: false });
  });

  it("does not silently downgrade an experimental optimizer for an old backend", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockRejectedValueOnce(
        new ApiClientError("INVALID_INPUT", "Unknown advanced fields", null, 422),
      );
    renderPage();

    createExperiment();

    expect(await screen.findByText(/experiment could not be created.*BACKEND_UPGRADE_REQUIRED/i)).toBeVisible();
    expect(createSpy).toHaveBeenCalledTimes(1);
  });

  it("does not hide a normal PX4 validation failure behind the legacy fallback", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockRejectedValue(
        new ApiClientError("INVALID_INPUT", "Unknown PX4 parameter MPC_BAD", null, 422),
      );
    renderPage();

    createExperiment();

    expect(await screen.findByText(/experiment could not be created.*INVALID_INPUT/i)).toBeVisible();
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("keeps the legacy baseline defaults when PX4 parameters are not selected", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_legacy_baseline" } as Job);
    renderPage();
    createExperiment();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy.mock.calls[0][0].baseline_parameters?.kd_xy).toBe(0.2);
  });

  it("preserves user input and surfaces a structured API failure", async () => {
    const createSpy = vi.spyOn(apiClient, "createJob").mockRejectedValue(
      new ApiClientError("NETWORK_ERROR", "Backend is unreachable.", null, 0),
    );
    renderPage({ experimentName: "keep-me" });
    createExperiment();

    expect(await screen.findByText(/experiment could not be created.*NETWORK_ERROR/i)).toBeVisible();
    expect(createSpy.mock.calls[0][0].display_name).toBe("keep-me");
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain("keep-me");
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
