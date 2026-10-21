import {
  beginBrowserAuth,
  cancelBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
} from "../../desktop/bridge";
import {
  adoptBrowserAuthSession,
  shouldClearBrowserAuthVaultAfterAdoptionError,
} from "./browserAuth";
import { activateDesktopAuthSession } from "./desktopAuthActivation";

export interface DesktopBrowserSignInOptions {
  signal?: AbortSignal;
  restoreFromVault?: boolean;
  onAdopting?: () => void;
}

export interface DesktopBrowserRestoreOptions {
  signal?: AbortSignal;
  onAdopting?: () => void;
}

function cancelledError(): Error {
  // A consistent user-facing cancellation message contains no credential details.
  return new Error("Desktop browser sign-in cancelled.");
}

function throwIfCancelled(signal?: AbortSignal): void {
  // Check between native calls as well as before publishing an adopted account.
  if (signal?.aborted) throw cancelledError();
}

function abortable<T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> {
  // Cancel the caller's wait; this cannot roll back the already-started native RPC.
  if (!signal) return operation;
  if (signal.aborted) {
    // Argument evaluation may already have started the operation. Observe even
    // this branch's late rejection while returning cancellation to the caller.
    void operation.catch(() => undefined);
    return Promise.reject(cancelledError());
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const finish = (complete: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      complete();
    };
    const onAbort = () => finish(() => reject(cancelledError()));
    signal.addEventListener("abort", onAbort, { once: true });
    // Always observe the underlying operation. Its late result is ignored
    // after cancellation, but a late rejection must never become unhandled.
    operation.then(
      (value) => finish(() => resolve(value)),
      (error: unknown) => finish(() => reject(error)),
    );
  });
}

async function rethrowAdoptionError(
  error: unknown,
  signal?: AbortSignal,
): Promise<never> {
  // Clear only conclusively unusable credentials, preserving the original failure.
  if (signal?.aborted) throw cancelledError();
  if (shouldClearBrowserAuthVaultAfterAdoptionError(error)) {
    // Native vault entries are edition-scoped. Remove this one only when the
    // adoption result proves it cannot become usable again; connectivity,
    // throttling, service, configuration, and unknown failures retain it.
    await clearBrowserAuthVault().catch(() => false);
    throwIfCancelled(signal);
  }
  throw error;
}

export async function completeDesktopBrowserSignIn(
  locale: "en" | "zh-CN",
  options: DesktopBrowserSignInOptions = {},
): Promise<void> {
  // Explicit sign-in owns launcher activation, browser consent, then remote adoption.
  const { signal, restoreFromVault = false, onAdopting } = options;
  throwIfCancelled(signal);
  activateDesktopAuthSession();
  if (!restoreFromVault) {
    // A desktop launch is intentionally a fresh authentication ceremony.
    // Never let an edition vault silently turn a reopened app into a session.
    await abortable(Promise.resolve(clearBrowserAuthVault()), signal);
  }
  const restored = restoreFromVault
    ? await abortable(restoreBrowserAuthVault(), signal)
    : null;
  throwIfCancelled(signal);
  const session = restored ?? await abortable(beginBrowserAuth({ locale }), signal);
  throwIfCancelled(signal);
  onAdopting?.();
  throwIfCancelled(signal);
  try {
    await abortable(adoptBrowserAuthSession(session, { signal }), signal);
  } catch (error) {
    await rethrowAdoptionError(error, signal);
  }
  throwIfCancelled(signal);
}

export async function restoreDesktopBrowserSession(
  options: DesktopBrowserRestoreOptions = {},
): Promise<boolean> {
  // Restore only when explicitly requested; absence is distinct from invalid adoption.
  const { signal, onAdopting } = options;
  throwIfCancelled(signal);
  activateDesktopAuthSession();
  const restored = await abortable(restoreBrowserAuthVault(), signal);
  throwIfCancelled(signal);
  if (!restored) return false;
  onAdopting?.();
  try {
    await abortable(adoptBrowserAuthSession(restored, { signal }), signal);
  } catch (error) {
    await rethrowAdoptionError(error, signal);
  }
  throwIfCancelled(signal);
  return true;
}

export async function cancelDesktopBrowserSignIn(
  controller: AbortController,
): Promise<boolean> {
  // Stop local publication immediately, even if cancelling the native UI later fails.
  controller.abort();
  return cancelBrowserAuth().catch(() => false);
}
