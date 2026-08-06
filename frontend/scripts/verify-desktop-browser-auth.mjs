import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDirectory, "..");

const files = {
  bridge: "src/desktop/bridge.ts",
  authContext: "src/features/auth/AuthContext.tsx",
  browserAuth: "src/features/auth/browserAuth.ts",
  supabaseClient: "src/features/auth/supabaseClient.ts",
  desktopSetup: "src/pages/DesktopSetup.tsx",
  websiteAuth: "src/site/websiteAuth.ts",
  sensitiveOrigin: "src/security/sensitiveOrigin.ts",
};

const sources = Object.fromEntries(
  Object.entries(files).map(([name, relativePath]) => [
    name,
    readFileSync(resolve(frontendRoot, relativePath), "utf8"),
  ]),
);
let checkCount = 0;

function requireMatch(sourceName, pattern, message) {
  if (!pattern.test(sources[sourceName])) {
    throw new Error(`${files[sourceName]}: ${message}`);
  }
  checkCount += 1;
}

function rejectMatch(sourceName, pattern, message) {
  if (pattern.test(sources[sourceName])) {
    throw new Error(`${files[sourceName]}: ${message}`);
  }
  checkCount += 1;
}

const requestInterface = /export interface BrowserAuthRequest\s*\{(?<body>[\s\S]*?)\n\}/u.exec(
  sources.bridge,
);
if (!requestInterface?.groups?.body) {
  throw new Error(`${files.bridge}: BrowserAuthRequest interface is missing`);
}
checkCount += 1;
if (!/^\s*locale:\s*InstallerLocale;\s*$/u.test(requestInterface.groups.body)) {
  throw new Error(
    `${files.bridge}: BrowserAuthRequest must contain only the locale field`,
  );
}
checkCount += 1;

requireMatch(
  "bridge",
  /protocolVersion:\s*"desktop-browser-auth-pkce-v1"/u,
  "browser-auth protocol version is not bound",
);
requireMatch(
  "bridge",
  /editionId:\s*"universal"\s*\|\s*"sim"\s*\|\s*"lab"\s*\|\s*"field"/u,
  "the four edition identities are not bound",
);
for (const field of ["attemptIdHash", "stateHash", "subjectHash"]) {
  requireMatch(
    "bridge",
    new RegExp(`expectLowercaseHex\\(\\s*record\\.${field},`, "u"),
    `${field} is not validated as a lowercase digest`,
  );
}
requireMatch(
  "bridge",
  /invokeDesktop\("restore_browser_auth_vault"/u,
  "edition vault restore bridge is missing",
);
requireMatch(
  "bridge",
  /invokeDesktop\("clear_browser_auth_vault"/u,
  "edition vault clear bridge is missing",
);

for (const [edition, clientId] of Object.entries({
  universal: "dronedream-desktop-universal",
  sim: "dronedream-desktop-sim",
  lab: "dronedream-desktop-lab",
  field: "dronedream-desktop-field",
})) {
  requireMatch(
    "browserAuth",
    new RegExp(`${edition}:\\s*"${clientId}"`, "u"),
    `${edition} auth client identity is missing`,
  );
}
requireMatch(
  "browserAuth",
  /session\.protocolVersion\s*!==\s*EXPECTED_PROTOCOL[\s\S]*session\.editionId\s*!==\s*edition[\s\S]*session\.authClientId\s*!==\s*CLIENT_BY_EDITION\[edition\]/u,
  "protocol, edition, and client identity are not rejected before adoption",
);

requireMatch(
  "supabaseClient",
  /\["universal",\s*"sim",\s*"lab",\s*"field"\]/u,
  "the four edition storage namespaces are not bound",
);
requireMatch(
  "supabaseClient",
  /`dronedream-desktop-auth:\$\{normalized\}:v1`/u,
  "edition-scoped storage key is missing",
);
requireMatch(
  "supabaseClient",
  /desktopRuntime\s*\?\s*window\.sessionStorage\s*:\s*window\.localStorage/u,
  "desktop and website storage lifetimes are not separated",
);

requireMatch(
  "authContext",
  /if\s*\(isDesktopRuntime\(\)\)\s*\{[\s\S]*await clearBrowserAuthVault\(\)/u,
  "vault clearing is not restricted to desktop runtime",
);
requireMatch(
  "authContext",
  /auth\.signOut\(\{\s*scope:\s*"local"\s*\}\)/u,
  "sign-out is not local to the current client",
);

requireMatch(
  "desktopSetup",
  /if\s*\(!desktopAvailable\s*\|\|\s*!localChecksReady/u,
  "normal website rendering can reach desktop browser-auth startup",
);
requireMatch(
  "desktopSetup",
  /restoreBrowserAuthVault\(\)\s*\?\?\s*await beginBrowserAuth\(\{\s*locale\s*\}\)/u,
  "explicit edition vault restore and locale-only startup are not preserved",
);
requireMatch(
  "desktopSetup",
  /if\s*\(sessionIssued\)\s*\{\s*await clearBrowserAuthVault\(\)\.catch/u,
  "a refused desktop session is not removed from the edition vault",
);
rejectMatch(
  "desktopSetup",
  /beginBrowserAuth\([\s\S]{0,160}(supabaseUrl|publishableKey)/u,
  "desktop auth request must not contain Supabase configuration",
);

requireMatch(
  "websiteAuth",
  /source:\s*"website"/u,
  "website account links lost their source identity",
);
requireMatch(
  "websiteAuth",
  /SAFE_WEBSITE_AUTH_RETURN_PATHS\.has\(candidate\)/u,
  "website account return path is not allowlisted",
);
rejectMatch(
  "websiteAuth",
  /redirectTo|callbackUrl|https?:\/\//u,
  "website account links must not accept an arbitrary callback origin",
);
requireMatch(
  "sensitiveOrigin",
  /parsed\.username\s*\|\|\s*parsed\.password/u,
  "credential-bearing origins are not rejected",
);
requireMatch(
  "sensitiveOrigin",
  /parsed\.protocol\s*===\s*"http:"\s*&&\s*isLoopbackHost/u,
  "HTTP sensitive actions are not restricted to loopback",
);

const fingerprints = Object.fromEntries(
  Object.entries(sources).map(([name, source]) => [
    files[name],
    createHash("sha256").update(source, "utf8").digest("hex"),
  ]),
);

console.log(JSON.stringify({
  schemaVersion: 1,
  protocol: "desktop-browser-auth-pkce-v1",
  editions: ["universal", "sim", "lab", "field"],
  websiteSource: "website",
  checks: checkCount,
  fingerprints,
}, null, 2));
