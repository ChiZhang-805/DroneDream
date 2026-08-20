const EXPECTED_ACCOUNT_URL = "https://yggabfynndpzymlqvnim.supabase.co";
const url = (process.env.VITE_SUPABASE_URL ?? "").trim().replace(/\/+$/u, "");
const publishableKey = (
  process.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? ""
).trim();
const turnstileSiteKey = (
  process.env.VITE_TURNSTILE_SITE_KEY ?? ""
).trim();
const githubCiPlaceholder = process.env.GITHUB_ACTIONS === "true"
  && url === "https://ci.invalid"
  && /^sb_publishable_ci_[a-z0-9_]+$/u.test(publishableKey);
const releaseBuild = Boolean(
  (process.env.DRONEDREAM_RELEASE_SOURCE_COMMIT ?? "").trim(),
);
const editionId = (
  process.env.DRONEDREAM_DESKTOP_EDITION_ID ?? "universal"
).trim();
const oauthClientId = (
  process.env.DRONEDREAM_OAUTH_CLIENT_ID ?? ""
).trim();
const registeredOAuthClientId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

function fail(message) {
  throw new Error(`Desktop browser-auth configuration failed: ${message}`);
}

function looksUnsafe(value) {
  return value.length < 20
    || value.length > 4096
    || /\s|[\u0000-\u001f\u007f]/u.test(value)
    || /placeholder|change.?me|desktop_only/iu.test(value)
    || value.startsWith("sb_secret_");
}

function decodedJwtRole(value) {
  const parts = value.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString("utf8"),
    );
    return typeof payload.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

if (!/^(universal|sim|lab|field|autonomy)$/u.test(editionId)) {
  fail("DRONEDREAM_DESKTOP_EDITION_ID must identify one supported edition");
}
if (
  releaseBuild
  && (
    !registeredOAuthClientId.test(oauthClientId)
    || /^dronedream-desktop-(universal|sim|lab|field|autonomy)$/u.test(oauthClientId)
  )
) {
  fail("release builds require the registered public DRONEDREAM_OAUTH_CLIENT_ID");
}
if (githubCiPlaceholder) {
  console.log("Desktop browser-auth configuration verified with CI-only placeholders.");
  process.exit(0);
}
if (turnstileSiteKey) {
  fail(
    "the standalone desktop browser page does not yet implement Turnstile; "
    + "do not enable Supabase CAPTCHA for desktop releases until that flow is added",
  );
}
if (url !== EXPECTED_ACCOUNT_URL) {
  fail("VITE_SUPABASE_URL must identify the approved DroneDream account service");
}
if (looksUnsafe(publishableKey)) {
  fail("VITE_SUPABASE_PUBLISHABLE_KEY must contain the real public client key");
}
if (decodedJwtRole(publishableKey) === "service_role") {
  fail("a service-role key must never be embedded in the desktop application");
}

console.log("Desktop browser-auth public configuration verified.");
