import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as cloudModels from "../features/settings/cloudModelAccess";
import { FieldApp } from "../field/FieldApp";

const MODEL = {
  provider: "openai" as const,
  display_name: "GPT",
  model: "gpt-4.1",
  enabled: true,
  assistant_enabled: true,
  job_enabled: true,
  policy_version: 1,
};

function modelPlan(overrides: Record<string, unknown> = {}) {
  return JSON.stringify({
    summary: "Prepare a four-trial hover stability study with rollback after every candidate.",
    objective: "Reduce hover drift while preserving smooth control effort.",
    test_profile: "hover",
    trial_budget: 4,
    parameters: ["MC_ROLL_P", "MC_PITCH_P"],
    constraints: ["Capture a snapshot before every trial.", "Abort on any safety threshold breach."],
    questions: ["What operating zone will be used?"],
    ...overrides,
  });
}

function mockCatalog() {
  vi.spyOn(cloudModels, "getManagedModelCatalog").mockResolvedValue({
    generated_at: "2026-08-08T00:00:00Z",
    models: [MODEL],
  });
  vi.spyOn(cloudModels, "issueManagedModelGrant").mockResolvedValue({
    access_mode: "platform",
    grant: `ddg_${"a".repeat(48)}`,
    scope: "assistant",
    expires_at: "2026-08-08T01:00:00Z",
    max_calls: 1,
    gateway_base_url: "https://example.supabase.co/functions/v1/model-gateway",
    managed_model: "GPT",
    usage: {
      plan: { id: "free", name: "Free", monthly_price_cny_fen: 0, included_ai_credits: 1000, capability_set: "core-v1" },
      period: { starts_at: "2026-08-01T00:00:00Z", ends_at: "2026-09-01T00:00:00Z" },
      usage: {
        reserved_ai_credits: 0,
        consumed_ai_credits: 0,
        remaining_ai_credits: 1000,
        request_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        estimated_request_count: 0,
        credit_policy_version: 1,
      },
      recent_requests: [],
    },
  });
}

describe("Field Chatting workspace", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses the managed model to create a proposal-only Field plan", async () => {
    mockCatalog();
    const completion = vi.spyOn(cloudModels, "completeManagedModelChat").mockResolvedValue({
      model: "DroneDream Managed",
      choices: [{ message: { role: "assistant", content: modelPlan() } }],
    });
    const { container } = render(<FieldApp initialLocale="en" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Model" })).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/Example: reduce hover drift/), {
      target: { value: "Reduce hover drift with four short trials." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/Prepare a four-trial hover stability study/)).toBeVisible();
    expect(screen.getByText("Reduce hover drift while preserving smooth control effort.")).toBeVisible();
    expect(screen.getByText("MC_ROLL_P")).toBeVisible();
    expect(screen.getByText("MC_PITCH_P")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start controlled test" })).toBeDisabled();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(cloudModels.issueManagedModelGrant).toHaveBeenCalledWith(
      "assistant",
      expect.stringMatching(/^field-plan:/),
      "openai",
    );
    const messages = completion.mock.calls[0]?.[1] ?? [];
    expect(messages[0]?.content).toContain("proposal-only Model");
    expect(messages[0]?.content).toContain("zero validated Vehicle Packs");
    expect(messages.map((message) => message.content).join("\n"))
      .not.toMatch(/gazebo|sitl|hitl|simulator/i);

    fireEvent.click(screen.getByRole("button", { name: "Review tuning controls" }));
    expect(screen.getByRole("heading", { name: "Autonomous tuning" })).toBeInTheDocument();
  });

  it("rejects a model plan outside the Field parameter allowlist", async () => {
    mockCatalog();
    vi.spyOn(cloudModels, "completeManagedModelChat").mockResolvedValue({
      model: "DroneDream Managed",
      choices: [{
        message: {
          role: "assistant",
          content: modelPlan({ parameters: ["UNREGISTERED_PARAMETER"] }),
        },
      }],
    });
    render(<FieldApp initialLocale="en" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Model" })).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/Example: reduce hover drift/), {
      target: { value: "Tune everything." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Managed model returned a plan outside the Field contract.",
    );
    expect(screen.getAllByText("Waiting for your goal")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Start controlled test" })).toBeDisabled();
  });

  it("rejects duplicate parameters and unexpected model fields", async () => {
    mockCatalog();
    vi.spyOn(cloudModels, "completeManagedModelChat").mockResolvedValue({
      model: "DroneDream Managed",
      choices: [{
        message: {
          role: "assistant",
          content: modelPlan({
            parameters: ["MC_ROLL_P", "MC_ROLL_P"],
            unsafe_override: true,
          }),
        },
      }],
    });
    render(<FieldApp initialLocale="en" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Model" })).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/Example: reduce hover drift/), {
      target: { value: "Prepare a plan with strict evidence gates." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Managed model returned a plan outside the Field contract.",
    );
    expect(screen.getByRole("button", { name: "Start controlled test" })).toBeDisabled();
  });
});
