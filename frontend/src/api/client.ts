// HTTP client for the DroneDream /api/v1 backend. It owns envelope parsing,
// desktop-runtime liveness checks, and the typed call surface used by pages.

import {
  desktopApiRequest,
  desktopDownloadArtifact,
  isDesktopRuntime,
} from "../desktop/bridge";
import {
  FetchDeadlineError,
  FetchResponseSizeError,
  fetchWithDeadline,
} from "./fetchWithDeadline";
import {
  ensureDesktopRuntimeLiveness,
  getDesktopReadinessSession,
} from "../desktop/readiness";
import { getDesktopStartupGateSession } from "../desktop/startupGate";
import { getAuthAccessToken } from "../features/auth/authTokenStore";
import { publicDemoConsole } from "../features/demo/publicDemo";
import type {
  ApiEnvelope,
  Artifact,
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyHarnessInspectRequest,
  AutonomyHarnessInspectResponse,
  AutonomyRuntimeObservation,
  AutonomyRuntimeSession,
  AutonomySimulationExecution,
  AutonomyMapAssetAdmissionReceipt,
  AutonomyMapPackQualificationReceipt,
  AutonomyMapPackQualificationRequest,
  AutonomySceneCatalogResponse,
  AutonomyVehiclePackQualificationReceipt,
  AutonomyVehiclePackQualificationRequest,
  BackendCapabilitiesResponse,
  BatchCreateRequest,
  BatchJob,
  Job,
  JobCompareResponse,
  JobCreateRequest,
  DeleteJobResponse,
  ExperimentAssistantTurnRequest,
  ExperimentAssistantTurnResponse,
  DeleteUserExperiencePreferencesResponse,
  JobUpdateRequest,
  JobRerunRequest,
  ContinueExplorationRequest,
  JobReport,
  PaginatedBatchJobs,
  JobStatus,
  PaginatedJobs,
  ParameterCatalogApiResponse,
  TaskWorkflowCompileRequest,
  TaskWorkflowContract,
  OptimizationHistory,
  Trial,
  TrialSummary,
  UserExperiencePreferences,
  UserExperiencePreferencesMutation,
  UserExperiencePreferencesUpdate,
} from "../types/api";

export class ApiClientError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly httpStatus: number;

  constructor(
    code: string,
    message: string,
    details: unknown = null,
    httpStatus = 0,
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.details = details;
    this.httpStatus = httpStatus;
  }
}

// Vite injects import.meta.env at build time. Falls back to the dev server
// host so `npm run dev` + `uvicorn` works with no config.
const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://127.0.0.1:8000";
const DEMO_AUTH_TOKEN: string | undefined =
  import.meta.env.VITE_DEMO_AUTH_TOKEN as string | undefined;
const BROWSER_REQUEST_TIMEOUT_MS = 120_000;
const BROWSER_API_RESPONSE_MAX_BYTES = 64 * 1024 * 1024;
const BROWSER_ARTIFACT_RESPONSE_MAX_BYTES = 256 * 1024 * 1024;
const DESKTOP_API_REQUEST_MAX_BYTES = 25 * 1024 * 1024;

function authHeaders(): Record<string, string> {
  const accessToken = currentAccessToken();
  if (!accessToken) {
    return {};
  }
  return { Authorization: `Bearer ${accessToken}` };
}

function currentAccessToken(): string | null {
  return getAuthAccessToken() ?? DEMO_AUTH_TOKEN ?? null;
}

export function artifactDownloadUrl(artifactId: string): string {
  return `${API_BASE_URL}/api/v1/artifacts/${encodeURIComponent(artifactId)}/download`;
}

async function triggerBrowserDownload(
  content: Blob,
  filename: string,
): Promise<void> {
  const objectUrl = URL.createObjectURL(content);
  const link = document.createElement("a");
  try {
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    // Firefox and embedded WebViews may not have consumed the object URL when
    // click() returns. Revoke it on the next task so the download can start,
    // while still guaranteeing bounded resource cleanup.
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

interface RequestPolicy {
  requireRuntimeLiveness?: boolean;
  idempotentMutation?: boolean;
}

interface PendingMutation {
  fingerprint: string;
  idempotencyKey: string;
  createdAt: number;
}

const PENDING_MUTATIONS_STORAGE_KEY =
  "dronedream.api.pending-mutations.v1";
const PENDING_MUTATION_TTL_MS = 30 * 60 * 1000;
const MAX_PENDING_MUTATIONS = 16;
const CANONICAL_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function loadPendingMutations(now = Date.now()): PendingMutation[] {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(PENDING_MUTATIONS_STORAGE_KEY) ?? "[]",
    ) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((value): value is PendingMutation => {
        if (!value || typeof value !== "object") return false;
        const candidate = value as Partial<PendingMutation>;
        return (
          typeof candidate.fingerprint === "string" &&
          /^[0-9a-f]{64}$/.test(candidate.fingerprint) &&
          typeof candidate.idempotencyKey === "string" &&
          CANONICAL_UUID.test(candidate.idempotencyKey) &&
          typeof candidate.createdAt === "number" &&
          Number.isFinite(candidate.createdAt) &&
          candidate.createdAt <= now &&
          now - candidate.createdAt <= PENDING_MUTATION_TTL_MS
        );
      })
      .slice(-MAX_PENDING_MUTATIONS);
  } catch {
    return [];
  }
}

function savePendingMutations(entries: PendingMutation[]): void {
  try {
    if (entries.length === 0) {
      localStorage.removeItem(PENDING_MUTATIONS_STORAGE_KEY);
      return;
    }
    localStorage.setItem(
      PENDING_MUTATIONS_STORAGE_KEY,
      JSON.stringify(entries.slice(-MAX_PENDING_MUTATIONS)),
    );
  } catch {
    // Storage can be unavailable under restrictive WebView policies. The
    // in-call exact retry remains safe even without restart persistence.
  }
}

async function mutationFingerprint(
  path: string,
  init: RequestInit | undefined,
): Promise<string | null> {
  if (!crypto.subtle) return null;
  const method = (init?.method ?? "GET").toUpperCase();
  const body = typeof init?.body === "string" ? init.body : "";
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${method}\n${path}\n${body}`),
  );
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

async function preparePendingMutation(
  path: string,
  init: RequestInit | undefined,
): Promise<PendingMutation> {
  const fingerprint = await mutationFingerprint(path, init);
  const now = Date.now();
  const existing = loadPendingMutations(now);
  if (fingerprint) {
    const match = existing.find(
      (entry) => entry.fingerprint === fingerprint,
    );
    if (match) return match;
  }
  const created: PendingMutation = {
    fingerprint: fingerprint ?? "0".repeat(64),
    idempotencyKey: crypto.randomUUID(),
    createdAt: now,
  };
  if (fingerprint) savePendingMutations([...existing, created]);
  return created;
}

function clearPendingMutation(pending: PendingMutation | null): void {
  if (!pending || pending.fingerprint === "0".repeat(64)) return;
  savePendingMutations(
    loadPendingMutations().filter(
      (entry) =>
        entry.fingerprint !== pending.fingerprint ||
        entry.idempotencyKey !== pending.idempotencyKey,
    ),
  );
}

async function request<T>(
  path: string,
  init?: RequestInit,
  policy: RequestPolicy = {},
): Promise<T> {
  if (isDesktopRuntime() && policy.requireRuntimeLiveness) {
    const readiness = getDesktopReadinessSession()?.snapshot;
    if (!readiness?.ready) {
      throw new ApiClientError(
        "DESKTOP_RUNTIME_NOT_READY",
        "The local DroneDream runtime has not been approved for this session. Open Settings and click Check environment before starting an experiment.",
      );
    }
    const startupGate = getDesktopStartupGateSession();
    if (startupGate.status !== "ready") {
      throw new ApiClientError(
        "DESKTOP_STARTUP_GATE_NOT_READY",
        "The startup checks have not approved this account and runtime session.",
      );
    }
    try {
      const live = await ensureDesktopRuntimeLiveness({ autoStart: true });
      if (!live.ready) {
        throw new ApiClientError(
          "DESKTOP_RUNTIME_NOT_READY",
          "The local DroneDream runtime stopped responding before the experiment started.",
        );
      }
    } catch (error) {
      if (error instanceof ApiClientError) throw error;
      throw new ApiClientError(
        "DESKTOP_RUNTIME_NOT_READY",
        error instanceof Error
          ? error.message
          : "The local DroneDream runtime could not be verified.",
      );
    }
  }

  const pendingMutation =
    policy.idempotentMutation
    ? await preparePendingMutation(path, init)
    : null;
  const idempotencyKey = pendingMutation?.idempotencyKey ?? null;
  const send = () =>
    transportRequest(path, init, "application/json", idempotencyKey);
  let response: Response;
  try {
    response = await send();
  } catch (networkError) {
    if (networkError instanceof FetchResponseSizeError) {
      throw new ApiClientError(
        "RESPONSE_TOO_LARGE",
        networkError.message,
        null,
        networkError.httpStatus,
      );
    }
    // Do not retry writes after an ambiguous transport failure until the
    // deployed backend persists and replays idempotency receipts.
    throw new ApiClientError(
      "NETWORK_ERROR",
      networkError instanceof Error
        ? networkError.message
        : "Failed to reach the API.",
      null,
      0,
    );
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch (error) {
    if (error instanceof FetchDeadlineError) {
      throw new ApiClientError("NETWORK_ERROR", error.message, null, 0);
    }
    if (error instanceof FetchResponseSizeError) {
      throw new ApiClientError(
        "RESPONSE_TOO_LARGE",
        error.message,
        null,
        response.status,
      );
    }
    throw new ApiClientError(
      "INTERNAL_ERROR",
      `Unexpected non-JSON response (HTTP ${response.status})`,
      null,
      response.status,
    );
  }

  // The HTTP status remains authoritative. A proxy, stale service worker, or
  // malformed backend must not turn a 4xx/5xx response into a successful
  // mutation merely by returning a body with `success: true`.
  if (response.ok && envelope.success === true) {
    clearPendingMutation(pendingMutation);
    return envelope.data;
  }
  const error = envelope?.error;
  // An in-progress idempotent mutation is not terminal. Keep its key so a
  // later retry can reconcile the same logical operation instead of starting
  // a duplicate with a fresh UUID.
  if (
    !response.ok &&
    envelope.success === false &&
    error?.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS"
  ) {
    clearPendingMutation(pendingMutation);
  }
  throw new ApiClientError(
    error?.code ?? (response.ok ? "INTERNAL_ERROR" : "HTTP_ERROR"),
    error?.message ?? `Request failed with HTTP ${response.status}`,
    error?.details ?? null,
    response.status,
  );
}

async function transportRequest(
  path: string,
  init?: RequestInit,
  accept: "application/json" | "application/octet-stream" | "text/csv" =
    "application/json",
  idempotencyKey: string | null = null,
): Promise<Response> {
  if (isDesktopRuntime()) {
    const method = (init?.method ?? "GET").toUpperCase();
    if (!(method === "GET" || method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE")) {
      throw new Error("The desktop API method is not supported.");
    }
    let body: string | null = null;
    let bodyBase64: string | null = null;
    let contentType: "application/json" | "application/octet-stream" | null = null;
    if (typeof init?.body === "string") {
      body = init.body;
      contentType = "application/json";
    } else if (typeof Blob !== "undefined" && init?.body instanceof Blob) {
      if (init.body.size > DESKTOP_API_REQUEST_MAX_BYTES) {
        throw new Error("The desktop API request body exceeds 25 MiB.");
      }
      bodyBase64 = bytesToBase64(new Uint8Array(await init.body.arrayBuffer()));
      contentType = "application/octet-stream";
    } else if (init?.body != null) {
      throw new Error("The desktop API request body type is not supported.");
    }
    const bridged = await desktopApiRequest({
      method,
      path: `/api/v1${path}`,
      body,
      bodyBase64,
      contentType,
      accessToken: currentAccessToken(),
      accept,
      idempotencyKey,
    });
    const headers = new Headers();
    if (bridged.contentType) headers.set("Content-Type", bridged.contentType);
    const responseBytes = base64ToBytes(bridged.bodyBase64);
    return new Response(responseBytes.buffer as ArrayBuffer, {
      status: bridged.status,
      headers,
    });
  }
  const formDataBody = typeof FormData !== "undefined" && init?.body instanceof FormData;
  return fetchWithDeadline(
    `${API_BASE_URL}/api/v1${path}`,
    {
      ...init,
      headers: {
        ...(formDataBody ? {} : { "Content-Type": "application/json" }),
        Accept: accept,
        ...authHeaders(),
        ...(init?.headers ?? {}),
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
    },
    BROWSER_REQUEST_TIMEOUT_MS,
    accept === "application/octet-stream"
      ? BROWSER_ARTIFACT_RESPONSE_MAX_BYTES
      : BROWSER_API_RESPONSE_MAX_BYTES,
  );
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const apiClient = {
  async listAutonomyScenes(): Promise<AutonomySceneCatalogResponse> {
    return request<AutonomySceneCatalogResponse>("/autonomy/scenes");
  },

  async compileAutonomyMission(
    req: AutonomyCompileRequest,
  ): Promise<AutonomyCompileResponse> {
    return request<AutonomyCompileResponse>("/autonomy/compile", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async compileTaskWorkflow(
    req: TaskWorkflowCompileRequest,
  ): Promise<TaskWorkflowContract> {
    return request<TaskWorkflowContract>("/task-workflows/compile", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async inspectAutonomyHarness(
    req: AutonomyHarnessInspectRequest,
  ): Promise<AutonomyHarnessInspectResponse> {
    return request<AutonomyHarnessInspectResponse>("/autonomy/harness/inspect", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async qualifyAutonomyVehiclePack(
    req: AutonomyVehiclePackQualificationRequest,
  ): Promise<AutonomyVehiclePackQualificationReceipt> {
    return request<AutonomyVehiclePackQualificationReceipt>("/autonomy/vehicle-packs/qualify", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async admitAutonomyMapAsset(file: File): Promise<AutonomyMapAssetAdmissionReceipt> {
    return request<AutonomyMapAssetAdmissionReceipt>(`/autonomy/map-assets/admit?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
  },

  async qualifyAutonomyMapPack(
    req: AutonomyMapPackQualificationRequest,
  ): Promise<AutonomyMapPackQualificationReceipt> {
    return request<AutonomyMapPackQualificationReceipt>("/autonomy/map-packs/qualify", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async createAutonomyRuntimeSession(
    mission: AutonomyCompileRequest,
    clientRequestId: string,
  ): Promise<AutonomyRuntimeSession> {
    return request<AutonomyRuntimeSession>("/autonomy/runtime/sessions", {
      method: "POST",
      body: JSON.stringify({ mission, client_request_id: clientRequestId }),
    });
  },

  async getAutonomyRuntimeSession(
    sessionId: string,
  ): Promise<AutonomyRuntimeSession> {
    return request<AutonomyRuntimeSession>(
      `/autonomy/runtime/sessions/${encodeURIComponent(sessionId)}`,
    );
  },

  async ingestAutonomyRuntimeObservation(
    sessionId: string,
    observation: AutonomyRuntimeObservation,
  ): Promise<AutonomyRuntimeSession> {
    return request<AutonomyRuntimeSession>(
      `/autonomy/runtime/sessions/${encodeURIComponent(sessionId)}/observations`,
      { method: "POST", body: JSON.stringify(observation) },
    );
  },

  async stopAutonomyRuntimeSession(
    sessionId: string,
    action: "hold" | "resume" | "abort",
    reason: string,
  ): Promise<AutonomyRuntimeSession> {
    return request<AutonomyRuntimeSession>(
      `/autonomy/runtime/sessions/${encodeURIComponent(sessionId)}/operator-commands`,
      { method: "POST", body: JSON.stringify({ action, reason }) },
    );
  },

  async startAutonomySimulationExecution(
    runtimeSessionId: string,
    contractId: string,
    plannerArtifactSha256: string,
    clientRequestId: string,
  ): Promise<AutonomySimulationExecution> {
    return request<AutonomySimulationExecution>("/autonomy/runtime/simulation-executions", {
      method: "POST",
      body: JSON.stringify({
        runtime_session_id: runtimeSessionId,
        contract_id: contractId,
        planner_artifact_sha256: plannerArtifactSha256,
        client_request_id: clientRequestId,
        operator_confirmed: true,
      }),
    });
  },

  async getAutonomySimulationExecution(
    executionId: string,
  ): Promise<AutonomySimulationExecution> {
    return request<AutonomySimulationExecution>(
      `/autonomy/runtime/simulation-executions/${encodeURIComponent(executionId)}`,
    );
  },

  async abortAutonomySimulationExecution(
    executionId: string,
    reason: string,
  ): Promise<AutonomySimulationExecution> {
    return request<AutonomySimulationExecution>(
      `/autonomy/runtime/simulation-executions/${encodeURIComponent(executionId)}/abort`,
      { method: "POST", body: JSON.stringify({ action: "abort", reason }) },
    );
  },

  async compileExperimentAssistantTurn(
    req: ExperimentAssistantTurnRequest,
  ): Promise<ExperimentAssistantTurnResponse> {
    return request<ExperimentAssistantTurnResponse>("/experiment-assistant/turn", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async getUserExperiencePreferences(): Promise<UserExperiencePreferences> {
    return request<UserExperiencePreferences>("/preferences/experience");
  },

  async updateUserExperiencePreferences(
    req: UserExperiencePreferencesUpdate,
  ): Promise<UserExperiencePreferencesMutation> {
    return request<UserExperiencePreferencesMutation>("/preferences/experience", {
      method: "PUT",
      body: JSON.stringify(req),
    }, { idempotentMutation: true });
  },

  async deleteUserExperiencePreferences(): Promise<DeleteUserExperiencePreferencesResponse> {
    return request<DeleteUserExperiencePreferencesResponse>("/preferences/experience", {
      method: "DELETE",
    }, { idempotentMutation: true });
  },

  async getCapabilities(): Promise<BackendCapabilitiesResponse> {
    return request<BackendCapabilitiesResponse>("/capabilities");
  },

  async getParameterCatalog(px4Version: string): Promise<ParameterCatalogApiResponse> {
    const qs = buildQuery({ px4_version: px4Version });
    return request<ParameterCatalogApiResponse>(`/parameter-catalog${qs}`);
  },

  async createJob(req: JobCreateRequest): Promise<Job> {
    if (publicDemoConsole) {
      throw new ApiClientError(
        "EXECUTION_DISABLED",
        "The public web console can save editable drafts but cannot run experiments.",
        null,
        403,
      );
    }
    return request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify(req),
    }, {
      requireRuntimeLiveness: true,
      idempotentMutation: true,
    });
  },

  async listJobs(params?: {
    page?: number;
    page_size?: number;
    status?: JobStatus;
  }): Promise<PaginatedJobs> {
    if (publicDemoConsole) {
      return {
        items: [],
        page: params?.page ?? 1,
        page_size: params?.page_size ?? 20,
        total: 0,
      };
    }
    const qs = buildQuery({
      page: params?.page,
      page_size: params?.page_size,
      status: params?.status,
    });
    return request<PaginatedJobs>(`/jobs${qs}`);
  },

  async getJob(jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  async updateJob(
    jobId: string,
    req: JobUpdateRequest,
    controlVersion: number,
  ): Promise<Job> {
    const qs = buildQuery({ control_version: controlVersion });
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}${qs}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    }, { idempotentMutation: true });
  },
  async deleteJob(
    jobId: string,
    controlVersion: number,
  ): Promise<DeleteJobResponse> {
    const qs = buildQuery({ control_version: controlVersion });
    return request<DeleteJobResponse>(`/jobs/${encodeURIComponent(jobId)}${qs}`, {
      method: "DELETE",
    }, { idempotentMutation: true });
  },

  async listJobTrials(jobId: string): Promise<TrialSummary[]> {
    // Keep the historical "all trials" client contract while the API reads
    // bounded pages. A job is capped at 10,000 trials by JobCreateRequest, so
    // this is at most twenty deterministic requests instead of one unbounded
    // database load.
    const pageSize = 500;
    const maxPages = 20;
    const items: TrialSummary[] = [];
    const seen = new Set<string>();
    for (let page = 1; page <= maxPages; page += 1) {
      const qs = buildQuery({ page, page_size: pageSize });
      const pageItems = await request<TrialSummary[]>(
        `/jobs/${encodeURIComponent(jobId)}/trials${qs}`,
      );
      let added = 0;
      for (const item of pageItems) {
        if (!seen.has(item.id)) {
          seen.add(item.id);
          items.push(item);
          added += 1;
        }
      }
      if (pageItems.length < pageSize) return items;
      if (added === 0) {
        throw new ApiClientError(
          "INVALID_PAGINATION",
          "The trial endpoint returned a repeated page.",
        );
      }
    }
    return items;
  },

  async listJobCandidates(jobId: string): Promise<OptimizationHistory> {
    return request<OptimizationHistory>(
      `/jobs/${encodeURIComponent(jobId)}/candidates`,
    );
  },

  async getTrial(trialId: string): Promise<Trial> {
    return request<Trial>(`/trials/${encodeURIComponent(trialId)}`);
  },

  async getJobReport(jobId: string): Promise<JobReport> {
    return request<JobReport>(
      `/jobs/${encodeURIComponent(jobId)}/report`,
    );
  },

  async listJobArtifacts(jobId: string): Promise<Artifact[]> {
    return request<Artifact[]>(
      `/jobs/${encodeURIComponent(jobId)}/artifacts`,
    );
  },

  async downloadArtifact(artifactId: string, filename?: string): Promise<void> {
    if (isDesktopRuntime()) {
      try {
        await desktopDownloadArtifact({
          artifactId,
          filename: filename ?? `artifact-${artifactId}`,
          accessToken: currentAccessToken(),
        });
        return;
      } catch (networkError) {
        throw new ApiClientError(
          "ARTIFACT_DOWNLOAD_FAILED",
          networkError instanceof Error
            ? networkError.message
            : "Failed to save the artifact.",
          null,
          0,
        );
      }
    }
    let response: Response;
    try {
      response = await transportRequest(
        `/artifacts/${encodeURIComponent(artifactId)}/download`,
        undefined,
        "application/octet-stream",
      );
    } catch (networkError) {
      if (networkError instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "ARTIFACT_TOO_LARGE",
          networkError.message,
          null,
          networkError.httpStatus,
        );
      }
      throw new ApiClientError(
        "NETWORK_ERROR",
        networkError instanceof Error
          ? networkError.message
          : "Failed to download artifact.",
        null,
        0,
      );
    }

    if (!response.ok) {
      throw new ApiClientError(
        "ARTIFACT_DOWNLOAD_FAILED",
        `Failed to download artifact (HTTP ${response.status})`,
        null,
        response.status,
      );
    }

    try {
      await triggerBrowserDownload(
        await response.blob(),
        filename ?? `artifact-${artifactId}`,
      );
    } catch (error) {
      if (error instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "ARTIFACT_TOO_LARGE",
          error.message,
          null,
          response.status,
        );
      }
      throw error;
    }
  },

  async fetchArtifactJson<T>(artifactId: string): Promise<T> {
    let response: Response;
    try {
      response = await transportRequest(
        `/artifacts/${encodeURIComponent(artifactId)}/download`,
        undefined,
        "application/json",
      );
    } catch (networkError) {
      if (networkError instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "ARTIFACT_TOO_LARGE",
          networkError.message,
          null,
          networkError.httpStatus,
        );
      }
      throw new ApiClientError(
        "NETWORK_ERROR",
        networkError instanceof Error
          ? networkError.message
          : "Failed to download artifact.",
        null,
        0,
      );
    }

    if (!response.ok) {
      throw new ApiClientError(
        "ARTIFACT_DOWNLOAD_FAILED",
        `Failed to download artifact JSON (HTTP ${response.status})`,
        null,
        response.status,
      );
    }

    let payloadText: string;
    try {
      payloadText = await response.text();
    } catch (error) {
      if (error instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "ARTIFACT_TOO_LARGE",
          error.message,
          null,
          response.status,
        );
      }
      throw error;
    }
    try {
      return JSON.parse(payloadText) as T;
    } catch {
      throw new ApiClientError(
        "ARTIFACT_NOT_JSON",
        "Artifact is not valid JSON.",
        null,
        response.status,
      );
    }
  },

  async cancelJob(jobId: string, controlVersion: number): Promise<Job> {
    const qs = buildQuery({ control_version: controlVersion });
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel${qs}`, {
      method: "POST",
    }, { idempotentMutation: true });
  },

  async rerunJob(jobId: string, req?: JobRerunRequest): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}/rerun`, {
      method: "POST",
      body: JSON.stringify(req ?? {}),
    }, {
      requireRuntimeLiveness: true,
      idempotentMutation: true,
    });
  },

  async continueExploration(
    jobId: string,
    controlVersion: number,
    req: ContinueExplorationRequest,
  ): Promise<Job> {
    const qs = buildQuery({ control_version: controlVersion });
    return request<Job>(
      `/jobs/${encodeURIComponent(jobId)}/continue-exploration${qs}`,
      {
        method: "POST",
        body: JSON.stringify(req),
      },
      {
        requireRuntimeLiveness: true,
        idempotentMutation: true,
      },
    );
  },

  async compareJobs(jobIds: string[]): Promise<JobCompareResponse> {
    return request<JobCompareResponse>("/jobs/compare", {
      method: "POST",
      body: JSON.stringify({ job_ids: jobIds }),
    });
  },

  compareJobsCsvUrl(jobIds: string[]): string {
    const joined = encodeURIComponent(jobIds.join(","));
    return `${API_BASE_URL}/api/v1/jobs/compare.csv?job_ids=${joined}`;
  },

  async downloadCompareJobsCsv(jobIds: string[]): Promise<void> {
    let response: Response;
    try {
      const joined = encodeURIComponent(jobIds.join(","));
      response = await transportRequest(
        `/jobs/compare.csv?job_ids=${joined}`,
        undefined,
        "text/csv",
      );
    } catch (networkError) {
      if (networkError instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "COMPARE_CSV_TOO_LARGE",
          networkError.message,
          null,
          networkError.httpStatus,
        );
      }
      throw new ApiClientError(
        "NETWORK_ERROR",
        networkError instanceof Error
          ? networkError.message
          : "Failed to download comparison CSV.",
        null,
        0,
      );
    }
    if (!response.ok) {
      throw new ApiClientError(
        "COMPARE_CSV_DOWNLOAD_FAILED",
        `Failed to download compare CSV (HTTP ${response.status})`,
        null,
        response.status,
      );
    }
    try {
      await triggerBrowserDownload(
        await response.blob(),
        `job-compare-${jobIds.join("_")}.csv`,
      );
    } catch (error) {
      if (error instanceof FetchResponseSizeError) {
        throw new ApiClientError(
          "COMPARE_CSV_TOO_LARGE",
          error.message,
          null,
          response.status,
        );
      }
      throw error;
    }
  },

  async createBatch(req: BatchCreateRequest): Promise<BatchJob> {
    return request<BatchJob>("/batches", {
      method: "POST",
      body: JSON.stringify(req),
    }, {
      requireRuntimeLiveness: true,
      idempotentMutation: true,
    });
  },

  async listBatches(params?: {
    page?: number;
    page_size?: number;
  }): Promise<PaginatedBatchJobs> {
    const qs = buildQuery({
      page: params?.page,
      page_size: params?.page_size,
    });
    return request<PaginatedBatchJobs>(`/batches${qs}`);
  },

  async getBatch(batchId: string): Promise<BatchJob> {
    return request<BatchJob>(`/batches/${encodeURIComponent(batchId)}`);
  },

  async listBatchJobs(batchId: string): Promise<Job[]> {
    return request<Job[]>(`/batches/${encodeURIComponent(batchId)}/jobs`);
  },

  async cancelBatch(
    batchId: string,
    controlVersion: number,
  ): Promise<BatchJob> {
    const qs = buildQuery({ control_version: controlVersion });
    return request<BatchJob>(`/batches/${encodeURIComponent(batchId)}/cancel${qs}`, {
      method: "POST",
    }, { idempotentMutation: true });
  },
};

export type ApiClient = typeof apiClient;
