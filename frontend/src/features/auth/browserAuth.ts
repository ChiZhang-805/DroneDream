import type { BrowserAuthSession } from "../../desktop/bridge";
import { supabaseClient } from "./supabaseClient";

const EXPECTED_PROTOCOL = "desktop-browser-auth-pkce-v1";
const CLIENT_BY_EDITION = {
  universal: "dronedream-desktop-universal",
  sim: "dronedream-desktop-sim",
  lab: "dronedream-desktop-lab",
  field: "dronedream-desktop-field",
} as const;

function expectedDesktopEdition(): keyof typeof CLIENT_BY_EDITION {
  const configured = (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)
    ?.trim()
    .toLowerCase();
  if (configured && configured in CLIENT_BY_EDITION) {
    return configured as keyof typeof CLIENT_BY_EDITION;
  }
  return "universal";
}

export async function adoptBrowserAuthSession(
  session: BrowserAuthSession,
): Promise<void> {
  if (!supabaseClient) {
    throw new Error("DroneDream account authentication is not configured.");
  }
  const edition = expectedDesktopEdition();
  if (
    session.protocolVersion !== EXPECTED_PROTOCOL ||
    session.editionId !== edition ||
    session.authClientId !== CLIENT_BY_EDITION[edition]
  ) {
    throw new Error("The browser session belongs to a different DroneDream edition.");
  }
  const { error } = await supabaseClient.auth.setSession({
    access_token: session.accessToken,
    refresh_token: session.refreshToken,
  });
  if (error) {
    throw new Error(error.message || "The browser session could not be adopted.");
  }
}
