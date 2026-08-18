import {
  beginBrowserAuth,
  cancelBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
} from "../../desktop/bridge";
import { adoptBrowserAuthSession } from "./browserAuth";
import { activateDesktopAuthSession } from "./desktopAuthActivation";

export interface DesktopBrowserSignInOptions {
  signal?: AbortSignal;
  restoreFromVault?: boolean;
  onAdopting?: () => void;
}

function cancelledError(): Error {
  return new Error("Desktop browser sign-in cancelled.");
}

function throwIfCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw cancelledError();
}

function abortable<T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return operation;
  throwIfCancelled(signal);
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

export async function completeDesktopBrowserSignIn(
  locale: "en" | "zh-CN",
  options: DesktopBrowserSignInOptions = {},
): Promise<void> {
  const { signal, restoreFromVault = true, onAdopting } = options;
  throwIfCancelled(signal);
  activateDesktopAuthSession();
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
    if (signal?.aborted) throw cancelledError();
    // Native stores only this edition's refresh grant before returning the
    // session. If the WebView cannot adopt it, remove the exact unusable grant
    // so the next explicit sign-in cannot loop on stale credentials.
    await clearBrowserAuthVault().catch(() => false);
    throw error;
  }
  throwIfCancelled(signal);
}

export async function cancelDesktopBrowserSignIn(
  controller: AbortController,
): Promise<boolean> {
  controller.abort();
  return cancelBrowserAuth().catch(() => false);
}
