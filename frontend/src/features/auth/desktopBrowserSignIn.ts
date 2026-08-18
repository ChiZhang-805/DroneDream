import {
  beginBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
} from "../../desktop/bridge";
import { adoptBrowserAuthSession } from "./browserAuth";
import { activateDesktopAuthSession } from "./desktopAuthActivation";

export async function completeDesktopBrowserSignIn(
  locale: "en" | "zh-CN",
): Promise<void> {
  activateDesktopAuthSession();
  const restored = await restoreBrowserAuthVault();
  const session = restored ?? await beginBrowserAuth({ locale });
  try {
    await adoptBrowserAuthSession(session);
  } catch (error) {
    // Native stores only this edition's refresh grant before returning the
    // session. If the WebView cannot adopt it, remove the exact unusable grant
    // so the next explicit sign-in cannot loop on stale credentials.
    await clearBrowserAuthVault().catch(() => false);
    throw error;
  }
}
