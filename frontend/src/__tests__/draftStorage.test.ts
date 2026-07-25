import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EXPERIMENT_DRAFT_KEY,
  LEGACY_EXPERIMENT_DRAFT_KEY,
  V2_EXPERIMENT_DRAFT_KEY,
  loadExperimentDraft,
  saveExperimentDraft,
} from "../features/experiment/draftStorage";
import type { ExperimentDraftSchema } from "../features/experiment/draftStorage";

interface TestForm {
  name: string;
  llm_api_key: string;
}

type TestSelections = Record<string, number>;

const schema: ExperimentDraftSchema<TestForm, TestSelections> = {
  maxActiveStep: 4,
  normalizeForm(value) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
    const candidate = value as Record<string, unknown>;
    if (typeof candidate.name !== "string" || typeof candidate.llm_api_key !== "string") {
      return null;
    }
    return { name: candidate.name, llm_api_key: candidate.llm_api_key };
  },
  normalizeSelections(value) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
    return { ...(value as TestSelections) };
  },
};

function envelope(schemaVersion: 1 | 2 | 3, activeStep: number, name: string, secret = "") {
  return JSON.stringify({
    schema_version: schemaVersion,
    saved_at: "2026-07-15T00:00:00.000Z",
    active_step: activeStep,
    form: { name, llm_api_key: secret },
    selections: { MPC_XY_P: 1 },
  });
}

describe("experiment draft storage migration", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prefers a valid v3 draft and does not remigrate an existing v1 draft", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      envelope(1, 6, "legacy"),
    );
    window.sessionStorage.setItem(
      EXPERIMENT_DRAFT_KEY,
      envelope(3, 4, "current"),
    );

    const loaded = loadExperimentDraft(schema);

    expect(loaded).toMatchObject({
      schema_version: 3,
      active_step: 4,
      completed_steps: [0, 1, 2, 3],
      form: { name: "current", llm_api_key: "" },
    });
    expect(window.sessionStorage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY)).not.toBeNull();
  });

  it("migrates a legacy seven-step draft to v3 step zero without restoring its secret", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      envelope(1, 6, "legacy-review", "sk-do-not-restore"),
    );

    const loaded = loadExperimentDraft(schema);

    expect(loaded).toMatchObject({
      schema_version: 3,
      active_step: 0,
      completed_steps: [],
      form: { name: "legacy-review", llm_api_key: "" },
      selections: { MPC_XY_P: 1 },
    });
    const migratedRaw = window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY);
    expect(migratedRaw).not.toContain("sk-do-not-restore");
    expect(JSON.parse(migratedRaw ?? "null")).toMatchObject({
      schema_version: 3,
      active_step: 0,
      form: { name: "legacy-review", llm_api_key: "" },
    });
    expect(window.sessionStorage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY)).toBeNull();
    expect(loadExperimentDraft(schema)).toEqual(loaded);
  });

  it("keeps the v1 draft when the migrated v3 draft cannot be written", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      envelope(1, 5, "legacy-budget", "sk-still-not-restored"),
    );
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function setItem(
      this: Storage,
      key,
      value,
    ) {
      if (key === EXPERIMENT_DRAFT_KEY) throw new DOMException("Quota exceeded", "QuotaExceededError");
      return originalSetItem.call(this, key, value);
    });
    const loaded = loadExperimentDraft(schema);

    expect(loaded).toMatchObject({
      schema_version: 3,
      active_step: 0,
      form: { name: "legacy-budget", llm_api_key: "" },
    });
    expect(window.sessionStorage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY)).not.toBeNull();
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).toBeNull();
  });

  it("does not fall back to v1 when a v2 key exists but is invalid", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      envelope(1, 4, "legacy-track"),
    );
    window.sessionStorage.setItem(
      V2_EXPERIMENT_DRAFT_KEY,
      envelope(2, 5, "invalid-current"),
    );

    expect(loadExperimentDraft(schema)).toBeNull();
    expect(window.sessionStorage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY)).not.toBeNull();
  });

  it("saves only a redacted v3 draft and removes stale prior drafts afterward", () => {
    window.sessionStorage.setItem(
      LEGACY_EXPERIMENT_DRAFT_KEY,
      envelope(1, 2, "legacy-parameters"),
    );

    expect(saveExperimentDraft({
      active_step: 3,
      completed_steps: [0, 2],
      form: { name: "new-budget", llm_api_key: "sk-never-write" },
      selections: { MPC_XY_P: 2 },
    })).not.toBeNull();

    const savedRaw = window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY);
    expect(savedRaw).not.toContain("sk-never-write");
    expect(JSON.parse(savedRaw ?? "null")).toMatchObject({
      schema_version: 3,
      active_step: 3,
      completed_steps: [0, 2],
      form: { name: "new-budget", llm_api_key: "" },
    });
    expect(window.sessionStorage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY)).toBeNull();
  });

  it("restores a redacted persistent draft in a new app session", () => {
    window.localStorage.setItem(
      EXPERIMENT_DRAFT_KEY,
      envelope(3, 3, "saved-from-closed-app", "sk-never-restore"),
    );

    expect(loadExperimentDraft(schema)).toMatchObject({
      schema_version: 3,
      active_step: 3,
      form: { name: "saved-from-closed-app", llm_api_key: "" },
    });
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toBeNull();
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toBeNull();
  });
});
