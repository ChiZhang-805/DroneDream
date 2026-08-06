import { isSafeOAuthConsentReturnPath } from "./oauthConsent";

const SAFE_WEBSITE_AUTH_RETURN_PATHS = new Set([
  "/",
  "/community/",
  "/pricing/",
  "/console/",
]);

export type WebsiteAuthMode = "sign-in" | "register";

function safeWebsiteAuthReturnPath(candidate: string | null): string {
  return candidate && (
    SAFE_WEBSITE_AUTH_RETURN_PATHS.has(candidate)
    || isSafeOAuthConsentReturnPath(candidate)
  )
    ? candidate
    : "/";
}

export function websiteAuthUrl(
  mode: WebsiteAuthMode = "sign-in",
  returnPath = "/",
): string {
  const search = new URLSearchParams({
    source: "website",
    mode,
    returnTo: safeWebsiteAuthReturnPath(returnPath),
  });
  return `/account/?${search.toString()}`;
}

export function websiteAuthReturnPath(search: URLSearchParams): string {
  return safeWebsiteAuthReturnPath(search.get("returnTo"));
}
