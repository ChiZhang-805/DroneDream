const DESKTOP_REDIRECTS = new Map([
  [
    "http://127.0.0.1:49210/desktop-auth/universal/callback",
    { edition: "Universal", product: "DroneDream Universal" },
  ],
  [
    "http://127.0.0.1:49211/desktop-auth/sim/callback",
    { edition: "SIM", product: "DroneDream SIM" },
  ],
  [
    "http://127.0.0.1:49212/desktop-auth/lab/callback",
    { edition: "LAB", product: "DroneDream LAB" },
  ],
  [
    "http://127.0.0.1:49213/desktop-auth/field/callback",
    { edition: "FIELD", product: "DroneDream FIELD" },
  ],
  [
    "http://127.0.0.1:49214/desktop-auth/autonomy/callback",
    { edition: "AGENT", product: "DroneDream · AGENT" },
  ],
] as const);

export function desktopEditionForRedirectUri(value: string) {
  return DESKTOP_REDIRECTS.get(value as never) ?? null;
}

export function isAllowedDesktopRedirectUri(value: string): boolean {
  return DESKTOP_REDIRECTS.has(value as never);
}

export function isAllowedDesktopCallback(value: string): boolean {
  try {
    const url = new URL(value);
    url.search = "";
    url.hash = "";
    return isAllowedDesktopRedirectUri(url.toString());
  } catch {
    return false;
  }
}
