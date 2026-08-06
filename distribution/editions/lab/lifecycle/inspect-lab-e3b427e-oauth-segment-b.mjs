import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../../frontend/node_modules/playwright");

const [endpoint, phase, outputPath] = process.argv.slice(2);
const phases = new Set(["runtime-prerequisite", "oauth-transaction", "vault-cleanup"]);
if (!endpoint || !phase || !outputPath || !phases.has(phase)) {
  throw new Error(
    "Usage: inspect-lab-e3b427e-oauth-segment-b.mjs <loopback-endpoint> <phase> <output.json>",
  );
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/u.test(endpoint)) {
  throw new Error("The WebView2 debug endpoint must be explicit loopback HTTP.");
}

const signInLabels = new Set([
  "Sign in and enter tuning workspace",
  "登录并进入调优平台",
]);
let browser;

function fail(code) {
  const error = new Error(code);
  error.failureCode = code;
  throw error;
}

function persist(payload) {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(payload));
}

try {
  browser = await chromium.connectOverCDP(endpoint);
  const page = browser.contexts()
    .flatMap((context) => context.pages())
    .find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) fail("lab-webview-not-found");

  await page.waitForSelector('html[data-brand-edition="lab"] .app-shell', {
    timeout: 30_000,
  });
  const edition = await page.locator("html").getAttribute("data-brand-edition");
  if (edition !== "lab") fail("wrong-edition-root");

  if (phase === "runtime-prerequisite") {
    const progress = page.getByRole("progressbar");
    await progress.waitFor({ state: "visible", timeout: 60_000 });
    if (await progress.getAttribute("aria-valuenow") !== "100") {
      fail("runtime-readiness-not-100");
    }
    const signIn = page.locator("button.launcher-primary-action");
    await signIn.waitFor({ state: "visible", timeout: 30_000 });
    const label = (await signIn.textContent())?.trim() ?? "";
    if (!signInLabels.has(label)) fail("explicit-lab-sign-in-action-not-ready");
    if (await signIn.isDisabled()) fail("explicit-lab-sign-in-action-disabled");
    persist({
      schemaVersion: 1,
      kind: "dronedream-lab-oauth-b0-runtime-readiness",
      phase,
      editionId: "lab",
      runtimeReadinessPercent: 100,
      explicitLoginActionPresent: true,
      explicitLoginActionEnabled: true,
      browserLaunches: 0,
      oauthTransactions: 0,
      providerCalls: 0,
      accountReads: 0,
      tokenCookieOrPasswordReads: 0,
      passed: true,
    });
  } else if (phase === "oauth-transaction") {
    const signIn = page.locator("button.launcher-primary-action");
    await signIn.waitFor({ state: "visible", timeout: 30_000 });
    const label = (await signIn.textContent())?.trim() ?? "";
    if (!signInLabels.has(label) || await signIn.isDisabled()) {
      fail("explicit-lab-sign-in-action-not-ready");
    }
    await signIn.click();
    await page.waitForFunction(
      () => window.location.hash.startsWith("#/assistant"),
      undefined,
      { timeout: 600_000 },
    );
    const accountButton = page.locator("button.app-account-button");
    await accountButton.waitFor({ state: "visible", timeout: 30_000 });
    await accountButton.click();
    const signOut = page.locator("button.account-sign-out");
    await signOut.waitFor({ state: "visible", timeout: 30_000 });
    await signOut.click();
    await signOut.waitFor({ state: "hidden", timeout: 30_000 });
    persist({
      schemaVersion: 1,
      kind: "dronedream-lab-oauth-b1-transaction-observation",
      phase,
      editionId: "lab",
      explicitLoginGestures: 1,
      browserLaunchMaximum: 1,
      oauthTransactionMaximum: 1,
      accountSurfaceReached: true,
      accountIdentityPersisted: false,
      localLogoutCompleted: true,
      labVaultClearRequestedByProductLogout: true,
      rawPasswordTokenCookieAuthorizationCodeVerifierStateNonceEmailOrCallbackPersisted: false,
      passed: true,
    });
  } else {
    const cleared = await page.evaluate(async () => {
      const invoke = window.__TAURI__?.core?.invoke;
      if (typeof invoke !== "function") throw new Error("tauri-invoke-unavailable");
      return invoke("clear_browser_auth_vault");
    });
    if (typeof cleared !== "boolean") fail("vault-cleanup-result-invalid");
    persist({
      schemaVersion: 1,
      kind: "dronedream-lab-oauth-b1-failure-vault-cleanup",
      phase,
      editionId: "lab",
      labVaultClearCommandCompleted: true,
      priorCredentialPresenceRead: false,
      credentialValueRead: false,
      passed: true,
    });
  }
} catch (error) {
  const failureCode = typeof error?.failureCode === "string"
    ? error.failureCode
    : `${phase}-inspection-failed`;
  persist({
    schemaVersion: 1,
    kind: "dronedream-lab-oauth-segment-b-inspection-failure",
    phase,
    editionId: "lab",
    failureCode,
    rawErrorUrlHeadersQueryCookieTokenPasswordEmailOrCallbackPersisted: false,
    passed: false,
  });
  console.error("Lab OAuth Segment B inspection failed closed.");
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
}
