import { buildModelCatalog, type ModelPolicyRow } from "./index.ts";

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
    Array.isArray(catalog.models) && catalog.models.length === 2,
    "catalog rows missing",
  );
  const serialized = JSON.stringify(catalog);
  assert(
    !/api[_-]?key|secret|token/iu.test(serialized),
    "catalog leaked credential material",
  );
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
