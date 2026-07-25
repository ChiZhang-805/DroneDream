let accessToken: string | null = null;

export function getAuthAccessToken(): string | null {
  return accessToken;
}

export function setAuthAccessToken(nextToken: string | null): void {
  accessToken = nextToken;
}
