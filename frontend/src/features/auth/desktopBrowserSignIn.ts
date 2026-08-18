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

export async function completeDesktopBrowserSignIn(
  locale: "en" | "zh-CN",
  options: DesktopBrowserSignInOptions = {},
): Promise<void> {
  const { signal, restoreFromVault = true, onAdopting } = options;
  throwIfCancelled(signal);
  activateDesktopAuthSession();
  const restored = restoreFromVault ? await restoreBrowserAuthVault() : null;
  throwIfCancelled(signal);
  const session = restored ?? await beginBrowserAuth({ locale });
  throwIfCancelled(signal);
  onAdopting?.();
  throwIfCancelled(signal);
  try {
    await adoptBrowserAuthSession(session, { signal });
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
