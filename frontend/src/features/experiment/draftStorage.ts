import type { ExperimentStudyConfig } from "../../types/api";

export const EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v2";
export const LEGACY_EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v1";
const JOB_STUDY_PREFIX = "drone-dream:job-study:v1:";
const LEGACY_MAX_ACTIVE_STEP = 6;

export interface ExperimentDraftEnvelope<TForm, TSelections> {
  schema_version: 2;
  saved_at: string;
  active_step: number;
  completed_steps: number[];
  form: TForm;
  selections: TSelections;
}

export interface ExperimentDraftSchema<TForm, TSelections> {
  maxActiveStep: number;
  normalizeForm: (value: unknown) => TForm | null;
  normalizeSelections: (value: unknown) => TSelections | null;
}

function safeStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function redactDraftSecrets<T>(value: T): T {
  if (!isRecord(value) || !("llm_api_key" in value)) return value;
  return { ...value, llm_api_key: "" } as T;
}

function normalizeCompletedSteps(
  value: unknown,
  activeStep: number,
  maxActiveStep: number,
): number[] | null {
  // Early v2 drafts did not persist this field. Reconstructing the preceding
  // steps preserves their original forward-only wizard semantics.
  if (value === undefined) {
    return Array.from({ length: activeStep }, (_, index) => index);
  }
  if (!Array.isArray(value)) return null;
  const completed = new Set<number>();
  for (const step of value) {
    if (
      typeof step !== "number"
      || !Number.isSafeInteger(step)
      || step < 0
      || step > maxActiveStep
    ) {
      return null;
    }
    completed.add(step);
  }
  return [...completed].sort((left, right) => left - right);
}

function parseDraftEnvelope<TForm, TSelections>(
  raw: string,
  schemaVersion: 1 | 2,
  maxActiveStep: number,
  schema: ExperimentDraftSchema<TForm, TSelections>,
): Omit<ExperimentDraftEnvelope<TForm, TSelections>, "schema_version"> | null {
  const parsed: unknown = JSON.parse(raw);
  if (!isRecord(parsed) || parsed.schema_version !== schemaVersion) return null;
  if (
    typeof parsed.saved_at !== "string" ||
    !Number.isFinite(Date.parse(parsed.saved_at)) ||
    typeof parsed.active_step !== "number" ||
    !Number.isSafeInteger(parsed.active_step) ||
    parsed.active_step < 0 ||
    parsed.active_step > maxActiveStep
  ) {
    return null;
  }
  const normalizedForm = schema.normalizeForm(parsed.form);
  const selections = schema.normalizeSelections(parsed.selections);
  const completedSteps = normalizeCompletedSteps(
    parsed.completed_steps,
    parsed.active_step,
    maxActiveStep,
  );
  if (!normalizedForm || !selections || !completedSteps) return null;
  return {
    saved_at: parsed.saved_at,
    active_step: parsed.active_step,
    completed_steps: completedSteps,
    form: redactDraftSecrets(normalizedForm),
    selections,
  };
}

export function loadExperimentDraft<TForm, TSelections>(
  schema: ExperimentDraftSchema<TForm, TSelections>,
):
  | ExperimentDraftEnvelope<TForm, TSelections>
  | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    const currentRaw = storage.getItem(EXPERIMENT_DRAFT_KEY);
    if (currentRaw !== null) {
      const current = parseDraftEnvelope(currentRaw, 2, schema.maxActiveStep, schema);
      return current ? { schema_version: 2, ...current } : null;
    }

    const legacyRaw = storage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY);
    if (legacyRaw === null) return null;
    const legacy = parseDraftEnvelope(
      legacyRaw,
      1,
      LEGACY_MAX_ACTIVE_STEP,
      schema,
    );
    if (!legacy) return null;
    const migrated: ExperimentDraftEnvelope<TForm, TSelections> = {
      schema_version: 2,
      ...legacy,
      active_step: 0,
      completed_steps: [],
    };
    try {
      storage.setItem(EXPERIMENT_DRAFT_KEY, JSON.stringify(migrated));
    } catch {
      // Preserve the readable legacy draft if v2 storage is unavailable.
      return migrated;
    }
    try {
      storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
    } catch {
      // The valid v2 draft takes precedence on the next load.
    }
    return migrated;
  } catch {
    return null;
  }
}

export function saveExperimentDraft<TForm, TSelections>(
  envelope: Omit<ExperimentDraftEnvelope<TForm, TSelections>, "schema_version" | "saved_at">,
): string | null {
  const storage = safeStorage();
  if (!storage) return null;
  const savedAt = new Date().toISOString();
  try {
    storage.setItem(
      EXPERIMENT_DRAFT_KEY,
      JSON.stringify({
        schema_version: 2,
        saved_at: savedAt,
        ...envelope,
        form: redactDraftSecrets(envelope.form),
      }),
    );
    try {
      storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
    } catch {
      // A valid v2 draft still prevents the stale legacy draft from loading.
    }
    return savedAt;
  } catch {
    return null;
  }
}

export function clearExperimentDraft(): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.removeItem(EXPERIMENT_DRAFT_KEY);
  } catch {
    // Optional draft storage must not block resetting or creating a job.
  }
  try {
    storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
  } catch {
    // Optional draft storage must not block resetting or creating a job.
  }
}

export function persistStudyForJob(
  jobId: string,
  study: ExperimentStudyConfig,
): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.setItem(
      `${JOB_STUDY_PREFIX}${jobId}`,
      JSON.stringify({ saved_at: new Date().toISOString(), study }),
    );
  } catch {
    // Creating a job must never fail because optional browser storage is full
    // or unavailable (for example, Safari private browsing).
  }
}
