import type { ExperimentStudyConfig } from "../../types/api";

export const EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v3";
export const V2_EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v2";
export const LEGACY_EXPERIMENT_DRAFT_KEY = "drone-dream:experiment-draft:v1";
export const EXPERIMENT_WORKSPACE_DRAFT_PREFIX =
  "drone-dream:experiment-workspace-draft:v1:";
const JOB_STUDY_PREFIX = "drone-dream:job-study:v1:";
const LEGACY_MAX_ACTIVE_STEP = 6;

export type DraftFieldSource = "explicit" | "derived" | "proposed_default";

export interface DraftFieldProvenance {
  source: DraftFieldSource;
  message_id?: string;
}

export interface ExperimentConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface ExperimentConversationState {
  summary: string;
  field_provenance: Record<string, DraftFieldProvenance>;
  messages: ExperimentConversationMessage[];
}

export interface ExperimentDraftEnvelope<TForm, TSelections> {
  schema_version: 3;
  saved_at: string;
  active_step: number;
  completed_steps: number[];
  form: TForm;
  selections: TSelections;
  conversation: ExperimentConversationState | null;
}

export interface ExperimentDraftSchema<TForm, TSelections> {
  maxActiveStep: number;
  normalizeForm: (value: unknown) => TForm | null;
  normalizeSelections: (value: unknown) => TSelections | null;
}

function safeDraftStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function safePersistentStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function workspaceDraftKey(workspaceId?: string | null): string {
  if (!workspaceId) return EXPERIMENT_DRAFT_KEY;
  if (!/^[a-zA-Z0-9_-]{8,128}$/u.test(workspaceId)) {
    throw new Error("Invalid experiment workspace id.");
  }
  return `${EXPERIMENT_WORKSPACE_DRAFT_PREFIX}${workspaceId}`;
}

function discardPersistedDrafts(): void {
  const storage = safePersistentStorage();
  if (!storage) return;
  try {
    storage.removeItem(EXPERIMENT_DRAFT_KEY);
    storage.removeItem(V2_EXPERIMENT_DRAFT_KEY);
    storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
  } catch {
    // A denied persistent store must not block the current app session.
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

function normalizeConversationState(
  value: unknown,
): ExperimentConversationState | null {
  if (value === undefined || value === null) return null;
  if (!isRecord(value) || typeof value.summary !== "string") return null;
  if (
    value.summary.length > 4_000 ||
    !isRecord(value.field_provenance) ||
    !Array.isArray(value.messages) ||
    value.messages.length > 60
  ) {
    return null;
  }
  const fieldProvenance: Record<string, DraftFieldProvenance> = {};
  for (const [fieldId, raw] of Object.entries(value.field_provenance)) {
    if (
      !/^[a-z][a-z0-9_]{0,63}$/u.test(fieldId) ||
      !isRecord(raw) ||
      !["explicit", "derived", "proposed_default"].includes(String(raw.source))
    ) {
      return null;
    }
    if (
      raw.message_id !== undefined &&
      (typeof raw.message_id !== "string" || raw.message_id.length > 128)
    ) {
      return null;
    }
    fieldProvenance[fieldId] = {
      source: raw.source as DraftFieldSource,
      ...(typeof raw.message_id === "string"
        ? { message_id: raw.message_id }
        : {}),
    };
  }
  const messages: ExperimentConversationMessage[] = [];
  for (const raw of value.messages) {
    if (
      !isRecord(raw) ||
      typeof raw.id !== "string" ||
      raw.id.length < 1 ||
      raw.id.length > 128 ||
      (raw.role !== "user" && raw.role !== "assistant") ||
      typeof raw.content !== "string" ||
      raw.content.length < 1 ||
      raw.content.length > 12_000
    ) {
      return null;
    }
    messages.push({
      id: raw.id,
      role: raw.role,
      content: raw.content,
    });
  }
  return {
    summary: value.summary,
    field_provenance: fieldProvenance,
    messages,
  };
}

function parseDraftEnvelope<TForm, TSelections>(
  raw: string,
  schemaVersion: 1 | 2 | 3,
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
  const conversation = normalizeConversationState(parsed.conversation);
  if (parsed.conversation !== undefined && parsed.conversation !== null && !conversation) {
    return null;
  }
  return {
    saved_at: parsed.saved_at,
    active_step: parsed.active_step,
    completed_steps: completedSteps,
    form: redactDraftSecrets(normalizedForm),
    selections,
    conversation,
  };
}

export function loadExperimentDraft<TForm, TSelections>(
  schema: ExperimentDraftSchema<TForm, TSelections>,
  workspaceId?: string | null,
):
  | ExperimentDraftEnvelope<TForm, TSelections>
  | null {
  discardPersistedDrafts();
  const storage = safeDraftStorage();
  if (!storage) return null;
  try {
    const currentRaw = storage.getItem(workspaceDraftKey(workspaceId));
    if (currentRaw !== null) {
      const current = parseDraftEnvelope(currentRaw, 3, schema.maxActiveStep, schema);
      return current ? { schema_version: 3, ...current } : null;
    }
    if (workspaceId) return null;

    const v2Raw = storage.getItem(V2_EXPERIMENT_DRAFT_KEY);
    if (v2Raw !== null) {
      const v2 = parseDraftEnvelope(v2Raw, 2, schema.maxActiveStep, schema);
      if (!v2) return null;
      const migrated: ExperimentDraftEnvelope<TForm, TSelections> = {
        schema_version: 3,
        ...v2,
        conversation: null,
      };
      storage.setItem(EXPERIMENT_DRAFT_KEY, JSON.stringify(migrated));
      storage.removeItem(V2_EXPERIMENT_DRAFT_KEY);
      return migrated;
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
      schema_version: 3,
      ...legacy,
      active_step: 0,
      completed_steps: [],
      conversation: null,
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
  envelope: Omit<
    ExperimentDraftEnvelope<TForm, TSelections>,
    "schema_version" | "saved_at" | "conversation"
  > & {
    conversation?: ExperimentConversationState | null;
  },
  workspaceId?: string | null,
): string | null {
  discardPersistedDrafts();
  const storage = safeDraftStorage();
  if (!storage) return null;
  const savedAt = new Date().toISOString();
  try {
    const currentKey = workspaceDraftKey(workspaceId);
    let conversation = envelope.conversation;
    if (conversation === undefined) {
      const currentRaw = storage.getItem(currentKey);
      if (currentRaw) {
        const current = JSON.parse(currentRaw) as Record<string, unknown>;
        conversation = normalizeConversationState(current.conversation);
      }
    }
    const serialized = JSON.stringify({
      schema_version: 3,
      saved_at: savedAt,
      ...envelope,
      form: redactDraftSecrets(envelope.form),
      conversation: conversation ?? null,
      ...(workspaceId ? { workspace_id: workspaceId } : {}),
    });
    storage.setItem(currentKey, serialized);
    if (workspaceId) {
      // The workspace-scoped key is canonical. This alias preserves the most
      // recently active draft for legacy routes and older installs without
      // allowing one experiment to overwrite another.
      storage.setItem(EXPERIMENT_DRAFT_KEY, serialized);
    }
    if (!workspaceId) {
      try {
        storage.removeItem(V2_EXPERIMENT_DRAFT_KEY);
        storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
      } catch {
        // A valid v3 draft still prevents stale legacy drafts from loading.
      }
    }
    return savedAt;
  } catch {
    return null;
  }
}

export function clearExperimentDraft(workspaceId?: string | null): void {
  for (const storage of [safeDraftStorage(), safePersistentStorage()]) {
    if (!storage) continue;
    try {
      storage.removeItem(workspaceDraftKey(workspaceId));
      if (!workspaceId) {
        storage.removeItem(V2_EXPERIMENT_DRAFT_KEY);
        storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
      } else {
        const activeDraft = storage.getItem(EXPERIMENT_DRAFT_KEY);
        if (activeDraft) {
          const parsed = JSON.parse(activeDraft) as unknown;
          if (isRecord(parsed) && parsed.workspace_id === workspaceId) {
            storage.removeItem(EXPERIMENT_DRAFT_KEY);
          }
        }
      }
    } catch {
      // Optional draft storage must not block resetting or creating a job.
    }
  }
}

export function renameExperimentDraft(
  workspaceId: string,
  displayName: string,
): boolean {
  const storage = safeDraftStorage();
  if (!storage) return false;
  try {
    const key = workspaceDraftKey(workspaceId);
    const raw = storage.getItem(key);
    if (!raw) return false;
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed) || !isRecord(parsed.form)) return false;
    const renamed = JSON.stringify({
      ...parsed,
      saved_at: new Date().toISOString(),
      form: {
        ...parsed.form,
        display_name: displayName.trim().slice(0, 255),
        llm_api_key: "",
      },
    });
    storage.setItem(key, renamed);
    const activeDraft = storage.getItem(EXPERIMENT_DRAFT_KEY);
    if (activeDraft) {
      const activeParsed = JSON.parse(activeDraft) as unknown;
      if (
        isRecord(activeParsed)
        && activeParsed.workspace_id === workspaceId
      ) {
        storage.setItem(EXPERIMENT_DRAFT_KEY, renamed);
      }
    }
    return true;
  } catch {
    return false;
  }
}

export function clearAllExperimentDrafts(): void {
  for (const storage of [safeDraftStorage(), safePersistentStorage()]) {
    if (!storage) continue;
    try {
      const workspaceKeys: string[] = [];
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key?.startsWith(EXPERIMENT_WORKSPACE_DRAFT_PREFIX)) {
          workspaceKeys.push(key);
        }
      }
      workspaceKeys.forEach((key) => storage.removeItem(key));
      storage.removeItem(EXPERIMENT_DRAFT_KEY);
      storage.removeItem(V2_EXPERIMENT_DRAFT_KEY);
      storage.removeItem(LEGACY_EXPERIMENT_DRAFT_KEY);
    } catch {
      // Closing the app must remain possible when optional storage is denied.
    }
  }
}

export function hasExperimentDraft(workspaceId?: string | null): boolean {
  const storage = safeDraftStorage();
  if (!storage) return false;
  try {
    if (workspaceId) {
      return storage.getItem(workspaceDraftKey(workspaceId)) !== null;
    }
    if (
      storage.getItem(EXPERIMENT_DRAFT_KEY) !== null ||
      storage.getItem(V2_EXPERIMENT_DRAFT_KEY) !== null ||
      storage.getItem(LEGACY_EXPERIMENT_DRAFT_KEY) !== null
    ) {
      return true;
    }
    for (let index = 0; index < storage.length; index += 1) {
      if (storage.key(index)?.startsWith(EXPERIMENT_WORKSPACE_DRAFT_PREFIX)) {
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}

export function persistStudyForJob(
  jobId: string,
  study: ExperimentStudyConfig,
): void {
  const storage = safePersistentStorage();
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
