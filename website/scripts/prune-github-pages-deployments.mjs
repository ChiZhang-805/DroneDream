#!/usr/bin/env node

import { pathToFileURL } from "node:url";

const API_ORIGIN = "https://api.github.com";
const API_VERSION = "2022-11-28";
const PAGE_SIZE = 100;
const NORMALIZABLE_SUPERSEDED_STATES = new Set(["error", "failure", "success"]);

function requireRepository(value) {
  const repository = String(value ?? "").trim();
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(repository)) {
    throw new Error("GITHUB_REPOSITORY must use owner/name syntax.");
  }
  return repository;
}

function requireEnvironment(value) {
  const environment = String(value ?? "github-pages").trim();
  if (environment !== "github-pages") {
    throw new Error("Only the canonical github-pages environment may be pruned.");
  }
  return environment;
}

function requireToken(value) {
  const token = String(value ?? "").trim();
  if (!token) throw new Error("GITHUB_TOKEN is required.");
  return token;
}

function booleanFlag(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized || normalized === "false") return false;
  if (normalized === "true") return true;
  throw new Error("DRONEDREAM_DEPLOYMENT_AUDIT_ONLY must be true or false.");
}

function deploymentOrder(left, right) {
  const timeDifference = Date.parse(right.created_at) - Date.parse(left.created_at);
  if (Number.isFinite(timeDifference) && timeDifference !== 0) return timeDifference;
  return Number(right.id) - Number(left.id);
}

async function githubRequest(fetchImpl, token, path, options = {}) {
  const response = await fetchImpl(new URL(path, API_ORIGIN), {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": API_VERSION,
      "User-Agent": "DroneDream-Pages-retention",
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.text()).slice(0, 500);
    throw new Error(`GitHub API ${options.method ?? "GET"} ${path} failed with ${response.status}: ${body}`);
  }
  return response;
}

async function listDeployments({ fetchImpl, token, repository, environment }) {
  const deployments = [];
  for (let page = 1; ; page += 1) {
    const query = new URLSearchParams({
      environment,
      per_page: String(PAGE_SIZE),
      page: String(page),
    });
    const response = await githubRequest(
      fetchImpl,
      token,
      `/repos/${repository}/deployments?${query}`,
    );
    const items = await response.json();
    if (!Array.isArray(items)) throw new Error("GitHub deployment inventory is malformed.");
    deployments.push(...items);
    if (items.length < PAGE_SIZE) return deployments;
  }
}

async function latestStatus({ fetchImpl, token, repository, deploymentId }) {
  const response = await githubRequest(
    fetchImpl,
    token,
    `/repos/${repository}/deployments/${deploymentId}/statuses?per_page=1`,
  );
  const statuses = await response.json();
  if (!Array.isArray(statuses) || statuses.length !== 1) {
    throw new Error(`Deployment ${deploymentId} has no unambiguous latest status.`);
  }
  return String(statuses[0]?.state ?? "");
}

export async function pruneGitHubPagesDeployments({
  fetchImpl = globalThis.fetch,
  token,
  repository,
  environment = "github-pages",
  auditOnly = false,
} = {}) {
  if (typeof fetchImpl !== "function") throw new Error("A Fetch implementation is required.");
  const safeRepository = requireRepository(repository);
  const safeEnvironment = requireEnvironment(environment);
  const safeToken = requireToken(token);
  const deployments = await listDeployments({
    fetchImpl,
    token: safeToken,
    repository: safeRepository,
    environment: safeEnvironment,
  });

  if (deployments.length === 0) {
    throw new Error("The github-pages environment has no deployment to retain.");
  }

  const ordered = [...deployments].sort(deploymentOrder);
  const keeper = ordered[0];
  const obsolete = ordered.slice(1);
  const keeperState = await latestStatus({
    fetchImpl,
    token: safeToken,
    repository: safeRepository,
    deploymentId: keeper.id,
  });
  if (keeperState !== "success") {
    throw new Error(`Newest deployment ${keeper.id} is ${keeperState || "unknown"}; refusing cleanup.`);
  }

  const audited = [];
  const needsInactiveStatus = [];
  for (const deployment of obsolete) {
    const state = await latestStatus({
      fetchImpl,
      token: safeToken,
      repository: safeRepository,
      deploymentId: deployment.id,
    });
    if (state !== "inactive" && !NORMALIZABLE_SUPERSEDED_STATES.has(state)) {
      throw new Error(`Older deployment ${deployment.id} is ${state || "unknown"}; refusing cleanup.`);
    }
    const record = { deployment, state };
    audited.push(record);
    if (state !== "inactive") needsInactiveStatus.push(record);
  }

  if (!auditOnly) {
    for (const { deployment } of needsInactiveStatus) {
      await githubRequest(
        fetchImpl,
        safeToken,
        `/repos/${safeRepository}/deployments/${deployment.id}/statuses`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            state: "inactive",
            description: "Superseded by the latest successful GitHub Pages deployment.",
          }),
        },
      );
    }
    for (const { deployment } of audited) {
      await githubRequest(
        fetchImpl,
        safeToken,
        `/repos/${safeRepository}/deployments/${deployment.id}`,
        { method: "DELETE" },
      );
    }
  }

  return {
    environment: safeEnvironment,
    keptDeploymentId: Number(keeper.id),
    eligibleDeleteCount: audited.length,
    normalizationCount: needsInactiveStatus.length,
    deletedCount: auditOnly ? 0 : audited.length,
    auditOnly: Boolean(auditOnly),
  };
}

async function main() {
  const result = await pruneGitHubPagesDeployments({
    token: process.env.GITHUB_TOKEN,
    repository: process.env.GITHUB_REPOSITORY,
    environment: process.env.DRONEDREAM_DEPLOYMENT_ENVIRONMENT,
    auditOnly: booleanFlag(process.env.DRONEDREAM_DEPLOYMENT_AUDIT_ONLY),
  });
  const action = result.auditOnly
    ? `audited ${result.eligibleDeleteCount} old deployment(s); ${result.normalizationCount} require inactive normalization`
    : `deleted ${result.deletedCount} inactive deployment(s)`;
  process.stdout.write(
    `Retained ${result.environment} deployment ${result.keptDeploymentId}; ${action}.\n`,
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
