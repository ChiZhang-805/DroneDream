import {
  desktopApiRequest,
  type RuntimeComponentStatus,
  type RuntimeStatusReport,
} from "./bridge";

export const RUNTIME_SESSION_COMPONENT_ID = "account-session-api";

export type RuntimeSessionContractFailure =
  | "runtime_session_api_missing"
  | "runtime_session_api_unavailable";

const MAX_CONTRACT_RESPONSE_BASE64_LENGTH = 16 * 1024;

interface ApiEnvelopeShape {
  success?: unknown;
  data?: unknown;
  error?: unknown;
}

function decodeBoundedJson(bodyBase64: string): ApiEnvelopeShape | null {
  if (bodyBase64.length > MAX_CONTRACT_RESPONSE_BASE64_LENGTH) return null;
  try {
    const binary = atob(bodyBase64);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const parsed = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
    return parsed && typeof parsed === "object"
      ? parsed as ApiEnvelopeShape
      : null;
  } catch {
    return null;
  }
}

function errorCode(envelope: ApiEnvelopeShape | null): string | null {
  if (!envelope?.error || typeof envelope.error !== "object") return null;
  const code = (envelope.error as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

function isValidAnonymousSuccess(envelope: ApiEnvelopeShape | null): boolean {
  if (envelope?.success !== true || !envelope.data || typeof envelope.data !== "object") {
    return false;
  }
  const data = envelope.data as { status?: unknown; user_id?: unknown };
  return data.status === "ready" && typeof data.user_id === "string" && data.user_id.length > 0;
}

function contractComponent(
  status: RuntimeComponentStatus["status"],
  detail: string,
): RuntimeComponentStatus {
  return {
    id: RUNTIME_SESSION_COMPONENT_ID,
    label: "Desktop account-session API",
    status,
    required: true,
    version: null,
    detail,
  };
}

function withContractComponent(
  report: RuntimeStatusReport,
  component: RuntimeComponentStatus,
): RuntimeStatusReport {
  const components = report.components.filter(
    (candidate) => candidate.id !== RUNTIME_SESSION_COMPONENT_ID,
  );
  components.push(component);
  const failure = component.status !== "ready";
  return {
    ...report,
    ready: failure ? false : report.ready,
    components,
    diagnostics: [
      ...report.diagnostics.filter(
        (diagnostic) => !diagnostic.startsWith("runtime_session_api_"),
      ),
      ...(failure && component.detail ? [component.detail] : []),
    ],
  };
}

/**
 * Verify the environment capability needed by browser-to-desktop sign-in.
 * This deliberately sends no user token: a structured 401 proves that the
 * route exists without checking, adopting, or exposing any account.
 */
export async function verifyRuntimeSessionContract(
  report: RuntimeStatusReport,
): Promise<RuntimeStatusReport> {
  if (!report.installed || !report.running || !report.ready) return report;

  try {
    const response = await desktopApiRequest({
      method: "GET",
      path: "/api/v1/session",
      body: null,
      accessToken: null,
      accept: "application/json",
      idempotencyKey: null,
    });
    const envelope = decodeBoundedJson(response.bodyBase64);
    const routeExists =
      (response.status === 401 && errorCode(envelope) === "UNAUTHORIZED") ||
      (response.status === 200 && isValidAnonymousSuccess(envelope));
    if (routeExists) {
      return withContractComponent(
        report,
        contractComponent("ready", "runtime_session_api_ready"),
      );
    }
    // Older FastAPI builds returned a bare {"detail":"Not Found"} for this
    // exact path, while newer builds use the standard NOT_FOUND envelope. The
    // HTTP status is therefore the stable compatibility signal.
    if (response.status === 404) {
      return withContractComponent(
        report,
        contractComponent("unhealthy", "runtime_session_api_missing"),
      );
    }
  } catch {
    // The caller receives a stable, non-sensitive capability classification.
  }

  return withContractComponent(
    report,
    contractComponent("unhealthy", "runtime_session_api_unavailable"),
  );
}

export function runtimeSessionContractFailure(
  report: RuntimeStatusReport | null,
): RuntimeSessionContractFailure | null {
  const detail = report?.components.find(
    (component) => component.id === RUNTIME_SESSION_COMPONENT_ID,
  )?.detail;
  return detail === "runtime_session_api_missing" ||
    detail === "runtime_session_api_unavailable"
    ? detail
    : null;
}
