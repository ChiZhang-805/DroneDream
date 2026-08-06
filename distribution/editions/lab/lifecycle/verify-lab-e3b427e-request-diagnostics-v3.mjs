import { strict as assert } from "node:assert";

import {
  classifyRequest,
  requestDiagnosticsEvidence,
} from "./lab-request-origin-diagnostics.mjs";

const cdpEndpoint = "http://127.0.0.1:49321";
const secretQuery = "apikey=do-not-persist&token=do-not-persist&email=hidden@example.com";
const fixtures = [
  {
    id: "tauri-app-asset",
    url: "https://tauri.localhost/assets/index.js",
    expected: ["allow", "tauri-app-origin"],
  },
  {
    id: "tauri-ipc-http-origin",
    url: "http://ipc.localhost/",
    expected: ["allow", "tauri-ipc-origin"],
  },
  {
    id: "tauri-asset-origin",
    url: "http://asset.localhost/icon.png",
    expected: ["allow", "tauri-asset-origin"],
  },
  {
    id: "local-backend-with-sensitive-query",
    url: `http://127.0.0.1:8000/api/v1/health?${secretQuery}`,
    expected: ["deny", "local-loopback"],
  },
  {
    id: "localhost-loopback",
    url: "http://localhost:5173/src/main.tsx",
    expected: ["allow", "local-loopback"],
  },
  {
    id: "exact-execution-cdp",
    url: "http://127.0.0.1:49321/json/version",
    expected: ["allow", "execution-owned-cdp"],
  },
  {
    id: "external-supabase",
    url: `https://project.supabase.co/rest/v1/items?${secretQuery}`,
    expected: ["deny", "external-network-origin"],
  },
  {
    id: "external-model-api",
    url: "https://api.example.com/v1/chat/completions?request=hidden",
    expected: ["deny", "external-network-origin"],
  },
  {
    id: "unknown-scheme",
    url: "chrome-extension://extension-id/private/path?secret=hidden",
    expected: ["deny", "unknown-scheme-origin"],
  },
];

const records = fixtures.map((fixture) => {
  const record = classifyRequest(fixture.url, {
    cdpEndpoint,
    resourceType: fixture.id.includes("asset") ? "script" : "fetch",
    observationSource: "playwright-request",
  });
  assert.equal(record.decision, fixture.expected[0], fixture.id);
  assert.equal(record.hostClass, fixture.expected[1], fixture.id);
  return { id: fixture.id, ...record };
});

const evidence = requestDiagnosticsEvidence(records, {
  phase: "fixture",
  status: "fixture-complete",
});
const serialized = JSON.stringify(evidence);
for (const forbidden of [
  "do-not-persist",
  "hidden@example.com",
  "project.supabase.co",
  "api.example.com",
  "extension-id",
  "/api/v1/health",
  "/rest/v1/items",
  "/v1/chat/completions",
]) {
  assert.equal(serialized.includes(forbidden), false, forbidden);
}
assert.equal(evidence.redactionContract.rawUrlPersisted, false);
assert.equal(evidence.redactionContract.queryPersistedOrHashed, false);
assert.equal(evidence.deniedCount, 4);
assert.equal(evidence.allowedCount, 5);
assert.equal(evidence.authSensitiveCount, 2);

console.log(JSON.stringify({
  fixtureCount: fixtures.length,
  allowedCount: evidence.allowedCount,
  deniedCount: evidence.deniedCount,
  authSensitiveCount: evidence.authSensitiveCount,
  redactionPassed: true,
  results: records.map(({ id, decision, hostClass, reason }) => ({
    id,
    decision,
    hostClass,
    reason,
  })),
}));
