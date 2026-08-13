import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type {
  ExperimentAssistantDocumentContext,
  ExperimentAssistantFieldValue,
  ExperimentAssistantTurnResponse,
} from "../../types/api";
import { getAuthAccessToken } from "../auth/authTokenStore";
import {
  FetchDeadlineError,
  FetchResponseSizeError,
  fetchWithDeadline,
} from "../../api/fetchWithDeadline";
import {
  CloudModelAccessError,
  type ManagedModelCatalogEntry,
} from "../settings/cloudModelAccess";

export type AssistantRunState = "queued" | "processing" | "retry_wait" | "completed" | "failed";
export type AssistantRunStage =
  | "queued"
  | "analyzing"
  | "planning"
  | "calling_tools"
  | "validating"
  | "retry_wait"
  | "completed"
  | "failed_recoverable"
  | "failed";

export interface AssistantWorkflowStep {
  step: string;
  label: string;
  status: "completed" | "needs_input";
}

export interface AssistantGeneratedFile {
  file_id: string;
  display_name: string;
  content_type: string;
  byte_size: number;
  content_sha256: string;
  version: number;
}

export interface AssistantOrchestratedRun {
  run_id: string;
  conversation_id: string;
  tenant_id: string;
  organization_id: string | null;
  owner_user_id?: string;
  edition: BrandEditionId;
  workspace_id: string;
  sequence: number;
  provider: string;
  model: string;
  state: AssistantRunState;
  stage: AssistantRunStage;
  intent: string | null;
  workflow_json: AssistantWorkflowStep[];
  result_json: {
    response: ExperimentAssistantTurnResponse;
    assistant_message: string;
    questions: string[];
    artifact_kind:
      | "universal_vehicle_model"
      | "universal_simulation_experiment"
      | "universal_cross_edition_workflow"
      | "simulation_experiment"
      | "lab_simulation_experiment"
      | "lab_hardware_validation"
      | "lab_calibration_workflow"
      | "lab_sim_to_real_workflow"
      | "lab_real_to_sim_workflow"
      | "field_task_plan";
    artifact_id: string;
    artifact_version: number;
    product_link: string;
    conversation_id: string;
    run_id: string;
    sequence: number;
    tenant_id: string;
    organization_id: string | null;
    workspace_id: string;
    edition: BrandEditionId;
    generated_files: AssistantGeneratedFile[];
  } | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  timeout_at: string | null;
  updated_at: string;
}

export interface OrchestratedAssistantTurnInput {
  edition: BrandEditionId;
  workspaceId: string;
  organizationId?: string | null;
  idempotencyKey: string;
  message: string;
  locale: "en" | "zh-CN";
  selectedModel: Pick<ManagedModelCatalogEntry, "provider" | "model">;
  currentValues: Record<string, ExperimentAssistantFieldValue>;
  documentContext: ExperimentAssistantDocumentContext | null;
  onStage?: (stage: AssistantRunStage) => void;
}

export interface OrchestratedAssistantTurnResult {
  run: AssistantOrchestratedRun;
  response: ExperimentAssistantTurnResponse;
}

export interface AssistantWorkspaceMessage {
  message_id: string;
  run_id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AssistantWorkspaceArtifact {
  artifact_id: string;
  run_id: string;
  edition: BrandEditionId;
  workspace_id: string;
  artifact_kind: typeof ARTIFACT_KINDS[number];
  title: string;
  payload_json: Record<string, unknown>;
  version: number;
  status: "draft";
  created_at: string;
  updated_at: string;
}

export interface AssistantWorkspaceSnapshot {
  conversation: {
    conversation_id: string;
    tenant_id: string;
    organization_id: string | null;
    edition: BrandEditionId;
    workspace_id: string;
    title: string;
    summary: string;
    status: "active" | "archived";
    latest_completed_sequence: number;
    created_at: string;
    updated_at: string;
  };
  messages: AssistantWorkspaceMessage[];
  artifacts: AssistantWorkspaceArtifact[];
  runs: AssistantOrchestratedRun[];
  steps: Array<{
    step_id: string;
    run_id: string;
    step_key: string;
    step_order: number;
    step_type: string;
    state: string;
    attempt: number;
    label: string;
    tool_name: string | null;
    output_json: Record<string, unknown> | null;
    error_code: string | null;
    updated_at: string;
  }>;
  files: Array<{
    file_id: string;
    run_id: string;
    direction: "input" | "generated";
    display_name: string;
    content_type: string;
    byte_size: number;
    content_sha256: string;
    version: number;
    status: "active" | "archived";
    created_at: string;
  }>;
}

export interface AssistantWorkspaceIndexEntry {
  conversation_id: string;
  tenant_id: string;
  organization_id: string | null;
  edition: BrandEditionId;
  workspace_id: string;
  title: string;
  summary: string;
  status: "active" | "archived";
  latest_completed_sequence: number;
  created_at: string;
  updated_at: string;
  latest_artifact: {
    artifact_id: string;
    artifact_kind: typeof ARTIFACT_KINDS[number];
    title: string;
    version: number;
    status: "draft" | "archived";
    created_at: string;
    updated_at: string;
  } | null;
}

const ASSISTANT_TIMEOUT_MS = 125_000;
const ASSISTANT_RESPONSE_MAX_BYTES = 2 * 1024 * 1024;
const MAX_POLL_ATTEMPTS = 60;

function deriveAssistantUrl(): string {
  const explicit = (
    import.meta.env.VITE_ASSISTANT_ORCHESTRATOR_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  if (explicit) return explicit;
  const supabase = (
    import.meta.env.VITE_SUPABASE_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  return supabase ? `${supabase}/functions/v1/assistant-orchestrator` : "";
}

export const assistantOrchestratorUrl = deriveAssistantUrl();

function authHeaders(idempotencyKey?: string): Record<string, string> {
  const accessToken = getAuthAccessToken();
  if (!accessToken) {
    throw new CloudModelAccessError(
      "AUTHENTICATION_REQUIRED",
      "Sign in to use DroneDream's managed assistant.",
      401,
    );
  }
  return {
    Authorization: `Bearer ${accessToken}`,
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const ARTIFACT_KINDS = [
  "universal_vehicle_model",
  "universal_simulation_experiment",
  "universal_cross_edition_workflow",
  "simulation_experiment",
  "lab_simulation_experiment",
  "lab_hardware_validation",
  "lab_calibration_workflow",
  "lab_sim_to_real_workflow",
  "lab_real_to_sim_workflow",
  "field_task_plan",
] as const;

function validCompletedResult(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return isRecord(value.response)
    && value.response.schema_version === "1.0"
    && Array.isArray(value.response.accepted_patches)
    && Array.isArray(value.response.rejected_patches)
    && Array.isArray(value.response.accepted_parameter_patches)
    && Array.isArray(value.response.rejected_parameter_patches)
    && Array.isArray(value.response.missing_field_ids)
    && Array.isArray(value.response.review_field_ids)
    && Array.isArray(value.response.questions)
    && typeof value.assistant_message === "string"
    && Array.isArray(value.questions)
    && ARTIFACT_KINDS.includes(value.artifact_kind as typeof ARTIFACT_KINDS[number])
    && typeof value.artifact_id === "string"
    && typeof value.artifact_version === "number"
    && typeof value.product_link === "string"
    && Array.isArray(value.generated_files)
    && value.generated_files.length >= 1
    && value.generated_files.every((file) =>
      isRecord(file)
      && typeof file.file_id === "string"
      && typeof file.display_name === "string"
      && typeof file.content_type === "string"
      && typeof file.byte_size === "number"
      && Number.isSafeInteger(file.byte_size)
      && file.byte_size >= 0
      && typeof file.content_sha256 === "string"
      && /^[0-9a-f]{64}$/u.test(file.content_sha256)
      && typeof file.version === "number"
      && Number.isSafeInteger(file.version)
      && file.version >= 1
    )
    && typeof value.conversation_id === "string"
    && typeof value.run_id === "string"
    && typeof value.sequence === "number";
}

function artifactMatchesEdition(
  edition: BrandEditionId,
  result: unknown,
): boolean {
  if (!isRecord(result) || typeof result.artifact_kind !== "string") return false;
  if (edition === "universal") {
    return result.artifact_kind === "universal_vehicle_model"
      || result.artifact_kind === "universal_simulation_experiment"
      || result.artifact_kind === "universal_cross_edition_workflow";
  }
  if (edition === "sim") return result.artifact_kind === "simulation_experiment";
  if (edition === "field") return result.artifact_kind === "field_task_plan";
  return [
    "lab_simulation_experiment",
    "lab_hardware_validation",
    "lab_calibration_workflow",
    "lab_sim_to_real_workflow",
    "lab_real_to_sim_workflow",
  ].includes(result.artifact_kind);
}

function validWorkflow(value: unknown): value is AssistantWorkflowStep[] {
  return Array.isArray(value)
    && value.length <= 8
    && value.every((item) =>
      isRecord(item)
      && Object.keys(item).sort().join("\0") === "label\0status\0step"
      && typeof item.step === "string"
      && item.step.length > 0
      && item.step.length <= 64
      && typeof item.label === "string"
      && item.label.length > 0
      && item.label.length <= 255
      && (item.status === "completed" || item.status === "needs_input")
    );
}

function validProductLink(
  value: unknown,
  edition: BrandEditionId,
  workspaceId: string,
  artifactId: string,
): boolean {
  if (typeof value !== "string" || value.length > 512) return false;
  try {
    const link = new URL(value, "https://console.getdronedream.invalid");
    return link.origin === "https://console.getdronedream.invalid"
      && link.pathname === "/console/assistant"
      && link.searchParams.get("edition") === edition
      && link.searchParams.get("experiment") === workspaceId
      && link.searchParams.get("artifact") === artifactId
      && [...link.searchParams.keys()].sort().join("\0") === "artifact\0edition\0experiment";
  } catch {
    return false;
  }
}

function stateMatchesStage(
  state: unknown,
  stage: unknown,
): boolean {
  if (state === "queued") return stage === "queued";
  if (state === "completed") return stage === "completed";
  if (state === "retry_wait") return stage === "retry_wait";
  if (state === "failed") return stage === "failed" || stage === "failed_recoverable";
  return state === "processing"
    && ["analyzing", "planning", "calling_tools", "validating"].includes(String(stage));
}

function parseRun(value: unknown): AssistantOrchestratedRun {
  if (!isRecord(value)) {
    throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant run is invalid.", 502);
  }
  if (
    typeof value.run_id !== "string"
    || typeof value.conversation_id !== "string"
    || typeof value.tenant_id !== "string"
    || (value.organization_id !== null && typeof value.organization_id !== "string")
    || (value.edition !== "universal" && value.edition !== "sim"
      && value.edition !== "lab" && value.edition !== "field")
    || typeof value.workspace_id !== "string"
    || !/^[a-zA-Z0-9_-]{8,128}$/u.test(value.workspace_id)
    || typeof value.sequence !== "number"
    || !Number.isSafeInteger(value.sequence)
    || value.sequence < 1
    || typeof value.provider !== "string"
    || value.provider.length < 1
    || typeof value.model !== "string"
    || value.model.length < 1
    || !["queued", "processing", "retry_wait", "completed", "failed"].includes(String(value.state))
    || !["queued", "analyzing", "planning", "calling_tools", "validating", "retry_wait", "completed", "failed_recoverable", "failed"].includes(String(value.stage))
    || !stateMatchesStage(value.state, value.stage)
    || (value.intent !== null && typeof value.intent !== "string")
    || !validWorkflow(value.workflow_json)
    || (value.error_code !== null && typeof value.error_code !== "string")
    || (value.error_message !== null && typeof value.error_message !== "string")
    || typeof value.attempt_count !== "number"
    || typeof value.max_attempts !== "number"
    || (value.next_attempt_at !== null && typeof value.next_attempt_at !== "string")
    || (value.timeout_at !== null && typeof value.timeout_at !== "string")
    || typeof value.updated_at !== "string"
  ) {
    throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant run is invalid.", 502);
  }
  if (
    value.state === "completed"
    && (
      !validCompletedResult(value.result_json)
      || !artifactMatchesEdition(value.edition, value.result_json)
      || !isRecord(value.result_json)
      || value.result_json.run_id !== value.run_id
      || value.result_json.conversation_id !== value.conversation_id
      || value.result_json.sequence !== value.sequence
      || value.result_json.tenant_id !== value.tenant_id
      || value.result_json.organization_id !== value.organization_id
      || value.result_json.workspace_id !== value.workspace_id
      || value.result_json.edition !== value.edition
      || typeof value.result_json.artifact_id !== "string"
      || !validProductLink(
        value.result_json.product_link,
        value.edition,
        value.workspace_id,
        value.result_json.artifact_id,
      )
    )
  ) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The completed assistant run has an invalid sealed result.",
      502,
    );
  }
  if (value.state !== "completed" && value.result_json !== null) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "A non-completed assistant run exposed an unsealed result.",
      502,
    );
  }
  return value as unknown as AssistantOrchestratedRun;
}

function completedRunResponse(
  run: AssistantOrchestratedRun,
): ExperimentAssistantTurnResponse | null {
  if (run.state !== "completed" || !run.result_json?.response) return null;
  return {
    ...run.result_json.response,
    assistant_message: run.result_json.assistant_message,
    orchestration: {
      run_id: run.run_id,
      conversation_id: run.conversation_id,
      tenant_id: run.tenant_id,
      organization_id: run.organization_id,
      workspace_id: run.workspace_id,
      edition: run.edition,
      artifact_id: run.result_json.artifact_id,
      artifact_version: run.result_json.artifact_version,
      product_link: run.result_json.product_link,
      artifact_kind: run.result_json.artifact_kind,
      sequence: run.sequence,
      intent: run.intent,
      workflow: run.workflow_json,
      generated_files: run.result_json.generated_files,
    },
  };
}

function parseWorkspaceSnapshot(
  value: unknown,
  expectedEdition: BrandEditionId,
  expectedWorkspaceId: string,
): AssistantWorkspaceSnapshot | null {
  if (value === null) return null;
  if (!isRecord(value) || !isRecord(value.conversation)) {
    throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace snapshot is invalid.", 502);
  }
  const conversation = value.conversation;
  if (
    conversation.edition !== expectedEdition
    || conversation.workspace_id !== expectedWorkspaceId
    || typeof conversation.conversation_id !== "string"
    || typeof conversation.tenant_id !== "string"
    || (conversation.organization_id !== null && typeof conversation.organization_id !== "string")
    || typeof conversation.title !== "string"
    || typeof conversation.summary !== "string"
    || (conversation.status !== "active" && conversation.status !== "archived")
    || typeof conversation.latest_completed_sequence !== "number"
    || typeof conversation.created_at !== "string"
    || typeof conversation.updated_at !== "string"
    || !Array.isArray(value.messages)
    || !Array.isArray(value.artifacts)
    || !Array.isArray(value.runs)
    || !Array.isArray(value.steps)
    || !Array.isArray(value.files)
  ) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The assistant workspace snapshot crossed an edition or workspace boundary.",
      502,
    );
  }
  const messages = value.messages.map((item) => {
    if (
      !isRecord(item)
      || typeof item.message_id !== "string"
      || typeof item.run_id !== "string"
      || typeof item.sequence !== "number"
      || (item.role !== "user" && item.role !== "assistant")
      || typeof item.content !== "string"
      || typeof item.created_at !== "string"
    ) {
      throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace contains an invalid message.", 502);
    }
    return item as unknown as AssistantWorkspaceMessage;
  });
  const artifacts = value.artifacts.map((item) => {
    if (
      !isRecord(item)
      || typeof item.artifact_id !== "string"
      || typeof item.run_id !== "string"
      || item.edition !== expectedEdition
      || item.workspace_id !== expectedWorkspaceId
      || !ARTIFACT_KINDS.includes(item.artifact_kind as typeof ARTIFACT_KINDS[number])
      || !artifactMatchesEdition(expectedEdition, item)
      || typeof item.title !== "string"
      || !isRecord(item.payload_json)
      || typeof item.version !== "number"
      || item.status !== "draft"
      || typeof item.created_at !== "string"
      || typeof item.updated_at !== "string"
    ) {
      throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace contains an invalid artifact.", 502);
    }
    return item as unknown as AssistantWorkspaceArtifact;
  });
  const runs = value.runs.map(parseRun);
  if (runs.some((run) =>
    run.conversation_id !== conversation.conversation_id
    || run.tenant_id !== conversation.tenant_id
    || run.organization_id !== conversation.organization_id
    || run.edition !== expectedEdition
    || run.workspace_id !== expectedWorkspaceId
  )) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The assistant workspace contains a run from another boundary.",
      502,
    );
  }
  const steps = value.steps.map((item) => {
    if (!isRecord(item) || typeof item.step_id !== "string" || typeof item.run_id !== "string"
      || typeof item.step_key !== "string" || typeof item.step_order !== "number"
      || typeof item.step_type !== "string" || typeof item.state !== "string"
      || typeof item.attempt !== "number" || typeof item.label !== "string"
      || (item.tool_name !== null && typeof item.tool_name !== "string")
      || (item.output_json !== null && !isRecord(item.output_json))
      || (item.error_code !== null && typeof item.error_code !== "string")
      || typeof item.updated_at !== "string") {
      throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace contains an invalid step.", 502);
    }
    return item as AssistantWorkspaceSnapshot["steps"][number];
  });
  const files = value.files.map((item) => {
    if (!isRecord(item) || typeof item.file_id !== "string" || typeof item.run_id !== "string"
      || (item.direction !== "input" && item.direction !== "generated")
      || typeof item.display_name !== "string" || typeof item.content_type !== "string"
      || typeof item.byte_size !== "number" || typeof item.content_sha256 !== "string"
      || typeof item.version !== "number" || (item.status !== "active" && item.status !== "archived")
      || typeof item.created_at !== "string") {
      throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace contains an invalid file.", 502);
    }
    return item as AssistantWorkspaceSnapshot["files"][number];
  });
  const knownRunIds = new Set(runs.map((run) => run.run_id));
  if (steps.some((step) => !knownRunIds.has(step.run_id)) || files.some((file) => !knownRunIds.has(file.run_id))) {
    throw new CloudModelAccessError("INVALID_RESPONSE", "The assistant workspace crossed a run boundary.", 502);
  }
  return {
    conversation: conversation as unknown as AssistantWorkspaceSnapshot["conversation"],
    messages,
    artifacts,
    runs,
    steps,
    files,
  };
}

function parseWorkspaceIndex(
  value: unknown,
  expectedEdition: BrandEditionId,
  expectedTenantId: string,
  expectedOrganizationId: string | null,
): AssistantWorkspaceIndexEntry[] {
  if (!isRecord(value) || !Array.isArray(value.conversations) || !Array.isArray(value.artifacts)) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The assistant workspace index is invalid.",
      502,
    );
  }
  const conversations = value.conversations.map((item) => {
    if (
      !isRecord(item)
      || typeof item.conversation_id !== "string"
      || item.tenant_id !== expectedTenantId
      || item.organization_id !== expectedOrganizationId
      || item.edition !== expectedEdition
      || typeof item.workspace_id !== "string"
      || !/^[a-zA-Z0-9_-]{8,128}$/u.test(item.workspace_id)
      || typeof item.title !== "string"
      || item.title.length < 1
      || item.title.length > 255
      || typeof item.summary !== "string"
      || (item.status !== "active" && item.status !== "archived")
      || typeof item.latest_completed_sequence !== "number"
      || !Number.isSafeInteger(item.latest_completed_sequence)
      || item.latest_completed_sequence < 0
      || typeof item.created_at !== "string"
      || !Number.isFinite(Date.parse(item.created_at))
      || typeof item.updated_at !== "string"
      || !Number.isFinite(Date.parse(item.updated_at))
    ) {
      throw new CloudModelAccessError(
        "INVALID_RESPONSE",
        "The assistant workspace index crossed a tenant or edition boundary.",
        502,
      );
    }
    return item;
  });
  const conversationIds = new Set(conversations.map((item) => String(item.conversation_id)));
  const latestArtifacts = new Map<string, AssistantWorkspaceIndexEntry["latest_artifact"]>();
  for (const item of value.artifacts) {
    if (
      !isRecord(item)
      || typeof item.artifact_id !== "string"
      || typeof item.conversation_id !== "string"
      || !conversationIds.has(item.conversation_id)
      || item.tenant_id !== expectedTenantId
      || item.organization_id !== expectedOrganizationId
      || item.edition !== expectedEdition
      || typeof item.workspace_id !== "string"
      || !ARTIFACT_KINDS.includes(item.artifact_kind as typeof ARTIFACT_KINDS[number])
      || !artifactMatchesEdition(expectedEdition, item)
      || typeof item.title !== "string"
      || typeof item.version !== "number"
      || !Number.isSafeInteger(item.version)
      || item.version < 1
      || (item.status !== "draft" && item.status !== "archived")
      || typeof item.created_at !== "string"
      || !Number.isFinite(Date.parse(item.created_at))
      || typeof item.updated_at !== "string"
      || !Number.isFinite(Date.parse(item.updated_at))
    ) {
      throw new CloudModelAccessError(
        "INVALID_RESPONSE",
        "The assistant artifact index crossed a tenant, edition, or conversation boundary.",
        502,
      );
    }
    const conversation = conversations.find(
      (candidate) => candidate.conversation_id === item.conversation_id,
    );
    if (!conversation || conversation.workspace_id !== item.workspace_id) {
      throw new CloudModelAccessError(
        "INVALID_RESPONSE",
        "The assistant artifact index crossed a workspace boundary.",
        502,
      );
    }
    if (!latestArtifacts.has(item.conversation_id)) {
      latestArtifacts.set(item.conversation_id, {
        artifact_id: item.artifact_id,
        artifact_kind: item.artifact_kind as typeof ARTIFACT_KINDS[number],
        title: item.title,
        version: item.version,
        status: item.status,
        created_at: item.created_at,
        updated_at: item.updated_at,
      });
    }
  }
  return conversations.map((conversation) => ({
    conversation_id: conversation.conversation_id as string,
    tenant_id: conversation.tenant_id as string,
    organization_id: conversation.organization_id as string | null,
    edition: conversation.edition as BrandEditionId,
    workspace_id: conversation.workspace_id as string,
    title: conversation.title as string,
    summary: conversation.summary as string,
    status: conversation.status as "active" | "archived",
    latest_completed_sequence: conversation.latest_completed_sequence as number,
    created_at: conversation.created_at as string,
    updated_at: conversation.updated_at as string,
    latest_artifact: latestArtifacts.get(conversation.conversation_id as string) ?? null,
  }));
}

async function assistantDataRequest(
  path: string,
  init: RequestInit,
  idempotencyKey?: string,
): Promise<unknown> {
  if (!assistantOrchestratorUrl) {
    throw new CloudModelAccessError(
      "SERVICE_NOT_CONFIGURED",
      "The assistant orchestrator URL is not configured in this build.",
      503,
    );
  }
  const headers = {
    ...authHeaders(idempotencyKey),
    ...(init.headers ?? {}),
  };
  let response: Response;
  try {
    response = await fetchWithDeadline(
      `${assistantOrchestratorUrl}${path}`,
      {
        ...init,
        headers,
      },
      ASSISTANT_TIMEOUT_MS,
      ASSISTANT_RESPONSE_MAX_BYTES,
    );
  } catch (error) {
    if (error instanceof FetchResponseSizeError) {
      throw new CloudModelAccessError("RESPONSE_TOO_LARGE", error.message, 502);
    }
    throw new CloudModelAccessError(
      "NETWORK_ERROR",
      error instanceof Error ? error.message : "The assistant service could not be reached.",
      0,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (error instanceof FetchDeadlineError) {
      throw new CloudModelAccessError("NETWORK_ERROR", error.message, 0);
    }
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      `The assistant service returned HTTP ${response.status} without JSON.`,
      response.status,
    );
  }
  const envelope = isRecord(payload) ? payload : {};
  if (response.ok && "data" in envelope) return envelope.data;
  const cloudError = isRecord(envelope.error) ? envelope.error : {};
  throw new CloudModelAccessError(
    typeof cloudError.code === "string" ? cloudError.code : "ASSISTANT_REQUEST_FAILED",
    typeof cloudError.message === "string"
      ? cloudError.message
      : `The assistant request failed with HTTP ${response.status}.`,
    response.status,
  );
}

async function assistantRequest(
  path: string,
  init: RequestInit,
  idempotencyKey?: string,
): Promise<AssistantOrchestratedRun> {
  return parseRun(await assistantDataRequest(path, init, idempotencyKey));
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function waitForRun(
  initial: AssistantOrchestratedRun,
  onStage?: (stage: AssistantRunStage) => void,
): Promise<AssistantOrchestratedRun> {
  let run = initial;
  onStage?.(run.stage);
  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    if (run.state === "completed" || run.state === "failed") return run;
    await wait(Math.min(2_000, 350 + attempt * 75));
    run = await assistantRequest(`/runs/${encodeURIComponent(run.run_id)}`, {
      method: "GET",
    });
    onStage?.(run.stage);
  }
  throw new CloudModelAccessError(
    "ASSISTANT_TIMEOUT",
    "The assistant is still processing this turn. Reopen the workspace to resume it.",
    202,
  );
}

export async function orchestrateAssistantTurn(
  input: OrchestratedAssistantTurnInput,
): Promise<OrchestratedAssistantTurnResult> {
  const initial = await assistantRequest(
    "/turns",
    {
      method: "POST",
      body: JSON.stringify({
        edition: input.edition,
        workspace_id: input.workspaceId,
        organization_id: input.organizationId ?? null,
        idempotency_key: input.idempotencyKey,
        provider: input.selectedModel.provider,
        model: input.selectedModel.model,
        message: input.message,
        locale: input.locale,
        current_values: input.currentValues,
        reference_documents: input.documentContext?.chunks ?? [],
      }),
    },
    input.idempotencyKey,
  );
  const run = await waitForRun(initial, input.onStage);
  if (run.state === "failed") {
    throw new CloudModelAccessError(
      run.error_code ?? "ASSISTANT_FAILED",
      run.error_message ?? "The assistant could not complete this turn.",
      502,
    );
  }
  if (!run.result_json?.response) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The completed assistant run has no sealed result.",
      502,
    );
  }
  return { run, response: completedRunResponse(run)! };
}

export async function getAssistantWorkspace(
  edition: BrandEditionId,
  workspaceId: string,
  organizationId: string | null = null,
): Promise<AssistantWorkspaceSnapshot | null> {
  if (!/^[a-zA-Z0-9_-]{8,128}$/u.test(workspaceId)) {
    throw new CloudModelAccessError(
      "INVALID_WORKSPACE",
      "The assistant workspace id is invalid.",
      400,
    );
  }
  const query = organizationId
    ? `?organization_id=${encodeURIComponent(organizationId)}`
    : "";
  const data = await assistantDataRequest(
    `/workspaces/${edition}/${encodeURIComponent(workspaceId)}${query}`,
    { method: "GET" },
  );
  return parseWorkspaceSnapshot(data, edition, workspaceId);
}

export async function getAssistantWorkspaceIndex(
  edition: BrandEditionId,
  ownerId: string,
  organizationId: string | null = null,
): Promise<AssistantWorkspaceIndexEntry[]> {
  const expectedTenantId = organizationId ?? ownerId;
  const query = organizationId
    ? `?organization_id=${encodeURIComponent(organizationId)}`
    : "";
  const data = await assistantDataRequest(
    `/workspaces/${edition}${query}`,
    { method: "GET" },
  );
  return parseWorkspaceIndex(data, edition, expectedTenantId, organizationId);
}

export function latestCompletedAssistantResponse(
  snapshot: AssistantWorkspaceSnapshot,
): ExperimentAssistantTurnResponse | null {
  const completed = snapshot.runs
    .filter((run) => run.state === "completed")
    .sort((left, right) => right.sequence - left.sequence)[0];
  return completed ? completedRunResponse(completed) : null;
}

export function completedAssistantResponseForArtifact(
  snapshot: AssistantWorkspaceSnapshot,
  artifactId: string,
): ExperimentAssistantTurnResponse | null {
  const artifact = snapshot.artifacts.find((item) => item.artifact_id === artifactId);
  if (!artifact) return null;
  const completed = snapshot.runs.find(
    (run) => run.run_id === artifact.run_id && run.state === "completed",
  );
  return completed ? completedRunResponse(completed) : null;
}
