import { afterEach, describe, expect, it, vi } from "vitest";

import {
  dryRunAgentCoreHarness,
  editAgentCoreHarness,
  getAgentCoreHarnessCatalog,
  getAgentCoreHarnessState,
  listAgentCoreHarnessReceipts,
} from "../features/autonomy/agentCore";

function responseBody(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function requestBody(value: unknown): unknown {
  const body = (value as { request?: { bodyBase64?: string | null } }).request?.bodyBase64;
  if (!body) return null;
  const binary = atob(body);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
}

afterEach(() => {
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("Harness designer desktop API", () => {
  it("uses the real revision endpoints and preserves optimistic concurrency metadata", async () => {
    const requests: Array<{ method: string; path: string; body: unknown }> = [];
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (_command: string, value?: unknown) => {
          const request = (value as { request: { method: string; path: string } }).request;
          requests.push({ method: request.method, path: request.path, body: requestBody(value) });
          return {
            status: 200,
            contentType: "application/json",
            bodyBase64: responseBody(request.path.endsWith("/catalog")
              ? { schema_version: "dronedream.harness-catalog.v1", node_descriptors: [], topology_templates: [], plugins: [], profiles: [], context_commands: {} }
              : request.path.includes("receipts")
                ? []
                : request.path.includes("dry-run")
                  ? { valid: true, layers: [], external_calls_executed: 0 }
                  : { active: { revision: 7 }, current: { revision: 7 } }),
          };
        }),
      },
    };

    await getAgentCoreHarnessCatalog();
    await getAgentCoreHarnessState();
    await editAgentCoreHarness({
      schema_version: "dronedream.harness-edit-operation.v1",
      client_operation_id: "test-operation",
      base_revision: 7,
      operation: "move_node",
      payload: { node_id: "mission.intent-parse", x: 120, y: 80 },
    });
    await dryRunAgentCoreHarness();
    await listAgentCoreHarnessReceipts(42);

    expect(requests.map(({ method, path }) => `${method} ${path}`)).toEqual([
      "GET /v1/harness/catalog",
      "GET /v1/harness/topologies/current",
      "PATCH /v1/harness/topologies/current",
      "POST /v1/harness/topologies/dry-run",
      "GET /v1/harness/receipts?limit=42",
    ]);
    expect(requests[2]?.body).toMatchObject({
      base_revision: 7,
      client_operation_id: "test-operation",
      operation: "move_node",
    });
  });
});
