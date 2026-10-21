import { afterEach, describe, expect, it, vi } from "vitest";

import { compileHostedAssistantTurn } from "../features/experiment/hostedAssistant";
import * as cloudModelAccess from "../features/settings/cloudModelAccess";
import type { ManagedModelGrant } from "../features/settings/cloudModelAccess";

const GRANT: ManagedModelGrant = {
  access_mode: "platform",
  grant: `ddg_${"a".repeat(40)}`,
  scope: "assistant",
  expires_at: "2099-01-01T00:00:00Z",
  max_calls: 1,
  gateway_base_url: "https://example.supabase.co/functions/v1/model-gateway",
  managed_model: "GPT",
  usage: {
    plan: {
      id: "pro",
      name: "Pro",
      monthly_price_cny_fen: 12900,
      included_ai_credits: 15_000_000,
      capability_set: "core-v1",
    },
    period: {
      starts_at: "2098-12-01T00:00:00Z",
      ends_at: "2099-01-01T00:00:00Z",
    },
    usage: {
      reserved_ai_credits: 0,
      consumed_ai_credits: 0,
      remaining_ai_credits: 15_000_000,
      request_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_request_count: 0,
      credit_policy_version: 1,
    },
    recent_requests: [],
  },
};

describe("hosted edition assistant", () => {
  afterEach(() => vi.restoreAllMocks());

  it("turns a SIM response into a bounded editable draft without execution authority", async () => {
    const complete = vi.spyOn(cloudModelAccess, "completeManagedModelChat")
      .mockResolvedValue({
        model: "GPT",
        choices: [{
          message: {
            role: "assistant",
            content: JSON.stringify({
              artifact_kind: "simulation_experiment",
              artifact_title: "Circular wind study",
              summary: "An editable circular-track simulation draft with a wind holdout.",
              track_type: "circle",
              altitude_m: 3,
              objective_profile: "robust",
              max_total_trials: 220,
              vehicle_mass_kg: null,
              motor_count: null,
              arm_length_m: null,
              propeller_diameter_m: null,
              camera_payload: null,
              questions: ["Which wind envelope should the holdout use?"],
            }),
          },
        }],
        usage: { prompt_tokens: 120, completion_tokens: 80, total_tokens: 200 },
      });

    const result = await compileHostedAssistantTurn({
      grant: GRANT,
      edition: "sim",
      locale: "en",
      messageId: "turn-1",
      message: "Build a circular wind experiment.",
      conversationSummary: "",
      currentValues: { display_name: "", altitude_m: "3" },
      documentContext: null,
    });

    expect(result.accepted_patches).toEqual(expect.arrayContaining([
      expect.objectContaining({ field_id: "display_name", value: "Circular wind study" }),
      expect.objectContaining({ field_id: "max_total_trials", value: 220 }),
    ]));
    expect(result.experiment_summary).toContain("editable");
    expect(result.usage.total_tokens).toBe(200);
    expect(result.lifecycle_stage).toBe("proposal");
    expect(result.model_entrypoint_role).toBe("managed_model_proposal");
    expect(result.model_harness_domain).toBe("experiment.simulation");
    expect(result.runtime_execution_performed).toBe(false);
    expect(result.control_plane).toMatchObject({
      plugin_selection_effect: "contract_only",
      plugin_runtime_receipt_ids: [],
    });
    expect(result.harness_input_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(complete.mock.calls[0][0]).toBe(GRANT);
    expect(JSON.stringify(complete.mock.calls[0][1])).toContain(
      "The public web console has no execution authority",
    );
  });

  it("rejects an artifact that does not match the selected FIELD edition", async () => {
    vi.spyOn(cloudModelAccess, "completeManagedModelChat").mockResolvedValue({
      model: "GPT",
      choices: [{
        message: {
          role: "assistant",
          content: JSON.stringify({
            artifact_kind: "simulation_experiment",
            artifact_title: "Unsafe mismatch",
            summary: "Wrong artifact.",
            track_type: null,
            altitude_m: null,
            objective_profile: null,
            max_total_trials: null,
            vehicle_mass_kg: null,
            motor_count: null,
            arm_length_m: null,
            propeller_diameter_m: null,
            camera_payload: null,
            questions: [],
          }),
        },
      }],
    });

    await expect(compileHostedAssistantTurn({
      grant: GRANT,
      edition: "field",
      locale: "en",
      messageId: "turn-2",
      message: "Prepare a field plan.",
      conversationSummary: "",
      currentValues: {},
      documentContext: null,
    })).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 502 });
  });

  it("turns a Universal response into a bounded editable vehicle draft", async () => {
    vi.spyOn(cloudModelAccess, "completeManagedModelChat").mockResolvedValue({
      model: "GPT",
      choices: [{
        message: {
          role: "assistant",
          content: JSON.stringify({
            artifact_kind: "universal_design",
            artifact_title: "Hexa inspection prototype",
            summary: "An editable six-motor inspection vehicle draft.",
            track_type: null,
            altitude_m: null,
            objective_profile: null,
            max_total_trials: null,
            vehicle_mass_kg: 4.2,
            motor_count: 6,
            arm_length_m: 0.48,
            propeller_diameter_m: 0.33,
            camera_payload: true,
            questions: ["Which camera sensor should the prototype carry?"],
          }),
        },
      }],
      usage: { prompt_tokens: 90, completion_tokens: 70, total_tokens: 160 },
    });

    const result = await compileHostedAssistantTurn({
      grant: GRANT,
      edition: "universal",
      locale: "en",
      messageId: "turn-3",
      message: "Create a six-motor inspection drone with a camera.",
      conversationSummary: "",
      currentValues: {},
      documentContext: null,
    });

    expect(result.accepted_patches).toEqual(expect.arrayContaining([
      expect.objectContaining({ field_id: "vehicle_mass_kg", value: 4.2 }),
      expect.objectContaining({ field_id: "motor_count", value: 6 }),
      expect.objectContaining({ field_id: "camera_payload", value: true }),
    ]));
    expect(result.experiment_summary).toContain("editable");
  });
});
