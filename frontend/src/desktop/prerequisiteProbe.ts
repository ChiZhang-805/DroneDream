import { probeSystemPrerequisites } from "./bridge";
import type { SystemPrerequisiteReport } from "./bridge";

const SYSTEM_PROBE_MAX_ATTEMPTS = 3;
const SYSTEM_PROBE_RETRY_DELAYS_MS = [1_000, 2_000] as const;

export interface SystemProbeRetryPolicy {
  maxAttempts: number;
  retryDelaysMs: readonly number[];
  wait: (delayMs: number) => Promise<void>;
}

const DEFAULT_RETRY_POLICY: SystemProbeRetryPolicy = {
  maxAttempts: SYSTEM_PROBE_MAX_ATTEMPTS,
  retryDelaysMs: SYSTEM_PROBE_RETRY_DELAYS_MS,
  wait: (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)),
};

let startupProbeInFlight: Promise<SystemPrerequisiteReport> | null = null;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The native prerequisite command has its own bounded process timeout. A
 * timeout is nevertheless often transient while Windows warms CIM/WMI after
 * login or while WSL is starting. Other failures (invalid output, unsupported
 * platform, permission errors) are deterministic and must still fail fast.
 */
export function isTransientSystemProbeTimeout(error: unknown): boolean {
  return /(?:timed\s+out|timeout)/iu.test(errorMessage(error));
}

/**
 * Retry only transient native timeouts. Keeping this orchestration outside the
 * React page means the setup launcher and the global Runtime access guard use
 * exactly the same startup grace policy.
 */
export async function runSystemProbeWithStartupGrace<T>(
  probe: () => Promise<T>,
  policy: SystemProbeRetryPolicy = DEFAULT_RETRY_POLICY,
): Promise<T> {
  const maxAttempts = Math.max(1, Math.trunc(policy.maxAttempts));
  let lastError: unknown;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await probe();
    } catch (error) {
      lastError = error;
      const attemptsExhausted = attempt + 1 >= maxAttempts;
      if (attemptsExhausted || !isTransientSystemProbeTimeout(error)) throw error;
      const delayMs = policy.retryDelaysMs[attempt] ??
        policy.retryDelaysMs.at(-1) ?? 0;
      if (delayMs > 0) await policy.wait(delayMs);
    }
  }

  // The loop always returns or throws. Keep a defensive error for malformed
  // policies without replacing the final native diagnostic when one exists.
  throw lastError ?? new Error("System prerequisite probe did not run.");
}

/**
 * Share the complete grace-window operation across concurrent callers. The
 * setup page and the access provider mount together, so without this guard
 * they can launch duplicate PowerShell/CIM probes and make the timeout more
 * likely on otherwise healthy computers.
 */
export function probeSystemPrerequisitesWithStartupGrace(): Promise<SystemPrerequisiteReport> {
  if (startupProbeInFlight) return startupProbeInFlight;

  const operation = runSystemProbeWithStartupGrace(probeSystemPrerequisites);
  startupProbeInFlight = operation;
  operation.then(
    () => {
      if (startupProbeInFlight === operation) startupProbeInFlight = null;
    },
    () => {
      if (startupProbeInFlight === operation) startupProbeInFlight = null;
    },
  );
  return operation;
}
