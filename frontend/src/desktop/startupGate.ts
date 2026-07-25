export type DesktopStartupGateStatus =
  | "idle"
  | "checking"
  | "accountRequired"
  | "ready"
  | "blocked";

export interface DesktopStartupGateSession {
  status: DesktopStartupGateStatus;
  accountId: string | null;
  checkedAt: number | null;
  error: string | null;
}

type DesktopStartupGateListener = () => void;

const INITIAL_SESSION: DesktopStartupGateSession = {
  status: "idle",
  accountId: null,
  checkedAt: null,
  error: null,
};

let session = INITIAL_SESSION;
let verificationInFlight: {
  accountId: string;
  promise: Promise<DesktopStartupGateSession>;
} | null = null;
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
  options: { accountId?: string | null; error?: string | null } = {},
): DesktopStartupGateSession {
  verificationInFlight = null;
  return publish({
    status,
    accountId: options.accountId ?? null,
    checkedAt: null,
    error: options.error ?? null,
  });
}

export function approveDesktopStartupGateWithoutCloudAuth(): DesktopStartupGateSession {
  verificationInFlight = null;
  return publish({
    status: "ready",
    accountId: null,
    checkedAt: Date.now(),
    error: null,
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

  publish({
    status: "checking",
    accountId,
    checkedAt: null,
    error: null,
  });
  const operation = verifier()
    .then((result) => {
      if (result.status !== "ready" || result.user_id !== accountId) {
        throw new Error("The local API accepted a different account identity.");
      }
      return publish({
        status: "ready",
        accountId,
        checkedAt: Date.now(),
        error: null,
      });
    })
    .catch((error: unknown) =>
      publish({
        status: "blocked",
        accountId,
        checkedAt: null,
        error: error instanceof Error
          ? error.message
          : "The local API did not accept the signed-in account.",
      })
    )
    .finally(() => {
      if (verificationInFlight?.promise === operation) {
        verificationInFlight = null;
      }
    });
  verificationInFlight = { accountId, promise: operation };
  return operation;
}

export function resetDesktopStartupGateSession(): void {
  verificationInFlight = null;
  publish(INITIAL_SESSION);
}
