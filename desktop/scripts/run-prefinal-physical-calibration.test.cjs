"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  parseArguments,
  prepareBaselinePayload,
  resolveEvidenceDirectory,
  selectProblems,
} = require("./run-prefinal-physical-calibration.cjs");

const repositoryRoot = path.resolve(__dirname, "../..");
const registry = JSON.parse(
  fs.readFileSync(
    path.join(
      repositoryRoot,
      "backend/evaluation_artifacts/prefinal-realistic-scenario-registry-v1.json",
    ),
    "utf8",
  ),
);

function validArguments(extra = []) {
  return [
    "--problem",
    "easy-hover-calm",
    "--output-directory",
    "artifacts/test-runs/unit-calibration",
    "--expected-source",
    "a".repeat(40),
    "--expected-pack-id",
    `sha256:${"b".repeat(64)}`,
    "--repository-evidence-head",
    "c".repeat(40),
    "--desktop-source",
    "d".repeat(40),
    "--desktop-sha256",
    "e".repeat(64),
    ...extra,
  ];
}

test("selects only intact pre-registered problems", () => {
  const selected = selectProblems(registry, ["easy-hover-calm", "hard-hover-wind-dropout"]);
  assert.deepEqual(
    selected.map((problem) => problem.problem_id),
    ["easy-hover-calm", "hard-hover-wind-dropout"],
  );
  assert.throws(() => selectProblems(registry, ["invented-problem"]), /unknown/);
  const tampered = structuredClone(registry);
  tampered.problems[0].difficulty = "hard";
  assert.throws(() => selectProblems(tampered, ["easy-hover-calm"]), /hash/);
});

test("baseline payload is bounded and cannot call a provider", () => {
  const [problem] = selectProblems(registry, ["representative-circle-crosswind"]);
  const payload = prepareBaselinePayload(problem, "abcdef0");
  assert.equal(payload.optimizer_strategy, "none");
  assert.equal(payload.max_iterations, 1);
  assert.equal(payload.max_total_trials, 4);
  assert.equal(payload.provider_turn_cap, 0);
  assert.equal(payload.continue_exploration_after_qualified, false);
  assert.equal(payload.exploration_budget, null);
  assert.equal(payload.llm, null);
  assert.equal(payload.openai, null);
  assert.equal(payload.scenario_suite.cases.length, 2);
  assert.deepEqual(
    payload.scenario_suite.cases.map((scenarioCase) => scenarioCase.seeds.length),
    [2, 2],
  );
});

test("argument and output guards reject ambiguity and path escape", () => {
  const options = parseArguments(validArguments());
  assert.deepEqual(options.problems, ["easy-hover-calm"]);
  assert.throws(
    () => parseArguments(validArguments(["--problem", "easy-hover-calm"])),
    /duplicated/,
  );
  assert.throws(() => resolveEvidenceDirectory("artifacts/test-runs"), /new child/);
  assert.throws(() => resolveEvidenceDirectory("../outside"), /new child/);
  assert.equal(
    resolveEvidenceDirectory("artifacts/test-runs/new-calibration"),
    path.join(repositoryRoot, "artifacts/test-runs/new-calibration"),
  );
});
