import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadEvents() {
  const events = await import("../features/analytics/productEvents");
  const auth = await import("../features/auth/authTokenStore");
  return { events, auth };
}

describe("privacy-safe product events", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv(
      "VITE_PRODUCT_EVENTS_URL",
      "https://cloud.example.test/functions/v1/product-events",
    );
    window.history.replaceState({}, "", "/assistant");
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("sends only the allowlisted event envelope under the signed-in identity", async () => {
    const { events, auth } = await loadEvents();
    auth.setAuthAccessToken("signed-user-token");
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "8fbe5c0e-a4d1-45ba-b8ca-b88c23f53c4f",
    );
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(events.recordProductEvent("assistant_turn_succeeded", {
      access_mode: "platform",
      provider: "deepseek",
      has_reference_files: false,
    })).resolves.toBe(true);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.headers).toEqual(expect.objectContaining({
      Authorization: "Bearer signed-user-token",
    }));
    expect(JSON.parse(String(request.body))).toMatchObject({
      schema_version: 1,
      event_id: "8fbe5c0e-a4d1-45ba-b8ca-b88c23f53c4f",
      name: "assistant_turn_succeeded",
      properties: {
        access_mode: "platform",
        provider: "deepseek",
        has_reference_files: false,
      },
    });
    expect(String(request.body)).not.toMatch(/prompt|api[_-]?key|email|password/iu);
  });

  it("drops events when signed out or when properties exceed the bounded contract", async () => {
    const { events, auth } = await loadEvents();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    auth.setAuthAccessToken(null);
    await expect(events.recordProductEvent("job_created", { source: "manual" }))
      .resolves.toBe(false);

    auth.setAuthAccessToken("signed-user-token");
    await expect(events.recordProductEvent("job_created", {
      unsafe_value: "x".repeat(97),
    })).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never lets analytics delivery failure block the product workflow", async () => {
    const { events, auth } = await loadEvents();
    auth.setAuthAccessToken("signed-user-token");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await expect(events.recordProductEvent("fixed_scenario_selected", {
      template_key: "hover-basics@1",
      difficulty: "simple",
    })).resolves.toBe(false);
  });
});
