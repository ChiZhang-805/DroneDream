import assert from "node:assert/strict";
import test from "node:test";

import { pruneGitHubPagesDeployments } from "./prune-github-pages-deployments.mjs";

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function deployment(id, createdAt) {
  return { id, environment: "github-pages", created_at: createdAt };
}

function mockGitHub({ deployments, states }) {
  const deletes = [];
  const normalized = [];
  const calls = [];
  const fetchImpl = async (input, options = {}) => {
    const url = new URL(input);
    const method = options.method ?? "GET";
    calls.push({ method, url });
    if (url.pathname.endsWith("/deployments") && method === "GET") {
      const page = Number(url.searchParams.get("page"));
      const start = (page - 1) * 100;
      return jsonResponse(deployments.slice(start, start + 100));
    }
    const statusMatch = url.pathname.match(/\/deployments\/(\d+)\/statuses$/u);
    if (statusMatch && method === "GET") {
      return jsonResponse([{ state: states.get(Number(statusMatch[1])) }]);
    }
    if (statusMatch && method === "POST") {
      const id = Number(statusMatch[1]);
      const payload = JSON.parse(options.body);
      assert.equal(payload.state, "inactive");
      normalized.push(id);
      states.set(id, "inactive");
      return jsonResponse({ state: "inactive" }, 201);
    }
    const deleteMatch = url.pathname.match(/\/deployments\/(\d+)$/u);
    if (deleteMatch && method === "DELETE") {
      deletes.push(Number(deleteMatch[1]));
      return new Response(null, { status: 204 });
    }
    return jsonResponse({ message: "unexpected request" }, 404);
  };
  return { calls, deletes, fetchImpl, normalized };
}

test("keeps the newest successful Pages deployment and deletes only audited inactive records", async () => {
  const github = mockGitHub({
    deployments: [
      deployment(102, "2026-08-30T08:00:00Z"),
      deployment(103, "2026-08-30T09:00:00Z"),
      deployment(101, "2026-08-30T07:00:00Z"),
    ],
    states: new Map([[101, "inactive"], [102, "inactive"], [103, "success"]]),
  });
  const result = await pruneGitHubPagesDeployments({
    fetchImpl: github.fetchImpl,
    token: "test-token",
    repository: "ChiZhang-805/DroneDream",
  });
  assert.deepEqual(result, {
    environment: "github-pages",
    keptDeploymentId: 103,
    eligibleDeleteCount: 2,
    normalizationCount: 0,
    deletedCount: 2,
    auditOnly: false,
  });
  assert.deepEqual(github.deletes, [102, 101]);
});

test("paginates the complete deployment inventory", async () => {
  const deployments = Array.from({ length: 101 }, (_, index) => (
    deployment(index + 1, new Date(Date.UTC(2026, 7, 1, 0, index)).toISOString())
  ));
  const states = new Map(deployments.map((item) => [item.id, "inactive"]));
  states.set(101, "success");
  const github = mockGitHub({ deployments, states });
  const result = await pruneGitHubPagesDeployments({
    fetchImpl: github.fetchImpl,
    token: "test-token",
    repository: "ChiZhang-805/DroneDream",
  });
  assert.equal(result.keptDeploymentId, 101);
  assert.equal(result.deletedCount, 100);
  assert.equal(github.calls.filter((call) => call.url.pathname.endsWith("/deployments")).length, 2);
});

test("fails before deletion when the newest deployment is not successful", async () => {
  const github = mockGitHub({
    deployments: [
      deployment(2, "2026-08-30T09:00:00Z"),
      deployment(1, "2026-08-30T08:00:00Z"),
    ],
    states: new Map([[1, "inactive"], [2, "in_progress"]]),
  });
  await assert.rejects(
    pruneGitHubPagesDeployments({
      fetchImpl: github.fetchImpl,
      token: "test-token",
      repository: "ChiZhang-805/DroneDream",
    }),
    /Newest deployment 2 is in_progress; refusing cleanup/u,
  );
  assert.deepEqual(github.deletes, []);
});

test("audits every older status before performing any mutation", async () => {
  const github = mockGitHub({
    deployments: [
      deployment(3, "2026-08-30T10:00:00Z"),
      deployment(2, "2026-08-30T09:00:00Z"),
      deployment(1, "2026-08-30T08:00:00Z"),
    ],
    states: new Map([[1, "in_progress"], [2, "inactive"], [3, "success"]]),
  });
  await assert.rejects(
    pruneGitHubPagesDeployments({
      fetchImpl: github.fetchImpl,
      token: "test-token",
      repository: "ChiZhang-805/DroneDream",
    }),
    /Older deployment 1 is in_progress; refusing cleanup/u,
  );
  assert.deepEqual(github.deletes, []);
  assert.deepEqual(github.normalized, []);
});

test("refuses any environment other than github-pages", async () => {
  await assert.rejects(
    pruneGitHubPagesDeployments({
      fetchImpl: async () => jsonResponse([]),
      token: "test-token",
      repository: "ChiZhang-805/DroneDream",
      environment: "production",
    }),
    /Only the canonical github-pages environment may be pruned/u,
  );
});

test("audit-only mode verifies the full inventory without deleting it", async () => {
  const github = mockGitHub({
    deployments: [
      deployment(2, "2026-08-30T09:00:00Z"),
      deployment(1, "2026-08-30T08:00:00Z"),
    ],
    states: new Map([[1, "inactive"], [2, "success"]]),
  });
  const result = await pruneGitHubPagesDeployments({
    fetchImpl: github.fetchImpl,
    token: "test-token",
    repository: "ChiZhang-805/DroneDream",
    auditOnly: true,
  });
  assert.equal(result.eligibleDeleteCount, 1);
  assert.equal(result.normalizationCount, 0);
  assert.equal(result.deletedCount, 0);
  assert.equal(result.auditOnly, true);
  assert.deepEqual(github.deletes, []);
});

test("normalizes superseded success and terminal failures before deleting them", async () => {
  const github = mockGitHub({
    deployments: [
      deployment(3, "2026-08-30T10:00:00Z"),
      deployment(2, "2026-08-30T09:00:00Z"),
      deployment(1, "2026-08-30T08:00:00Z"),
    ],
    states: new Map([[1, "success"], [2, "error"], [3, "success"]]),
  });
  const result = await pruneGitHubPagesDeployments({
    fetchImpl: github.fetchImpl,
    token: "test-token",
    repository: "ChiZhang-805/DroneDream",
  });
  assert.equal(result.normalizationCount, 2);
  assert.deepEqual(github.normalized, [2, 1]);
  assert.deepEqual(github.deletes, [2, 1]);
});
