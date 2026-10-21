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

/** Bound bridge allocation and reject invalid UTF-8/JSON; decoding proves no user identity. */
function decodeBoundedJson(bodyBase64: string): ApiEnvelopeShape | null {
  if (bodyBase64.length > MAX_CONTRACT_RESPONSE_BASE64_LENGTH) return null;
  try {
    const binary = atob(bodyBase64);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as ApiEnvelopeShape
      : null;
  } catch {
    return null;
  }
}

/** Inspect only a coherent failure envelope, not a success carrying a stray error field. */
function errorCode(envelope: ApiEnvelopeShape | null): string | null {
  if (envelope?.success !== false || envelope.data != null || !envelope.error ||
      typeof envelope.error !== "object" || Array.isArray(envelope.error)) return null;
  const code = (envelope.error as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

/** Recognize the development/no-auth route shape without adopting its reported account. */
function isValidAnonymousSuccess(envelope: ApiEnvelopeShape | null): boolean {
  if (envelope?.success !== true || envelope.error != null || !envelope.data ||
      typeof envelope.data !== "object" || Array.isArray(envelope.data)) {
    return false;
  }
  const data = envelope.data as { status?: unknown; user_id?: unknown };
  return data.status === "ready" && typeof data.user_id === "string" && data.user_id.length > 0;
}

/** Represent this capability as one required component of the existing Runtime report. */
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

/** Replace only our previous diagnostic; success cannot promote an otherwise unready Runtime. */
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

/** Expose stable repair-routing codes, never native exception text or credentials. */
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
