import {
  buildModelCatalog,
  MANAGED_MODELS,
  managedProviderReasoningPolicy,
  publicModelGatewayBaseUrl,
  reconcileManagedUsage,
  type ModelPolicyRow,
} from "./index.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

Deno.test("model catalog exposes bounded provider policy without credentials", () => {
  const rows: ModelPolicyRow[] = [
    {
      provider: "deepseek",
      enabled: true,
      assistant_enabled: true,
      job_enabled: false,
      version: 8,
    },
    {
      provider: "openai",
      enabled: false,
      assistant_enabled: false,
      job_enabled: false,
      version: 3,
    },
  ];
  const catalog = buildModelCatalog(rows);
  assert(
    catalog.policy_version === 8,
    "catalog must expose the latest policy version",
  );
  assert(
    typeof catalog.generated_at === "string",
    "catalog must be timestamped",
  );
  assert(
    Array.isArray(catalog.models) && catalog.models.length === 5,
    "catalog rows missing",
  );
  const serialized = JSON.stringify(catalog);
  assert(
    !/api[_-]?key|secret|token/iu.test(serialized),
    "catalog leaked credential material",
  );
});

Deno.test("managed catalog exposes the two current Kimi choices", () => {
  const kimi = MANAGED_MODELS.filter((model) => model.provider === "kimi");
  assert(kimi.length === 2, "Kimi model count changed unexpectedly");
  assert(kimi[0].model === "kimi-k2.6", "Kimi K2.6 is missing");
  assert(kimi[1].model === "kimi-k3", "Kimi K3 is missing");
});

Deno.test("managed Kimi K2.6 calls reserve output for the final JSON artifact", () => {
  assert(
    JSON.stringify(managedProviderReasoningPolicy("kimi", "kimi-k2.6")) ===
      JSON.stringify({ thinking: { type: "disabled" } }),
    "Kimi K2.6 must not spend the bounded response budget on hidden thinking",
  );
  assert(
    Object.keys(managedProviderReasoningPolicy("kimi", "kimi-k3")).length === 0,
    "the K2.6 policy must not leak into another model",
  );
  assert(
    Object.keys(managedProviderReasoningPolicy("openai", "gpt-5.4")).length ===
      0,
    "the Kimi policy must not leak into another provider",
  );
});

Deno.test("model grants expose the public HTTPS Functions endpoint", () => {
  assert(
    publicModelGatewayBaseUrl("https://project-ref.supabase.co") ===
      "https://project-ref.supabase.co/functions/v1/model-gateway",
    "grant URLs must not inherit an Edge Runtime internal request path",
  );
  let rejected = false;
  try {
    publicModelGatewayBaseUrl("http://project-ref.supabase.co/model-gateway");
  } catch {
    rejected = true;
  }
  assert(rejected, "an internal or insecure gateway origin must be rejected");
});

Deno.test("model catalog rejects malformed provider policy", () => {
  let rejected = false;
  try {
    buildModelCatalog([{
      provider: "openai",
      enabled: true,
      assistant_enabled: true,
      job_enabled: true,
      version: 0,
    }]);
  } catch {
    rejected = true;
  }
  assert(rejected, "invalid policy version must be rejected");
});

Deno.test("managed usage settles actual provider tokens with output weighting", () => {
  const usage = reconcileManagedUsage({
    prompt_tokens: 120,
    completion_tokens: 30,
    total_tokens: 150,
  }, 8_000, 4);
  assert(usage.input_tokens === 120, "input tokens were not preserved");
  assert(usage.output_tokens === 30, "output tokens were not preserved");
  assert(usage.total_tokens === 150, "total tokens were not preserved");
  assert(usage.consumed_credits === 240, "weighted credits were calculated incorrectly");
  assert(usage.estimated === false, "valid provider usage must not be estimated");
});

Deno.test("managed usage charges the reservation when provider usage is incomplete", () => {
  const usage = reconcileManagedUsage({
    prompt_tokens: 120,
    completion_tokens: 30,
    total_tokens: 149,
  }, 8_000, 4);
  assert(usage.input_tokens === null, "invalid usage must not be recorded as actual");
  assert(usage.output_tokens === null, "invalid usage must not be recorded as actual");
  assert(usage.total_tokens === null, "invalid usage must not be recorded as actual");
  assert(usage.consumed_credits === 8_000, "invalid usage must consume the reservation");
  assert(usage.estimated === true, "fallback usage must be marked estimated");
});
