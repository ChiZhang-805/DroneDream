import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function completedRun() {
  return {
    run_id: "11111111-1111-4111-8111-111111111111",
    conversation_id: "22222222-2222-4222-8222-222222222222",
    tenant_id: "33333333-3333-4333-8333-333333333333",
    organization_id: null,
    owner_user_id: "33333333-3333-4333-8333-333333333333",
    edition: "sim",
    workspace_id: "workspace_sim_01",
    sequence: 1,
    provider: "openai",
    model: "gpt-4.1",
    state: "completed",
    stage: "completed",
    intent: "simulation_draft",
    workflow_json: [
      { step: "draft", label: "Prepare simulation draft", status: "completed" },
    ],
    result_json: {
      response: {
        schema_version: "1.0",
        experiment_summary: "A bounded simulation experiment draft.",
        accepted_patches: [],
        rejected_patches: [],
        accepted_parameter_patches: [],
        rejected_parameter_patches: [],
        missing_field_ids: [],
        review_field_ids: [],
        questions: [],
        usage: {
          input_tokens: null,
          output_tokens: null,
          total_tokens: null,
          estimated: false,
        },
        provider: "dronedream",
        model: "gpt-4.1",
      },
      assistant_message: "I prepared the draft without running it.",
      questions: [],
      artifact_kind: "simulation_experiment",
      artifact_sha256: "b".repeat(64),
      artifact_id: "44444444-4444-4444-8444-444444444444",
      artifact_version: 1,
      generated_files: [{
        file_id: "77777777-7777-4777-8777-777777777777",
        display_name: "simulation_experiment.json",
        content_type: "application/json",
        byte_size: 384,
        content_sha256: "a".repeat(64),
        version: 1,
      }],
      product_link:
        "/console/assistant?edition=sim&experiment=workspace_sim_01&artifact=44444444-4444-4444-8444-444444444444",
      conversation_id: "22222222-2222-4222-8222-222222222222",
      run_id: "11111111-1111-4111-8111-111111111111",
      sequence: 1,
      tenant_id: "33333333-3333-4333-8333-333333333333",
      organization_id: null,
      workspace_id: "workspace_sim_01",
      edition: "sim",
    },
    error_code: null,
    error_message: null,
    attempt_count: 1,
    max_attempts: 3,
    next_attempt_at: null,
    timeout_at: "2026-08-13T00:05:00.000Z",
    updated_at: "2026-08-13T00:00:00.000Z",
  };
}

describe("assistant orchestration client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv(
      "VITE_ASSISTANT_ORCHESTRATOR_URL",
      "https://example.supabase.co/functions/v1/assistant-orchestrator",
    );
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("sends the authenticated edition-bound turn and returns its sealed artifact", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: completedRun() }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    const result = await orchestrateAssistantTurn({
      edition: "sim",
      workspaceId: "workspace_sim_01",
      idempotencyKey: "assistant:turn-001",
      message: "Prepare a bounded hover experiment.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: { altitude_m: 3 },
      documentContext: null,
    });

    expect(result.response.orchestration).toMatchObject({
      run_id: completedRun().run_id,
      artifact_kind: "simulation_experiment",
      artifact_id: completedRun().result_json.artifact_id,
    });
    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer signed-user-token");
    expect(headers["Idempotency-Key"]).toBe("assistant:turn-001");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      edition: "sim",
      workspace_id: "workspace_sim_01",
      provider: "openai",
      model: "gpt-4.1",
    });
  });

  it("accepts an AUTONOMY run and its sealed mission artifact", async () => {
    const run = completedRun();
    run.edition = "autonomy";
    run.workspace_id = "workspace_autonomy_01";
    run.result_json.artifact_kind = "autonomy_mission_plan";
    run.result_json.product_link =
      "/console/assistant?edition=autonomy&experiment=workspace_autonomy_01&artifact=44444444-4444-4444-8444-444444444444";
    run.result_json.workspace_id = "workspace_autonomy_01";
    run.result_json.edition = "autonomy";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: run }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    const result = await orchestrateAssistantTurn({
      edition: "autonomy",
      workspaceId: "workspace_autonomy_01",
      idempotencyKey: "assistant:autonomy-turn-001",
      message: "Plan a qualified inspection mission.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    });

    expect(result.run.edition).toBe("autonomy");
    expect(result.run.result_json?.artifact_kind).toBe("autonomy_mission_plan");
  });

  it("carries an explicit organization boundary on both write and restore", async () => {
    const organizationId = "44444444-4444-4444-8444-444444444444";
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: completedRun() }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { getAssistantWorkspace, orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await orchestrateAssistantTurn({
      edition: "sim",
      workspaceId: "workspace_sim_01",
      organizationId,
      idempotencyKey: "assistant:org-turn-001",
      message: "Prepare an organization-scoped draft.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    });
    await getAssistantWorkspace("sim", "workspace_sim_01", organizationId);

    const turnBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(turnBody.organization_id).toBe(organizationId);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `https://example.supabase.co/functions/v1/assistant-orchestrator/workspaces/sim/workspace_sim_01?organization_id=${organizationId}`,
    );
  });

  it("indexes only server workspaces inside the explicit tenant and edition boundary", async () => {
    const ownerId = "33333333-3333-4333-8333-333333333333";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        data: {
          conversations: [{
            conversation_id: "22222222-2222-4222-8222-222222222222",
            tenant_id: ownerId,
            organization_id: null,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            title: "Hover draft",
            summary: "A bounded hover draft.",
            status: "active",
            latest_completed_sequence: 1,
            created_at: "2026-08-13T00:00:00.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
          artifacts: [{
            artifact_id: "44444444-4444-4444-8444-444444444444",
            conversation_id: "22222222-2222-4222-8222-222222222222",
            tenant_id: ownerId,
            organization_id: null,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            artifact_kind: "simulation_experiment",
            title: "Hover draft",
            version: 1,
            status: "draft",
            created_at: "2026-08-13T00:00:01.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
        },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { getAssistantWorkspaceIndex } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    const index = await getAssistantWorkspaceIndex("sim", ownerId);

    expect(index).toMatchObject([{
      workspace_id: "workspace_sim_01",
      tenant_id: ownerId,
      organization_id: null,
      latest_artifact: {
        artifact_kind: "simulation_experiment",
        title: "Hover draft",
      },
    }]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://example.supabase.co/functions/v1/assistant-orchestrator/workspaces/sim",
    );
  });

  it("rejects a workspace index containing another tenant's artifact", async () => {
    const ownerId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        data: {
          conversations: [{
            conversation_id: "22222222-2222-4222-8222-222222222222",
            tenant_id: ownerId,
            organization_id: null,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            title: "Hover draft",
            summary: "A bounded hover draft.",
            status: "active",
            latest_completed_sequence: 1,
            created_at: "2026-08-13T00:00:00.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
          artifacts: [{
            artifact_id: "44444444-4444-4444-8444-444444444444",
            conversation_id: "22222222-2222-4222-8222-222222222222",
            tenant_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            organization_id: null,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            artifact_kind: "simulation_experiment",
            title: "Leaked draft",
            version: 1,
            status: "draft",
            created_at: "2026-08-13T00:00:01.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { getAssistantWorkspaceIndex } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await expect(getAssistantWorkspaceIndex("sim", ownerId))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("fails before networking when no signed-in account token is present", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken(null);

    await expect(orchestrateAssistantTurn({
      edition: "field",
      workspaceId: "workspace_field_01",
      idempotencyKey: "assistant:turn-002",
      message: "Prepare a field task plan.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    })).rejects.toMatchObject({ code: "AUTHENTICATION_REQUIRED" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a completed response without a sealed edition artifact", async () => {
    const invalid = completedRun();
    invalid.result_json.artifact_kind = "field_task_plan";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: invalid }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await expect(orchestrateAssistantTurn({
      edition: "sim",
      workspaceId: "workspace_sim_01",
      idempotencyKey: "assistant:turn-003",
      message: "Prepare a simulation draft.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a sealed result whose identity does not match its run", async () => {
    const invalid = completedRun();
    invalid.result_json.run_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: invalid }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await expect(orchestrateAssistantTurn({
      edition: "sim",
      workspaceId: "workspace_sim_01",
      idempotencyKey: "assistant:turn-identity",
      message: "Prepare a simulation draft.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a run with a malformed workflow boundary", async () => {
    const invalid = completedRun();
    invalid.workflow_json = [
      { step: "draft", label: "Draft", status: "completed", private_reasoning: "hidden" },
    ] as unknown as typeof invalid.workflow_json;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: invalid }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { orchestrateAssistantTurn } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await expect(orchestrateAssistantTurn({
      edition: "sim",
      workspaceId: "workspace_sim_01",
      idempotencyKey: "assistant:turn-workflow",
      message: "Prepare a simulation draft.",
      locale: "en",
      selectedModel: { provider: "openai", model: "gpt-4.1" },
      currentValues: {},
      documentContext: null,
    })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("restores only an authenticated workspace inside the requested edition boundary", async () => {
    const run = completedRun();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        data: {
          conversation: {
            conversation_id: run.conversation_id,
            tenant_id: run.tenant_id,
            organization_id: run.organization_id,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            title: "Hover draft",
            summary: "A bounded hover draft.",
            status: "active",
            latest_completed_sequence: 1,
            created_at: "2026-08-13T00:00:00.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          },
          messages: [{
            message_id: "55555555-5555-4555-8555-555555555555",
            run_id: run.run_id,
            sequence: 1,
            role: "assistant",
            content: "The SIM draft is ready.",
            created_at: "2026-08-13T00:00:01.000Z",
          }],
          artifacts: [{
            artifact_id: run.result_json.artifact_id,
            run_id: run.run_id,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            artifact_kind: "simulation_experiment",
            title: "Hover draft",
            payload_json: { scenario: { track: "hover" } },
            version: 1,
            status: "draft",
            created_at: "2026-08-13T00:00:01.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
          runs: [run],
          steps: [],
          files: [],
        },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const {
      getAssistantWorkspace,
      latestCompletedAssistantResponse,
    } = await import("../features/experiment/assistantOrchestration");
    setAuthAccessToken("signed-user-token");

    const snapshot = await getAssistantWorkspace("sim", "workspace_sim_01");

    expect(snapshot?.messages[0]?.content).toBe("The SIM draft is ready.");
    expect(snapshot?.artifacts[0]?.artifact_kind).toBe("simulation_experiment");
    expect(snapshot && latestCompletedAssistantResponse(snapshot)?.orchestration)
      .toMatchObject({ artifact_kind: "simulation_experiment", sequence: 1 });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://example.supabase.co/functions/v1/assistant-orchestrator/workspaces/sim/workspace_sim_01",
    );
  });

  it("rejects a workspace snapshot containing a cross-edition artifact", async () => {
    const run = completedRun();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        data: {
          conversation: {
            conversation_id: run.conversation_id,
            tenant_id: run.tenant_id,
            organization_id: run.organization_id,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            title: "SIM",
            summary: "SIM",
            status: "active",
            latest_completed_sequence: 1,
            created_at: "2026-08-13T00:00:00.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          },
          messages: [],
          artifacts: [{
            artifact_id: run.result_json.artifact_id,
            run_id: run.run_id,
            edition: "sim",
            workspace_id: "workspace_sim_01",
            artifact_kind: "field_task_plan",
            title: "Wrong boundary",
            payload_json: {},
            version: 1,
            status: "draft",
            created_at: "2026-08-13T00:00:01.000Z",
            updated_at: "2026-08-13T00:00:01.000Z",
          }],
          runs: [run],
          steps: [],
          files: [],
        },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { setAuthAccessToken } = await import("../features/auth/authTokenStore");
    const { getAssistantWorkspace } = await import(
      "../features/experiment/assistantOrchestration"
    );
    setAuthAccessToken("signed-user-token");

    await expect(getAssistantWorkspace("sim", "workspace_sim_01"))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
