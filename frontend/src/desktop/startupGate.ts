export type DesktopStartupGateStatus =
  | "idle"
  | "checking"
  | "accountRequired"
  | "ready"
  | "blocked";

export type DesktopStartupGateFailureCode =
  | "accountIdentityMismatch"
  | "runtimeSessionApiMissing"
  | "accountVerificationFailed"
  | "updateRequired";

export interface DesktopStartupGateSession {
  status: DesktopStartupGateStatus;
  accountId: string | null;
  checkedAt: number | null;
  error: string | null;
  failureCode: DesktopStartupGateFailureCode | null;
}

type DesktopStartupGateListener = () => void;

const INITIAL_SESSION: DesktopStartupGateSession = {
  status: "idle",
  accountId: null,
  checkedAt: null,
  error: null,
  failureCode: null,
};

let session = INITIAL_SESSION;
let verificationInFlight: {
  accountId: string;
  revision: number;
  promise: Promise<DesktopStartupGateSession>;
} | null = null;
let verificationRevision = 0;
const listeners = new Set<DesktopStartupGateListener>();

function publish(next: DesktopStartupGateSession): DesktopStartupGateSession {
  session = next;
  for (const listener of listeners) listener();
  return next;
}

export function getDesktopStartupGateSession(): DesktopStartupGateSession {
  return session;
}

export function subscribeDesktopStartupGate(
  listener: DesktopStartupGateListener,
): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setDesktopStartupGateState(
  status: Exclude<DesktopStartupGateStatus, "ready">,
  options: {
    accountId?: string | null;
    error?: string | null;
    failureCode?: DesktopStartupGateFailureCode | null;
  } = {},
): DesktopStartupGateSession {
  verificationRevision += 1;
  verificationInFlight = null;
  return publish({
    status,
    accountId: options.accountId ?? null,
    checkedAt: null,
    error: options.error ?? null,
    failureCode: options.failureCode ?? null,
  });
}

export function approveDesktopStartupGateWithoutCloudAuth(): DesktopStartupGateSession {
  verificationRevision += 1;
  verificationInFlight = null;
  return publish({
    status: "ready",
    accountId: null,
    checkedAt: Date.now(),
    error: null,
    failureCode: null,
  });
}

export async function verifyDesktopStartupGate(
  accountId: string,
  verifier: () => Promise<{ status: string; user_id: string }>,
): Promise<DesktopStartupGateSession> {
  if (session.status === "ready" && session.accountId === accountId) {
    return session;
  }
  if (verificationInFlight?.accountId === accountId) {
    return verificationInFlight.promise;
  }

  const revision = ++verificationRevision;
  publish({
    status: "checking",
    accountId,
    checkedAt: null,
    error: null,
    failureCode: null,
  });
  const operation = verifier()
    .then((result) => {
      if (
        verificationRevision !== revision ||
        session.status !== "checking" ||
        session.accountId !== accountId
      ) {
        return session;
      }
      if (result.status !== "ready" || result.user_id !== accountId) {
        return publish({
          status: "blocked",
          accountId,
          checkedAt: null,
          error: "The local API accepted a different account identity.",
          failureCode: "accountIdentityMismatch",
        });
      }
      return publish({
        status: "ready",
        accountId,
        checkedAt: Date.now(),
        error: null,
        failureCode: null,
      });
    })
    .catch((error: unknown) => {
      if (
        verificationRevision !== revision ||
        session.status !== "checking" ||
        session.accountId !== accountId
      ) {
        return session;
      }
      const candidate = error && typeof error === "object"
        ? error as { code?: unknown; httpStatus?: unknown }
        : null;
      const missingSessionApi = candidate?.httpStatus === 404 ||
        candidate?.code === "NOT_FOUND";
      return publish({
        status: "blocked",
        accountId,
        checkedAt: null,
        error: missingSessionApi
          ? "The installed Runtime does not provide the desktop account-session API."
          : "The local API did not accept the signed-in account.",
        failureCode: missingSessionApi
          ? "runtimeSessionApiMissing"
          : "accountVerificationFailed",
      });
    })
    .finally(() => {
      if (
        verificationInFlight?.revision === revision &&
        verificationInFlight.promise === operation
      ) {
        verificationInFlight = null;
      }
    });
  verificationInFlight = { accountId, revision, promise: operation };
  return operation;
}

export function resetDesktopStartupGateSession(): void {
  verificationRevision += 1;
  verificationInFlight = null;
  publish(INITIAL_SESSION);
}
