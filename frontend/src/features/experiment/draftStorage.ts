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

function storageAvailable(): boolean {
  return typeof window !== "undefined" && Boolean(window.localStorage);
}

export function loadExperimentDraft<TForm, TSelections>():
  | ExperimentDraftEnvelope<TForm, TSelections>
  | null {
  if (!storageAvailable()) return null;
  try {
    const raw = window.localStorage.getItem(EXPERIMENT_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ExperimentDraftEnvelope<TForm, TSelections>;
    if (parsed.schema_version !== 1 || !parsed.form || !parsed.selections) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveExperimentDraft<TForm, TSelections>(
  envelope: Omit<ExperimentDraftEnvelope<TForm, TSelections>, "schema_version" | "saved_at">,
): string | null {
  if (!storageAvailable()) return null;
  const savedAt = new Date().toISOString();
  try {
    window.localStorage.setItem(
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
  if (!storageAvailable()) return;
  window.localStorage.removeItem(EXPERIMENT_DRAFT_KEY);
}

export function persistStudyForJob(
  jobId: string,
  study: ExperimentStudyConfig,
): void {
  if (!storageAvailable()) return;
  try {
    window.localStorage.setItem(
      `${JOB_STUDY_PREFIX}${jobId}`,
      JSON.stringify({ saved_at: new Date().toISOString(), study }),
    );
  } catch {
    // Creating a job must never fail because optional browser storage is full
    // or unavailable (for example, Safari private browsing).
  }
}

export function loadStudyForJob(jobId: string): ExperimentStudyConfig | null {
  if (!storageAvailable()) return null;
  try {
    const raw = window.localStorage.getItem(`${JOB_STUDY_PREFIX}${jobId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { study?: ExperimentStudyConfig };
    return parsed.study?.schema_version === 1 ? parsed.study : null;
  } catch {
    return null;
  }
}

