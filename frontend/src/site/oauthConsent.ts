export type OAuthEditionId = "universal" | "sim" | "lab" | "field";

export interface OAuthClientRegistration {
  editionId: OAuthEditionId;
  displayName: string;
  clientId: string;
  callbackPort: number;
  redirectUri: string;
}

export const oauthClientRegistrations = [
  {
    editionId: "universal",
    displayName: "DroneDream",
    clientId: "24cf4e9d-527e-42eb-abd9-5395d579b8fc",
    callbackPort: 49210,
    redirectUri: "http://127.0.0.1:49210/desktop-auth/universal/callback",
  },
  {
    editionId: "sim",
    displayName: "DroneDream \u00b7 SIM",
    clientId: "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df",
    callbackPort: 49211,
    redirectUri: "http://127.0.0.1:49211/desktop-auth/sim/callback",
  },
  {
    editionId: "lab",
    displayName: "DroneDream \u00b7 LAB",
    clientId: "0b9e7a8d-2c90-4b76-8842-511363f555bd",
    callbackPort: 49212,
    redirectUri: "http://127.0.0.1:49212/desktop-auth/lab/callback",
  },
  {
    editionId: "field",
    displayName: "DroneDream \u00b7 FIELD",
    clientId: "3140bbe2-5f0e-4699-8a9b-295d4030f853",
    callbackPort: 49213,
    redirectUri: "http://127.0.0.1:49213/desktop-auth/field/callback",
  },
] as const satisfies readonly OAuthClientRegistration[];

const AUTHORIZATION_ID_PATTERN = /^[A-Za-z0-9_-]{16,512}$/u;
const OAUTH_SCOPE_SET = new Set(["openid", "email", "profile"]);
const OAUTH_REDIRECT_QUERY_KEYS = new Set([
  "code",
  "state",
  "error",
  "error_description",
  "error_uri",
]);

export function isOAuthAuthorizationId(value: string | null): value is string {
  return value !== null && AUTHORIZATION_ID_PATTERN.test(value);
}

export function oauthAuthorizationId(search: URLSearchParams): string | null {
  const values = search.getAll("authorization_id");
  if (values.length !== 1 || !isOAuthAuthorizationId(values[0])) return null;
  return values[0];
}

export function oauthConsentPath(authorizationId: string): string {
  if (!isOAuthAuthorizationId(authorizationId)) {
    throw new Error("Invalid OAuth authorization identifier");
  }
  const search = new URLSearchParams({ authorization_id: authorizationId });
  return `/oauth/consent/?${search.toString()}`;
}

export function isSafeOAuthConsentReturnPath(candidate: string): boolean {
  let url: URL;
  try {
    url = new URL(candidate, "https://getdronedream.com");
  } catch {
    return false;
  }
  return url.origin === "https://getdronedream.com"
    && url.pathname === "/oauth/consent/"
    && url.hash === ""
    && [...url.searchParams.keys()].every((key) => key === "authorization_id")
    && oauthAuthorizationId(url.searchParams) !== null;
}

export function oauthClientRegistration(
  clientId: string,
  redirectUri: string,
): OAuthClientRegistration | null {
  return oauthClientRegistrations.find((registration) =>
    registration.clientId === clientId
    && registration.redirectUri === redirectUri
  ) ?? null;
}

export function isExpectedOAuthScope(scope: string): boolean {
  const scopes = scope.split(/\s+/u).filter(Boolean);
  return scopes.length === OAUTH_SCOPE_SET.size
    && new Set(scopes).size === scopes.length
    && scopes.every((candidate) => OAUTH_SCOPE_SET.has(candidate));
}

export function safeOAuthRedirectUrl(
  candidate: string,
  expectedRegistration?: OAuthClientRegistration,
): string | null {
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }
  if (url.username || url.password || url.hash) return null;

  const registration = oauthClientRegistrations.find((entry) => {
    const registeredUrl = new URL(entry.redirectUri);
    return url.origin === registeredUrl.origin && url.pathname === registeredUrl.pathname;
  });
  if (!registration || (expectedRegistration
    && (
      registration.clientId !== expectedRegistration.clientId
      || registration.redirectUri !== expectedRegistration.redirectUri
    ))) return null;

  const keys = [...url.searchParams.keys()];
  if (keys.some((key) => !OAUTH_REDIRECT_QUERY_KEYS.has(key))) return null;
  if ([...new Set(keys)].some((key) => url.searchParams.getAll(key).length !== 1)) {
    return null;
  }

  const state = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");
  if (!state || !AUTHORIZATION_ID_PATTERN.test(state) || Boolean(code) === Boolean(error)) {
    return null;
  }
  if (code) {
    if (
      keys.length !== 2
      || !keys.includes("code")
      || !keys.includes("state")
      || code.length > 8192
      || /\s/u.test(code)
      || [...code].some((value) => /\p{Cc}/u.test(value))
    ) return null;
  }
  if (error && !/^[a-z][a-z0-9_]{2,63}$/u.test(error)) return null;

  return url.toString();
}
