import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadCloudAccess() {
  const cloud = await import("../features/settings/cloudModelAccess");
  const auth = await import("../features/auth/authTokenStore");
  return { cloud, auth };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("cloud model access client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv(
      "VITE_MODEL_GATEWAY_URL",
      "https://cloud.example.test/functions/v1/model-gateway",
    );
    vi.stubEnv(
      "VITE_BILLING_CHECKOUT_URL",
      "https://cloud.example.test/functions/v1/billing-checkout",
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("requires a signed-in account before requesting platform usage", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(cloud.getManagedModelUsage()).rejects.toMatchObject({
      name: "CloudModelAccessError",
      code: "AUTHENTICATION_REQUIRED",
      status: 401,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("issues a scoped grant without exposing the platform provider key", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    const snapshot = {
      plan: {
        id: "plus",
        name: "Plus",
        monthly_price_cny_fen: 3_900,
        included_ai_credits: 3_000_000,
        capability_set: "core-v1",
      },
      period: {
        starts_at: "2026-07-01T00:00:00Z",
        ends_at: "2026-08-01T00:00:00Z",
      },
      usage: {
        reserved_ai_credits: 0,
        consumed_ai_credits: 1_200,
        remaining_ai_credits: 2_998_800,
        request_count: 2,
        input_tokens: 400,
        output_tokens: 200,
        total_tokens: 600,
        estimated_request_count: 0,
        credit_policy_version: 1,
      },
      recent_requests: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      data: {
        access_mode: "platform",
        grant: "ddg_one_time_scoped_test_grant_1234567890",
        scope: "job",
        expires_at: "2026-07-27T00:00:00Z",
        max_calls: 128,
        gateway_base_url: "https://cloud.example.test/functions/v1/model-gateway",
        managed_model: "DroneDream Managed",
        usage: snapshot,
      },
    }, 201));
    vi.stubGlobal("fetch", fetchMock);

    const result = await cloud.issueManagedModelGrant("job", "draft-42");

    expect(result).toMatchObject({
      access_mode: "platform",
      scope: "job",
      managed_model: "DroneDream Managed",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://cloud.example.test/functions/v1/model-gateway/grants",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer signed-user-token",
        }),
        body: JSON.stringify({
          scope: "job",
          scope_reference: "draft-42",
          provider: "openai",
          model: "gpt-4.1",
        }),
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("PLATFORM_LLM_API_KEY");
  });

  it("uses a one-time grant for a bounded managed chat completion", async () => {
    const { cloud } = await loadCloudAccess();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: "chat-1",
      model: "DroneDream Managed",
      choices: [{ message: { role: "assistant", content: '{"summary":"ready"}' } }],
      usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await cloud.completeManagedModelChat(
      {
        access_mode: "platform",
        grant: `ddg_${"a".repeat(48)}`,
        scope: "assistant",
        expires_at: "2026-08-08T01:00:00Z",
        max_calls: 1,
        gateway_base_url: "https://cloud.example.test/functions/v1/model-gateway",
        managed_model: "DroneDream Managed",
        usage: {} as never,
      },
      [{ role: "user", content: "Prepare a bounded Field plan." }],
      { type: "json_object" },
    );

    expect(result.choices[0]?.message.content).toContain("summary");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://cloud.example.test/functions/v1/model-gateway/chat/completions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: `Bearer ddg_${"a".repeat(48)}`,
          "Idempotency-Key": expect.any(String),
        }),
        body: JSON.stringify({
          messages: [{ role: "user", content: "Prepare a bounded Field plan." }],
          response_format: { type: "json_object" },
        }),
      }),
    );
  });

  it("rejects a grant gateway outside the managed-model endpoint", async () => {
    const { cloud } = await loadCloudAccess();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(cloud.completeManagedModelChat(
      {
        access_mode: "platform",
        grant: `ddg_${"a".repeat(48)}`,
        scope: "assistant",
        expires_at: "2026-08-08T01:00:00Z",
        max_calls: 1,
        gateway_base_url: "https://attacker.example.test/collect",
        managed_model: "DroneDream Managed",
        usage: {} as never,
      },
      [{ role: "user", content: "test" }],
    )).rejects.toMatchObject({
      code: "MODEL_GATEWAY_INVALID",
      status: 503,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads the centrally filtered model catalog and requests one provider", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    const catalog = {
      policy_version: 8,
      models: [
        {
          provider: "deepseek",
          display_name: "DeepSeek",
          model: "deepseek-chat",
          enabled: true,
          assistant_enabled: true,
          job_enabled: false,
          policy_version: 8,
        },
      ],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ data: catalog }))
      .mockResolvedValueOnce(jsonResponse({
        data: {
          access_mode: "platform",
          grant: "ddg_one_time_scoped_test_grant_1234567890",
          scope: "assistant",
          expires_at: "2026-08-03T00:00:00Z",
          max_calls: 1,
          gateway_base_url: "https://cloud.example.test/functions/v1/model-gateway",
          managed_model: "deepseek-chat",
          usage: {},
        },
      }, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(cloud.getManagedModelCatalog()).resolves.toEqual(catalog);
    await cloud.issueManagedModelGrant(
      "assistant",
      "draft-84",
      "deepseek",
      "deepseek-v4-flash",
    );

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://cloud.example.test/functions/v1/model-gateway/models",
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      body: JSON.stringify({
        scope: "assistant",
        scope_reference: "draft-84",
        provider: "deepseek",
        model: "deepseek-v4-flash",
      }),
    }));
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(/api[_-]?key/iu);
  });

  it("maps an exhausted managed allowance to the typed BYOK boundary", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      error: {
        code: "MODEL_QUOTA_EXHAUSTED",
        message: "Switch to BYOK or upgrade.",
      },
    }, 402)));

    await expect(cloud.issueManagedModelGrant("assistant")).rejects.toMatchObject({
      name: "CloudModelAccessError",
      code: "MODEL_QUOTA_EXHAUSTED",
      status: 402,
      message: "Switch to BYOK or upgrade.",
    });
  });

  it("fails at its deadline when response headers arrive but the body stalls", async () => {
    vi.useFakeTimers();
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream<Uint8Array>({
            pull: () => new Promise<void>(() => undefined),
          }),
        ),
      ),
    );

    const assertion = expect(cloud.getManagedModelUsage()).rejects.toMatchObject({
      name: "CloudModelAccessError",
      code: "NETWORK_ERROR",
      status: 0,
      message: "Request timed out after 30 seconds.",
    });
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });

  it("reports an oversized cloud response without attempting JSON parsing", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("{}", {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": String(1024 * 1024 + 1),
          },
        }),
      ),
    );

    await expect(cloud.getManagedModelUsage()).rejects.toMatchObject({
      name: "CloudModelAccessError",
      code: "RESPONSE_TOO_LARGE",
      status: 200,
      message: "Response exceeded the 1 MiB safety limit.",
    });
  });

  it("loads public plan availability and creates an authenticated checkout", async () => {
    const { cloud, auth } = await loadCloudAccess();
    auth.setAuthAccessToken("signed-user-token");
    const availability = {
      enabled: true,
      billing_mode: "manual_monthly_renewal",
      methods: { alipay: true, wechat: true, card: false },
      entitlement_activation: "verified_server_callback_only",
      plans: [
        {
          id: "free",
          name: "Free",
          monthly_price_cny_fen: 0,
          included_ai_credits: 300_000,
          capability_set: "core-v1",
        },
        {
          id: "plus",
          name: "Plus",
          monthly_price_cny_fen: 3_900,
          included_ai_credits: 3_000_000,
          capability_set: "core-v1",
        },
        {
          id: "pro",
          name: "Pro",
          monthly_price_cny_fen: 12_900,
          included_ai_credits: 15_000_000,
          capability_set: "core-v1",
        },
      ],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ data: availability }))
      .mockResolvedValueOnce(jsonResponse({
        data: {
          order_id: "79ed4e92-7d9d-42ca-8d36-dd0fbd4d1550",
          plan_id: "plus",
          payment_method: "wechat",
          amount_cny_fen: 3_900,
          currency: "CNY",
          expires_at: "2026-07-26T05:30:00Z",
          checkout: {
            kind: "qr_code",
            code_url: "weixin://wxpay/bizpayurl?pr=test",
          },
        },
      }, 201));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "6f882c36-e6df-4a44-af8d-2ae0104f6bf0",
    );

    await expect(cloud.getBillingAvailability()).resolves.toEqual(availability);
    await expect(cloud.createBillingCheckout("plus", "wechat")).resolves.toMatchObject({
      plan_id: "plus",
      checkout: { kind: "qr_code" },
    });

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: "GET",
      headers: expect.not.objectContaining({ Authorization: expect.anything() }),
    }));
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer signed-user-token",
      }),
      body: JSON.stringify({
        plan_id: "plus",
        billing_scope: "individual",
        payment_method: "wechat",
        idempotency_key: "6f882c36-e6df-4a44-af8d-2ae0104f6bf0",
      }),
    }));
  });
});
