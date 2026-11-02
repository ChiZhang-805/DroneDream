// Process-local access-token cache for request clients, not a persistent session
// store. AuthContext owns refresh/sign-out and must clear this on account loss.
let accessToken: string | null = null;

export function getAuthAccessToken(): string | null {
  return accessToken;
}

/** Adopt the active session's token; null prevents subsequent authenticated calls. */
export function setAuthAccessToken(nextToken: string | null): void {
  accessToken = nextToken;
}
