import type {
  ExperimentAssistantCurrentParameter,
  ExperimentAssistantPatch,
  ExperimentAssistantTurnResponse,
} from "../../types/api";
import {
  clearExperimentDraft,
  loadExperimentDraft,
  saveExperimentDraft,
  type DraftFieldProvenance,
  type DraftFieldSource,
  type ExperimentConversationMessage,
  type ExperimentConversationState,
  type ExperimentDraftEnvelope,
} from "./draftStorage";
import {
  EXPERIMENT_DRAFT_SCHEMA,
  EXPERIMENT_FORM_DEFAULTS,
  type ExperimentFormState,
} from "./formState";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
  type ParameterSelectionMap,
} from "./parameterCatalog";

export interface AssistantDraft {
  form: ExperimentFormState;
  selections: ParameterSelectionMap;
  activeStep: number;
  completedSteps: number[];
  conversation: ExperimentConversationState;
}

const EMPTY_CONVERSATION: ExperimentConversationState = {
  summary: "",
  field_provenance: {},
  messages: [],
};

function emptyDraft(): AssistantDraft {
  return {
    form: { ...EXPERIMENT_FORM_DEFAULTS },
    selections: createParameterSelections(
      BUILTIN_PARAMETER_CATALOG.parameters,
      EXPERIMENT_FORM_DEFAULTS.tuning_mode,
    ),
    activeStep: 0,
    completedSteps: [],
    conversation: {
      ...EMPTY_CONVERSATION,
      field_provenance: {},
      messages: [],
    },
  };
}

export function clearAssistantDraft(workspaceId?: string | null): AssistantDraft {
  clearExperimentDraft(workspaceId);
  return emptyDraft();
}

export function loadAssistantDraft(workspaceId?: string | null): AssistantDraft {
  const stored = loadExperimentDraft(EXPERIMENT_DRAFT_SCHEMA, workspaceId);
  if (!stored) return emptyDraft();
  return {
    form: stored.form,
    selections: stored.selections,
    activeStep: stored.active_step,
    completedSteps: stored.completed_steps,
    conversation: stored.conversation ?? {
      ...EMPTY_CONVERSATION,
      field_provenance: {},
      messages: [],
    },
  };
}

function sourceRank(source: DraftFieldSource): number {
  if (source === "explicit") return 3;
  if (source === "derived") return 2;
  return 1;
}

function shouldApplyPatch(
  current: DraftFieldProvenance | undefined,
  patch: ExperimentAssistantPatch,
): boolean {
  if (!current) return true;
  if (patch.provenance === "explicit") return true;
  return sourceRank(patch.provenance) >= sourceRank(current.source);
}

function applyFieldPatch(
  form: ExperimentFormState,
  patch: ExperimentAssistantPatch,
): boolean {
  if (
    !(patch.field_id in form) ||
    patch.field_id === "llm_api_key" ||
    patch.field_id === "llm_provider" ||
    patch.field_id === "llm_model" ||
    patch.field_id === "llm_base_url" ||
    patch.field_id === "reference_track_json" ||
    patch.field_id === "obstacles_json"
  ) {
    return false;
  }
  const key = patch.field_id as keyof ExperimentFormState;
  const current = form[key];
  if (typeof current === "boolean") {
    if (typeof patch.value !== "boolean") return false;
    (form as unknown as Record<string, unknown>)[key] = patch.value;
    return true;
  }
  if (typeof patch.value === "boolean") return false;
  (form as unknown as Record<string, unknown>)[key] = String(patch.value);
  return true;
}

function boundedMessages(
  messages: ExperimentConversationMessage[],
): ExperimentConversationMessage[] {
  return messages.slice(-60);
}

export function assistantCurrentValues(
  form: ExperimentFormState,
): Record<string, string | number | boolean> {
  const result: Record<string, string | number | boolean> = {};
  for (const [fieldId, value] of Object.entries(form)) {
    if (
      fieldId.startsWith("llm_") ||
      fieldId === "reference_track_json" ||
      fieldId === "obstacles_json"
    ) {
      continue;
    }
    result[fieldId] = value;
  }
  return result;
}

export function assistantCurrentParameters(
  selections: ParameterSelectionMap,
): ExperimentAssistantCurrentParameter[] {
  return Object.values(selections)
    .filter((selection) => selection.selected)
    .slice(0, 64)
    .map((selection) => ({
      name: selection.name,
      selected: true,
      baseline: selection.baseline,
      search_min: selection.search_min,
      search_max: selection.search_max,
      scale: selection.scale,
    }));
}

export function explicitAssistantFields(
  conversation: ExperimentConversationState,
): string[] {
  return Object.entries(conversation.field_provenance)
    .filter(([, provenance]) => provenance.source === "explicit")
    .map(([fieldId]) => fieldId)
    .sort();
}

export function recordManualDraftEdits(
  conversation: ExperimentConversationState | null,
  originalForm: ExperimentFormState,
  nextForm: ExperimentFormState,
  originalSelections: ParameterSelectionMap,
  nextSelections: ParameterSelectionMap,
): ExperimentConversationState | null {
  const fieldProvenance = {
    ...(conversation?.field_provenance ?? {}),
  };
  let changed = false;
  for (const [fieldId, value] of Object.entries(nextForm)) {
    if (
      fieldId.startsWith("llm_")
      || fieldId === "reference_track_json"
      || fieldId === "obstacles_json"
      || Object.is(originalForm[fieldId as keyof ExperimentFormState], value)
    ) {
      continue;
    }
    fieldProvenance[fieldId] = { source: "explicit" };
    changed = true;
  }
  const selectionNames = new Set([
    ...Object.keys(originalSelections),
    ...Object.keys(nextSelections),
  ]);
  for (const name of selectionNames) {
    if (
      JSON.stringify(originalSelections[name] ?? null)
      !== JSON.stringify(nextSelections[name] ?? null)
    ) {
      fieldProvenance.parameters = { source: "explicit" };
      changed = true;
      break;
    }
  }
  if (!conversation && !changed) return null;
  return {
    summary: conversation?.summary ?? "",
    field_provenance: fieldProvenance,
    messages: conversation?.messages ?? [],
  };
}

export function applyAssistantTurn(
  current: AssistantDraft,
  result: ExperimentAssistantTurnResponse,
  userMessage: ExperimentConversationMessage,
  workspaceId?: string | null,
): AssistantDraft {
  const form = { ...current.form };
  const selections = { ...current.selections };
  const fieldProvenance = {
    ...current.conversation.field_provenance,
  };

  for (const patch of result.accepted_patches) {
    if (!shouldApplyPatch(fieldProvenance[patch.field_id], patch)) continue;
    if (!applyFieldPatch(form, patch)) continue;
    fieldProvenance[patch.field_id] = {
      source: patch.provenance,
      ...(patch.source_message_id
        ? { message_id: patch.source_message_id }
        : {}),
    };
  }

  const currentParameterProvenance = fieldProvenance.parameters;
  let appliedParameterProvenance: DraftFieldProvenance | undefined;
  for (const patch of result.accepted_parameter_patches) {
    if (
      currentParameterProvenance
      && patch.provenance !== "explicit"
      && sourceRank(patch.provenance) < sourceRank(currentParameterProvenance.source)
    ) {
      continue;
    }
    const existing = selections[patch.name];
    if (!existing) continue;
    selections[patch.name] = {
      ...existing,
      selected: patch.selected,
      baseline: patch.baseline ?? existing.baseline,
      search_min: patch.search_min ?? existing.search_min,
      search_max: patch.search_max ?? existing.search_max,
      scale: patch.scale ?? existing.scale,
    };
    if (
      !appliedParameterProvenance
      || sourceRank(patch.provenance) > sourceRank(appliedParameterProvenance.source)
    ) {
      appliedParameterProvenance = {
        source: patch.provenance,
        ...(patch.source_message_id
          ? { message_id: patch.source_message_id }
          : {}),
      };
    }
  }
  if (appliedParameterProvenance) {
    fieldProvenance.parameters = appliedParameterProvenance;
  }

  const assistantContent = [
    result.experiment_summary,
    ...result.questions.map((question) => question.question),
  ].join("\n\n");
  const conversation: ExperimentConversationState = {
    summary: result.experiment_summary,
    field_provenance: fieldProvenance,
    messages: boundedMessages([
      ...current.conversation.messages,
      userMessage,
      {
        id: `${userMessage.id}:assistant`,
        role: "assistant",
        content: assistantContent,
      },
    ]),
  };

  const next: AssistantDraft = {
    ...current,
    form,
    selections,
    conversation,
  };
  persistAssistantDraft(next, workspaceId);
  return next;
}

export function persistAssistantDraft(
  draft: AssistantDraft,
  workspaceId?: string | null,
): string | null {
  return saveExperimentDraft({
    active_step: draft.activeStep,
    completed_steps: draft.completedSteps,
    form: draft.form,
    selections: draft.selections,
    conversation: draft.conversation,
  }, workspaceId);
}

export function toDraftEnvelope(
  draft: AssistantDraft,
): Omit<
  ExperimentDraftEnvelope<ExperimentFormState, ParameterSelectionMap>,
  "schema_version" | "saved_at"
> {
  return {
    active_step: draft.activeStep,
    completed_steps: draft.completedSteps,
    form: draft.form,
    selections: draft.selections,
    conversation: draft.conversation,
  };
}
