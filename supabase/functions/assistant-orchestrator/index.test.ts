import { assertEquals, assertThrows } from "jsr:@std/assert@1";

import {
  parseAssistantPlan,
  sanitizedContextValue,
  type AssistantEdition,
} from "./index.ts";

const contracts: Record<AssistantEdition, { kind: string; draft: Record<string, unknown> }> = {
  universal: {
    kind: "universal_vehicle_model",
    draft: {
      vehicle_type: "quadrotor",
      geometry: {},
      propulsion: {},
      mass_properties: {},
      sensors: [],
      assumptions: [],
    },
  },
  sim: {
    kind: "simulation_experiment",
    draft: {
      scenario: {}, trajectory: {}, objectives: [], metrics: [], constraints: [],
      budget: {}, seeds: [], assumptions: [],
    },
  },
  lab: {
    kind: "lab_hardware_validation",
    draft: {
      validation_goal: "calibration", vehicle_identity: {}, simulation_evidence: [],
      hardware_checks: [], qualification_gates: [], holdout: {}, assumptions: [],
    },
  },
  field: {
    kind: "field_task_plan",
    draft: {
      task_goal: "bounded hover", vehicle_identity: {}, snapshot: {}, bounded_steps: [],
      abort_limits: {}, telemetry: [], operator_approval: false, rollback: {}, assumptions: [],
    },
  },
};

function plan(edition: AssistantEdition): string {
  const contract = contracts[edition];
  return JSON.stringify({
    artifact_kind: contract.kind,
    artifact_title: `${edition} draft`,
    intent: `${edition}_draft`,
    assistant_message: "I prepared a reviewable draft without running it.",
    conversation_summary: "The user requested one bounded draft.",
    workflow: [{ step: "draft", label: "Prepare the edition-bound draft", status: "completed" }],
    draft: contract.draft,
    questions: [],
  });
}

Deno.test("accepts every edition's own artifact contract", () => {
  for (const edition of Object.keys(contracts) as AssistantEdition[]) {
    const result = parseAssistantPlan(plan(edition), edition);
    assertEquals(result.artifact_kind, contracts[edition].kind);
  }
});

Deno.test("rejects an artifact from another edition", () => {
  assertThrows(() => parseAssistantPlan(plan("field"), "sim"));
});

Deno.test("honors an explicitly selected task workflow", () => {
  const value = JSON.parse(plan("sim"));
  value.intent = "mission_autonomy";
  const result = parseAssistantPlan(
    JSON.stringify(value),
    "sim",
    "mission_autonomy",
  );
  assertEquals(result.intent, "mission_autonomy");
  assertEquals(result.artifact_kind, "simulation_experiment");
});

Deno.test("rejects a model that changes an explicitly selected task", () => {
  const value = JSON.parse(plan("sim"));
  value.intent = "control_tuning";
  assertThrows(() => parseAssistantPlan(
    JSON.stringify(value),
    "sim",
    "mission_autonomy",
  ));
});

Deno.test("requires auto-routing to return an edition-valid task type", () => {
  const value = JSON.parse(plan("field"));
  value.intent = "vehicle_modeling";
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "field", null));
});

Deno.test("rejects unexpected top-level fields", () => {
  const value = JSON.parse(plan("sim"));
  value.private_reasoning = "must never be accepted";
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "sim"));
});

Deno.test("rejects an incomplete edition artifact", () => {
  const value = JSON.parse(plan("field"));
  delete value.draft.operator_approval;
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "field"));
});

Deno.test("rejects a draft with the wrong deep field type", () => {
  const value = JSON.parse(plan("field"));
  value.draft.operator_approval = "false";
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "field"));
});

Deno.test("rejects model-granted field operator approval", () => {
  const value = JSON.parse(plan("field"));
  value.draft.operator_approval = true;
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "field"));
});

Deno.test("rejects unexpected draft fields", () => {
  const value = JSON.parse(plan("sim"));
  value.draft.execution_command = "run now";
  assertThrows(() => parseAssistantPlan(JSON.stringify(value), "sim"));
});

Deno.test("removes nested and camel-case credential fields from model context", () => {
  assertEquals(sanitizedContextValue({
    altitude_m: 3,
    apiKey: "do-not-send",
    accessToken: "do-not-send",
    nested: {
      clientSecret: "do-not-send",
      password: "do-not-send",
      safeLabel: "hover",
    },
    list: [{ authorization: "do-not-send", metric: "rmse" }],
  }), {
    altitude_m: 3,
    nested: { safeLabel: "hover" },
    list: [{ metric: "rmse" }],
  });
});

Deno.test("redacts credential values embedded in otherwise safe text fields", () => {
  assertEquals(sanitizedContextValue({
    notes: "hover test; API key: placeholder-value-for-redaction; keep 3 m altitude",
    label: "token=temporary-secret, stable hover",
  }), {
    notes: "hover test; [redacted] keep 3 m altitude",
    label: "[redacted] stable hover",
  });
});
