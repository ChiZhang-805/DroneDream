import { beforeEach, describe, expect, it, vi } from "vitest";

const supabase = vi.hoisted(() => ({
  from: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock("../auth/supabaseClient", () => ({
  supabaseClient: supabase,
}));

import {
  deleteConsolePreferencesAndMemory,
  forgetConsoleMemoryDomain,
  forgetConsoleMemoryRecord,
  loadConsoleMemoryConsent,
  loadConsoleMemory,
  permanentlyDeleteConsoleMemory,
  resolveConsoleMemoryCandidate,
  saveConsoleMemoryConsent,
  type ConsolePreferenceBoundary,
} from "./consolePreferences";

const boundary: ConsolePreferenceBoundary = {
  userId: "11111111-1111-4111-8111-111111111111",
  tenantId: "11111111-1111-4111-8111-111111111111",
  organizationId: null,
  workspaceId: "console-sim",
  edition: "sim",
};

function queryBuilder(result: Record<string, unknown>) {
  const builder = {
    delete: vi.fn(),
    eq: vi.fn(),
    gt: vi.fn(),
    in: vi.fn(),
    limit: vi.fn(),
    maybeSingle: vi.fn(),
    order: vi.fn(),
    select: vi.fn(),
    upsert: vi.fn(),
    then: (
      resolve: (value: Record<string, unknown>) => unknown,
      reject: (reason: unknown) => unknown,
    ) => Promise.resolve(result).then(resolve, reject),
  };
  for (const method of [
    builder.delete,
    builder.eq,
    builder.gt,
    builder.in,
    builder.limit,
    builder.maybeSingle,
    builder.order,
    builder.select,
    builder.upsert,
  ]) {
    method.mockReturnValue(builder);
  }
  return builder;
}

describe("account and responsibility bounded memory management", () => {
  beforeEach(() => {
    supabase.from.mockReset();
    supabase.rpc.mockReset();
  });

  it("forgets one record without sending a browser-supplied user id", async () => {
    supabase.rpc.mockResolvedValue({ data: 2, error: null });

    await expect(forgetConsoleMemoryRecord(boundary, {
      responsibility_namespace: "experiment.simulation",
      scope: "experiment_defaults",
      memory_key: "experiment_defaults.altitude_m",
    })).resolves.toBe(2);

    expect(supabase.rpc).toHaveBeenCalledWith(
      "console_memory_forget_current_user",
      {
        p_tenant_id: boundary.tenantId,
        p_organization_id: "00000000-0000-0000-0000-000000000000",
        p_responsibility_namespace: "experiment.simulation",
        p_scope: "experiment_defaults",
        p_memory_key: "experiment_defaults.altitude_m",
      },
    );
    expect(supabase.rpc.mock.calls[0][1]).not.toHaveProperty("p_user_id");
  });

  it("forgets a whole responsibility domain through the same bounded RPC", async () => {
    supabase.rpc.mockResolvedValue({ data: 4, error: null });

    await expect(
      forgetConsoleMemoryDomain(boundary, "autonomy.mission"),
    ).resolves.toBe(4);

    expect(supabase.rpc).toHaveBeenCalledWith(
      "console_memory_forget_current_user",
      expect.objectContaining({
        p_responsibility_namespace: "autonomy.mission",
        p_scope: null,
        p_memory_key: null,
      }),
    );
  });

  it("permanently deletes all account memory through one explicit RPC", async () => {
    supabase.rpc.mockResolvedValue({ data: 7, error: null });
    const preferencesDelete = queryBuilder({ error: null });
    supabase.from.mockReturnValue(preferencesDelete);

    await expect(deleteConsolePreferencesAndMemory(boundary)).resolves.toBe(7);

    expect(supabase.rpc).toHaveBeenCalledTimes(1);
    expect(supabase.rpc).toHaveBeenCalledWith(
      "console_memory_permanently_delete_all_current_user",
      {
        p_tenant_id: boundary.tenantId,
        p_organization_id: "00000000-0000-0000-0000-000000000000",
      },
    );
    expect(supabase.from).toHaveBeenCalledWith("console_memory_consents");
    expect(supabase.from).toHaveBeenCalledWith("console_preferences");
  });

  it("keeps soft forget and permanent delete as different operations", async () => {
    supabase.rpc.mockResolvedValue({ data: 1, error: null });
    await permanentlyDeleteConsoleMemory(boundary, {
      responsibilityNamespace: "autonomy.mission",
      scope: "workflow_tools",
      memoryKey: "workflow_tools.route_policy",
    });
    expect(supabase.rpc).toHaveBeenCalledWith(
      "console_memory_permanently_delete_current_user",
      expect.objectContaining({
        p_responsibility_namespace: "autonomy.mission",
        p_scope: "workflow_tools",
        p_memory_key: "workflow_tools.route_policy",
      }),
    );
  });

  it("stores account-wide read/write consent separately from edition preferences", async () => {
    const consent = {
      memory_enabled: true,
      read_namespaces: ["account.shared"] as const,
      write_namespaces: ["experiment.simulation"] as const,
      memory_scopes: { chat_preferences: true },
    };
    const loadBuilder = queryBuilder({ data: consent, error: null });
    const saveBuilder = queryBuilder({ error: null });
    supabase.from.mockReturnValueOnce(loadBuilder).mockReturnValueOnce(saveBuilder);

    await expect(loadConsoleMemoryConsent(boundary)).resolves.toEqual(consent);
    await expect(saveConsoleMemoryConsent(boundary, consent as never)).resolves.toBeUndefined();
    expect(supabase.from).toHaveBeenNthCalledWith(1, "console_memory_consents");
    expect(supabase.from).toHaveBeenNthCalledWith(2, "console_memory_consents");
  });

  it("loads consolidated memory across source editions within selected domains", async () => {
    const memory = {
      responsibility_namespace: "optimization.control_tuning",
      scope: "metrics_constraints",
      memory_key: "metrics_constraints.altitude_m",
      memory_kind: "structured_state",
      payload: { value: 3 },
      evidence_count: 2,
      confidence: 0.86,
      first_seen: "2026-08-20T00:00:00.000Z",
      last_seen: "2026-08-24T00:00:00.000Z",
    };
    const recordsQuery = queryBuilder({ data: [memory], error: null });
    supabase.from.mockReturnValue(recordsQuery);

    await expect(loadConsoleMemory(
      boundary,
      ["metrics_constraints"],
      ["optimization.control_tuning"],
    )).resolves.toEqual([memory]);

    expect(supabase.from).toHaveBeenCalledWith("console_memory_records");
    expect(recordsQuery.eq).not.toHaveBeenCalledWith("workspace_id", expect.anything());
    expect(recordsQuery.eq).not.toHaveBeenCalledWith("edition", expect.anything());
    expect(recordsQuery.in).toHaveBeenCalledWith(
      "responsibility_namespace",
      ["optimization.control_tuning"],
    );
  });

  it("resolves a candidate without sending a user id", async () => {
    const candidate = { candidate_id: "22222222-2222-4222-8222-222222222222" };
    supabase.rpc.mockResolvedValue({ data: candidate, error: null });

    await expect(resolveConsoleMemoryCandidate(
      boundary,
      candidate.candidate_id,
      "reject",
    )).resolves.toEqual(candidate);

    expect(supabase.rpc).toHaveBeenCalledWith(
      "console_memory_resolve_current_user",
      expect.not.objectContaining({ p_user_id: expect.anything() }),
    );
  });
});
