import type { ExperimentStudyConfig } from "../../types/api";

export const EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v1";
const JOB_STUDY_PREFIX = "drone-dream:job-study:v1:";

export interface ExperimentDraftEnvelope<TForm, TSelections> {
  schema_version: 1;
  saved_at: string;
  active_step: number;
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

export function loadExperimentDraft<TForm, TSelections>(
  schema: ExperimentDraftSchema<TForm, TSelections>,
):
  | ExperimentDraftEnvelope<TForm, TSelections>
  | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(EXPERIMENT_DRAFT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.schema_version !== 1) {
      return null;
    }
    if (
      typeof parsed.saved_at !== "string" ||
      !Number.isFinite(Date.parse(parsed.saved_at)) ||
      typeof parsed.active_step !== "number" ||
      !Number.isSafeInteger(parsed.active_step) ||
      parsed.active_step < 0 ||
      parsed.active_step > schema.maxActiveStep
    ) {
      return null;
    }
    const form = schema.normalizeForm(parsed.form);
    const selections = schema.normalizeSelections(parsed.selections);
    if (!form || !selections) return null;
    return {
      schema_version: 1,
      saved_at: parsed.saved_at,
      active_step: parsed.active_step,
      form,
      selections,
    };
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
        schema_version: 1,
        saved_at: savedAt,
        ...envelope,
      }),
    );
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

export function loadStudyForJob(jobId: string): ExperimentStudyConfig | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(`${JOB_STUDY_PREFIX}${jobId}`);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || !isRecord(parsed.study)) return null;
    return parsed.study.schema_version === 1
      ? parsed.study as unknown as ExperimentStudyConfig
      : null;
  } catch {
    return null;
  }
}
