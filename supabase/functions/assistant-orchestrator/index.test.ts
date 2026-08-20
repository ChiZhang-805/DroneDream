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
  autonomy: {
    kind: "simulation_experiment",
    draft: {
      scenario: {}, trajectory: {}, objectives: [], metrics: [], constraints: [],
      budget: {}, seeds: [], assumptions: [],
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

function autonomyRequestContext({ ready }: { ready: boolean }): Record<string, unknown> {
  return {
    requested_task_type: "mission_autonomy",
    current_values: {
      autonomy_context: {
        context_sha256: "a".repeat(64),
        selected_aircraft: {
          kind: "aircraft",
          asset_id: "aircraft-primary",
          name: "Primary research quadrotor",
          version: 2,
          status: ready ? "validated-unsigned" : "draft",
          content_hash: null,
          qualification_receipt_id: ready ? "vehicle-receipt-v2" : null,
          capabilities: { localization_sources: ["gps", "vio"] },
        },
        selected_map: {
          kind: "map",
          asset_id: "map-building",
          name: "Engineering Building",
          version: 4,
          status: ready ? "qualified" : "draft",
          content_hash: ready ? "b".repeat(64) : null,
          qualification_receipt_id: ready ? "map-receipt-v4" : null,
          capabilities: {
            planning_layers: ready ? ["collision-geometry", "occupancy", "esdf"] : [],
            compiler_scene_id: ready ? "stairwell-coffee-return" : null,
          },
        },
      },
    },
  };
}

function autonomyPlan({ ready }: { ready: boolean }): string {
  const blockers = ready
    ? []
    : [
      "aircraft.pack.not-validated",
      "aircraft.qualification-receipt.missing",
      "map.pack.not-qualified",
      "map.content-hash.missing",
      "map.qualification-receipt.missing",
      "map.collision-layers.missing",
      "map.compiler-scene.unbound",
    ];
  return JSON.stringify({
    artifact_kind: "autonomy_mission_plan",
    artifact_title: "Coffee return mission",
    intent: "mission_autonomy",
    assistant_message: ready
      ? "I bound the selected assets and prepared a reviewable mission draft."
      : "I saved the intent, but the selected assets are not yet qualified.",
    conversation_summary: "The user requested a bounded autonomous mission.",
    workflow: [{
      step: "asset_gate",
      label: "Bind and validate the selected aircraft and map",
      status: ready ? "completed" : "needs_input",
    }],
    draft: {
      schema_version: "dronedream.autonomy.planner-response.v1",
      status: ready ? "draft" : "needs_assets",
      goal: "Collect coffee and return to the office",
      asset_bindings: {
        aircraft_id: "aircraft-primary",
        aircraft_version: 2,
        map_id: "map-building",
        map_version: 4,
        context_sha256: "a".repeat(64),
      },
      grounded_entities: [],
      task_graph: {
        nodes: ready ? [
          {
            node_id: "takeoff",
            action: "takeoff",
            target: "office launch pad",
            depends_on: [],
            success_evidence: ["airborne telemetry"],
          },
          {
            node_id: "pickup",
            action: "pickup",
            target: "coffee pickup",
            depends_on: ["takeoff"],
            success_evidence: ["payload attached"],
          },
          {
            node_id: "return",
            action: "return",
            target: "office launch pad",
            depends_on: ["pickup"],
            success_evidence: ["office return reached"],
          },
          {
            node_id: "land",
            action: "land",
            target: "office launch pad",
            depends_on: ["return"],
            success_evidence: ["landed telemetry"],
          },
        ] : [],
      },
      tool_requests: [],
      tool_receipts: [],
      assumptions: [],
      blockers,
      repair: { attempt: 0, max_attempts: 3, repeated_plan_hashes: 0, stop_reason: null },
      safety_policy: {
        actuator_authority: false,
        may_relax_constraints: false,
        execution_requires_deterministic_validation: true,
      },
    },
    questions: ready ? [] : ["Please qualify the selected aircraft and map."],
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
  const result = parseAssistantPlan(
    autonomyPlan({ ready: true }),
    "sim",
    "mission_autonomy",
    autonomyRequestContext({ ready: true }),
  );
  assertEquals(result.intent, "mission_autonomy");
  assertEquals(result.artifact_kind, "autonomy_mission_plan");
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

Deno.test("rejects a ready autonomy draft when the selected assets are not qualified", () => {
  assertThrows(() => parseAssistantPlan(
    autonomyPlan({ ready: true }),
    "sim",
    "mission_autonomy",
    autonomyRequestContext({ ready: false }),
  ));
});

Deno.test("accepts a needs-assets response only when it preserves authoritative blockers", () => {
  const result = parseAssistantPlan(
    autonomyPlan({ ready: false }),
    "field",
    "mission_autonomy",
    autonomyRequestContext({ ready: false }),
  );
  assertEquals(result.artifact_kind, "autonomy_mission_plan");
  assertEquals(result.draft.status, "needs_assets");
});

Deno.test("rejects model-authored autonomy tool receipts", () => {
  const value = JSON.parse(autonomyPlan({ ready: true }));
  value.draft.tool_receipts = [{ tool_id: "mission.validate_plan", outcome: "accepted" }];
  assertThrows(() => parseAssistantPlan(
    JSON.stringify(value),
    "lab",
    "mission_autonomy",
    autonomyRequestContext({ ready: true }),
  ));
});

Deno.test("rejects duplicate autonomy task dependencies before backend compilation", () => {
  const value = JSON.parse(autonomyPlan({ ready: true }));
  value.draft.task_graph.nodes[1].depends_on = ["takeoff", "takeoff"];
  assertThrows(() => parseAssistantPlan(
    JSON.stringify(value),
    "sim",
    "mission_autonomy",
    autonomyRequestContext({ ready: true }),
  ));
});

Deno.test("rejects an autonomy request outside the closed eligible tool set", () => {
  const value = JSON.parse(autonomyPlan({ ready: false }));
  value.draft.tool_requests = [{
    tool_id: "trajectory.plan_segment",
    arguments: {},
    reason: "Plan before assets are ready",
    evidence_required: [],
  }];
  assertThrows(() => parseAssistantPlan(
    JSON.stringify(value),
    "universal",
    "mission_autonomy",
    autonomyRequestContext({ ready: false }),
  ));
});

Deno.test("requires the model repair counter to match the server-owned attempt", () => {
  const request = autonomyRequestContext({ ready: true });
  const plan = JSON.parse(autonomyPlan({ ready: true }));
  plan.draft.repair = {
    attempt: 0,
    max_attempts: 3,
    repeated_plan_hashes: 0,
    stop_reason: null,
  };
  assertThrows(
    () => parseAssistantPlan(
      JSON.stringify(plan),
      "universal",
      "mission_autonomy",
      request,
      1,
      0,
    ),
    Error,
    "repair state is invalid",
  );
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
