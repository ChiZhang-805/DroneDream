const CONSOLE_PREFIX = "/console";
const RECOVERY_PARAMETER = "route";

export function hostedConsoleRecoveryHref(
  pathname: string,
  search = "",
  hash = "",
): string | null {
  if (!pathname.startsWith(`${CONSOLE_PREFIX}/`) || pathname === `${CONSOLE_PREFIX}/`) {
    return null;
  }
  const route = `${pathname.slice(CONSOLE_PREFIX.length)}${search}${hash}`;
  return `${CONSOLE_PREFIX}/?${RECOVERY_PARAMETER}=${encodeURIComponent(route)}`;
}

export function restoredHostedConsolePath(
  pathname: string,
  search: string,
): string | null {
  if (pathname !== CONSOLE_PREFIX && pathname !== `${CONSOLE_PREFIX}/`) return null;
  const route = new URLSearchParams(search).get(RECOVERY_PARAMETER);
  if (!route || !route.startsWith("/") || route.startsWith("//")) return null;

  try {
    const origin = "https://hosted-console.invalid";
    const parsed = new URL(route, origin);
    if (parsed.origin !== origin) return null;
    return `${CONSOLE_PREFIX}${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}
