import { beforeEach, describe, expect, it } from "vitest";

import {
  applyAssistantTurn,
  loadAssistantDraft,
  recordManualDraftEdits,
} from "../features/experiment/assistantDraft";
import {
  EXPERIMENT_FORM_DEFAULTS,
} from "../features/experiment/formState";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
} from "../features/experiment/parameterCatalog";
import type {
  ExperimentAssistantParameterPatch,
  ExperimentAssistantTurnResponse,
} from "../types/api";

function response(
  patch: ExperimentAssistantParameterPatch,
): ExperimentAssistantTurnResponse {
  return {
    schema_version: "1.0",
    lifecycle_stage: "proposal",
    model_entrypoint_role: "control_tuning_draft_compiler",
    creates_job: false,
    runtime_execution_performed: false,
    next_required_stage: "review_and_submit_job",
    model_harness_domain: "optimization.control_tuning",
    memory_domain: "optimization.control_tuning",
    control_plane: {
      plugin_selection_effect: "contract_only",
      plugin_runtime_receipt_ids: [],
    },
    harness_input_sha256: "0".repeat(64),
    harness_output: {
      lifecycle_stage: "proposal",
      runtime_execution_performed: false,
    },
    experiment_summary: "Parameter intent compiled.",
    accepted_patches: [],
    rejected_patches: [],
    accepted_parameter_patches: [patch],
    rejected_parameter_patches: [],
    missing_field_ids: [],
    review_field_ids: [],
    questions: [],
    usage: {
      input_tokens: 10,
      output_tokens: 5,
      total_tokens: 15,
      estimated: false,
    },
    provider: "openai",
    model: "test-model",
  };
}

function parameterPatch(
  provenance: ExperimentAssistantParameterPatch["provenance"],
  baseline: number,
  messageId: string | null,
): ExperimentAssistantParameterPatch {
  return {
    name: "MPC_XY_P",
    selected: true,
    baseline,
    search_min: 0.6,
    search_max: 1.3,
    scale: "linear",
    provenance,
    source_message_id: messageId,
  };
}

describe("assistant parameter provenance", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("does not let a later proposed default replace an explicit parameter choice", () => {
    const first = applyAssistantTurn(
      loadAssistantDraft(),
      response(parameterPatch("explicit", 1.0, "turn-1")),
      { id: "turn-1", role: "user", content: "Use MPC_XY_P with baseline 1.0." },
    );

    const second = applyAssistantTurn(
      first,
      response(parameterPatch("proposed_default", 1.1, null)),
      { id: "turn-2", role: "user", content: "Continue." },
    );

    expect(second.selections.MPC_XY_P.baseline).toBe(1.0);
    expect(second.conversation.field_provenance.parameters).toEqual({
      source: "explicit",
      message_id: "turn-1",
    });
  });

  it("allows a later explicit correction to replace an explicit parameter choice", () => {
    const first = applyAssistantTurn(
      loadAssistantDraft(),
      response(parameterPatch("explicit", 1.0, "turn-1")),
      { id: "turn-1", role: "user", content: "Use a baseline of 1.0." },
    );

    const second = applyAssistantTurn(
      first,
      response(parameterPatch("explicit", 1.1, "turn-2")),
      { id: "turn-2", role: "user", content: "Change the baseline to 1.1." },
    );

    expect(second.selections.MPC_XY_P.baseline).toBe(1.1);
    expect(second.conversation.field_provenance.parameters).toEqual({
      source: "explicit",
      message_id: "turn-2",
    });
  });

  it("records later wizard edits as explicit without recording model credentials", () => {
    const selections = createParameterSelections(
      BUILTIN_PARAMETER_CATALOG.parameters,
      "basic",
    );
    const nextSelections = {
      ...selections,
      MPC_XY_P: {
        ...selections.MPC_XY_P,
        baseline: 1.1,
      },
    };
    const conversation = recordManualDraftEdits(
      null,
      EXPERIMENT_FORM_DEFAULTS,
      {
        ...EXPERIMENT_FORM_DEFAULTS,
        altitude_m: "4",
        llm_model: "private-model",
      },
      selections,
      nextSelections,
    );

    expect(conversation?.field_provenance).toEqual({
      altitude_m: { source: "explicit" },
      parameters: { source: "explicit" },
    });
  });
});
