import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildAuditStorageState,
  childProcessExited,
  collectFailureDiagnostic,
  createPageEventJournal,
  redactDiagnosticText,
} from "./oauth-consent-audit-diagnostics.mjs";

const [
  frontendRootRaw,
  siteDistRaw,
  outputRaw,
  productSource = "unknown",
  auditToolSource = "unknown",
] = process.argv.slice(2);
if (!frontendRootRaw || !siteDistRaw || !outputRaw) {
  console.error(
    "Usage: node audit-oauth-consent.mjs <frontend-root> <site-dist> <output-directory> "
      + "[product-source] [audit-tool-source]",
  );
  process.exit(2);
}

const frontendRoot = path.resolve(frontendRootRaw);
const siteDist = path.resolve(siteDistRaw);
const outputDirectory = path.resolve(outputRaw);
const auditToolPath = fileURLToPath(import.meta.url);
const auditToolDirectory = path.dirname(auditToolPath);
const screenshotDirectory = path.join(outputDirectory, "screenshots");
const failureScreenshotDirectory = path.join(outputDirectory, "failure-screenshots");
mkdirSync(screenshotDirectory, { recursive: true });
mkdirSync(failureScreenshotDirectory, { recursive: true });

const fixtureUrl = process.env.VITE_SUPABASE_URL?.trim() ?? "";
const fixtureKey = process.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim() ?? "";
const fixtureOrigin = fixtureUrl ? new URL(fixtureUrl).origin : "";
if (
  fixtureKey !== "local-preview-only"
  || !fixtureOrigin
  || new URL(fixtureOrigin).protocol !== "https:"
  || !new URL(fixtureOrigin).hostname.endsWith(".invalid")
) {
  throw new Error("OAuth consent audit requires a synthetic HTTPS .invalid Supabase fixture");
}
const authStorageKey = `sb-${new URL(fixtureOrigin).hostname.split(".")[0]}-auth-token`;
const expectedSiteDist = path.join(frontendRoot, "site-dist");
if (siteDist.toLowerCase() !== expectedSiteDist.toLowerCase()) {
  throw new Error("The audit may only consume the existing frontend/site-dist build output");
}

const require = createRequire(path.join(frontendRoot, "package.json"));
const { chromium, firefox } = require("playwright");
const authorizationId = "authorization_1234567890abcdef";
const oauthState = "state_1234567890abcdef";
const user = {
  id: "user-1",
  aud: "authenticated",
  role: "authenticated",
  email: "pilot@example.test",
  email_confirmed_at: "2026-01-01T00:00:00.000Z",
  phone: "",
  confirmed_at: "2026-01-01T00:00:00.000Z",
  last_sign_in_at: "2026-01-01T00:00:00.000Z",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: { display_name: "Fixture Pilot" },
  identities: [],
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
  is_anonymous: false,
};
const session = {
  access_token: "synthetic-access-token",
  token_type: "bearer",
  expires_in: 3_600,
  expires_at: Math.floor(Date.now() / 1_000) + 3_600,
  refresh_token: "synthetic-refresh-token",
  user,
};
const sim = {
  clientId: "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df",
  displayName: "DroneDream \u00b7 SIM",
  redirectUri: "http://127.0.0.1:49211/desktop-auth/sim/callback",
};
const labRedirectUri = "http://127.0.0.1:49212/desktop-auth/lab/callback";
const authorizationDetails = {
  authorization_id: authorizationId,
  redirect_uri: sim.redirectUri,
  client: {
    id: sim.clientId,
    name: sim.displayName,
    uri: "https://getdronedream.com/",
    logo_uri: "https://getdronedream.com/drone-favicon.png",
  },
  user: { id: user.id, email: user.email },
  scope: "openid email profile",
};
const copy = {
  en: {
    title: "Authorize this app",
    approve: "Authorize and return to app",
    deny: "Deny",
    invalid: "This authorization request is invalid or no longer available.",
    accountTitle: "Sign in",
  },
  "zh-CN": {
    title: "授权此应用",
    approve: "授权并返回应用",
    deny: "拒绝",
    invalid: "此授权请求无效或已不可用。",
    accountTitle: "登录",
  },
};
const browserSpecs = [
  {
    name: "edge",
    engine: chromium,
    executablePaths: [
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ],
  },
  { name: "firefox", engine: firefox, executablePaths: [] },
];
const locales = ["en", "zh-CN"];
const profiles = [
  { name: "desktop-1440", viewport: { width: 1_440, height: 900 } },
  { name: "mobile-390", viewport: { width: 390, height: 844 } },
];
const evidence = {
  schemaVersion: 2,
  productSource,
  auditToolSource,
  auditTool: {
    entry: {
      path: auditToolPath,
      sha256: sha256(readFileSync(auditToolPath)),
    },
    diagnostics: {
      path: path.join(auditToolDirectory, "oauth-consent-audit-diagnostics.mjs"),
      sha256: sha256(readFileSync(
        path.join(auditToolDirectory, "oauth-consent-audit-diagnostics.mjs"),
      )),
    },
  },
  startedAt: new Date().toISOString(),
  deploymentPerformed: false,
  realSupabaseContacted: false,
  buildCount: 0,
  auditCount: 1,
  fixture: {
    originClass: "https-.invalid",
    storageKey: authStorageKey,
    sessionValueRecorded: false,
  },
  matrix: [],
  invalidDetailCases: [],
  screenshots: [],
  failures: [],
  preview: {},
  status: "running",
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForPreview(url, child) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (childProcessExited(child)) {
      throw new Error(`Preview exited before readiness with code ${child.exitCode ?? "signal"}`);
    }
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status === 200) return;
    } catch {
      // The owned loopback listener is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for the local preview");
}

async function listenerClosed(port) {
  return await new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    socket.setTimeout(750);
    socket.once("connect", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(true));
    socket.once("timeout", () => {
      socket.destroy();
      resolve(true);
    });
  });
}

function launchOptions(spec) {
  if (!spec.executablePaths.length) return { headless: true };
  const executablePath = spec.executablePaths.find(existsSync);
  assert(executablePath, `${spec.name} executable was not found`);
  return { headless: true, executablePath };
}

async function installNetworkBoundary(context, baseUrl) {
  const permittedOrigins = new Set([
    new URL(baseUrl).origin,
    fixtureOrigin,
    "http://127.0.0.1:49211",
  ]);
  await context.route("**/*", async (route) => {
    let origin;
    try {
      origin = new URL(route.request().url()).origin;
    } catch {
      await route.abort("blockedbyclient");
      return;
    }
    if (permittedOrigins.has(origin)) {
      await route.fallback();
      return;
    }
    await route.abort("blockedbyclient");
  });
}

async function installFixtureRoutes(page, responseMode = "valid") {
  const calls = [];
  await page.route(`${fixtureOrigin}/**`, async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204 });
      return;
    }
    if (requestUrl.pathname === "/auth/v1/user") {
      calls.push({ kind: "user", method: request.method() });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(user) });
      return;
    }
    if (
      requestUrl.pathname === `/auth/v1/oauth/authorizations/${authorizationId}`
      && request.method() === "GET"
    ) {
      calls.push({ kind: "details", method: "GET" });
      const payload = responseMode === "invalid-details-unknown-client"
        ? { ...authorizationDetails, client: { ...authorizationDetails.client, id: "unknown-client" } }
        : responseMode === "invalid-details-cross-edition"
          ? { ...authorizationDetails, redirect_uri: labRedirectUri }
          : authorizationDetails;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
      return;
    }
    if (
      requestUrl.pathname === `/auth/v1/oauth/authorizations/${authorizationId}/consent`
      && request.method() === "POST"
    ) {
      let action;
      try {
        action = request.postDataJSON()?.action ?? "missing";
      } catch {
        action = "unparseable";
      }
      calls.push({ kind: "consent", method: "POST", action });
      let redirectUrl;
      if (responseMode === "invalid-redirect-external") {
        redirectUrl = `https://attacker.invalid/callback?code=synthetic-code&state=${oauthState}`;
      } else if (responseMode === "invalid-redirect-cross-edition") {
        redirectUrl = `${labRedirectUri}?code=synthetic-code&state=${oauthState}`;
      } else if (action === "approve") {
        redirectUrl = `${sim.redirectUri}?code=synthetic-code&state=${oauthState}`;
      } else {
        redirectUrl = `${sim.redirectUri}?error=access_denied&state=${oauthState}`;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ redirect_url: redirectUrl }),
      });
      return;
    }
    calls.push({ kind: "unexpected", method: request.method(), pathname: requestUrl.pathname });
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.route("http://127.0.0.1:49211/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><title>Fixture callback</title><main>Callback received</main>",
    });
  });
  return calls;
}

async function withCase({ browser, browserName, locale, profile, baseUrl, authenticated, caseId }, run) {
  const context = await browser.newContext({
    viewport: profile.viewport,
    colorScheme: "light",
    storageState: buildAuditStorageState({
      origin: baseUrl,
      locale,
      authStorageKey,
      session: authenticated ? session : null,
    }),
  });
  await installNetworkBoundary(context, baseUrl);
  const page = await context.newPage();
  await page.addInitScript(({ key }) => {
    window.__droneDreamOAuthAuditBootstrap = {
      sessionPresent: window.localStorage.getItem(key) !== null,
      locale: window.localStorage.getItem("drone-dream:locale"),
    };
  }, { key: authStorageKey });
  const journal = createPageEventJournal(page);
  let response = null;
  try {
    return await run({
      page,
      journal,
      setResponse(value) {
        response = value;
      },
    });
  } catch (error) {
    const diagnostic = await collectFailureDiagnostic({
      page,
      response,
      journal,
      screenshotDirectory: failureScreenshotDirectory,
      caseId,
      authStorageKey,
    });
    evidence.failures.push({
      browser: browserName,
      locale,
      profile: profile.name,
      authenticated,
      error: redactDiagnosticText(error instanceof Error ? error.message : error),
      diagnostic,
    });
    throw error;
  } finally {
    await context.close();
  }
}

async function openConsent(page, baseUrl) {
  return await page.goto(`${baseUrl}oauth/consent/?authorization_id=${authorizationId}`, {
    waitUntil: "domcontentloaded",
  });
}

async function assertConsent(page, locale) {
  await page.getByRole("heading", { name: copy[locale].title, exact: true })
    .waitFor({ state: "visible", timeout: 10_000 });
  await page.getByText(sim.displayName, { exact: true }).first()
    .waitFor({ state: "visible", timeout: 10_000 });
  const state = await page.evaluate(() => ({
    lang: document.documentElement.lang,
    sitePage: document.querySelector(".dd-site")?.getAttribute("data-page") ?? null,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    dialogCount: document.querySelectorAll("[role='dialog']").length,
  }));
  assert(state.lang === locale, `Document locale is ${state.lang}`);
  assert(state.sitePage === "oauth-consent", `Rendered site page is ${state.sitePage}`);
  assert(state.overflow <= 1, `Horizontal overflow is ${state.overflow}px`);
  assert(state.dialogCount === 0, "Unexpected dialog is rendered");
  return state;
}

function assertCleanPageJournal(journal) {
  const consoleErrors = journal.console.filter((event) => event.type === "error");
  assert(consoleErrors.length === 0, `Console errors: ${JSON.stringify(consoleErrors)}`);
  assert(journal.pageErrors.length === 0, `Page errors: ${JSON.stringify(journal.pageErrors)}`);
  assert(
    journal.requestFailures.length === 0,
    `Request failures: ${JSON.stringify(journal.requestFailures)}`,
  );
  assert(journal.dialogs.length === 0, `Browser dialogs: ${JSON.stringify(journal.dialogs)}`);
}

async function runAuthenticated(browser, spec, locale, profile, baseUrl) {
  const caseId = `${spec.name}-${locale}-${profile.name}-authenticated`;
  return await withCase({
    browser,
    browserName: spec.name,
    locale,
    profile,
    baseUrl,
    authenticated: true,
    caseId,
  }, async ({ page, journal, setResponse }) => {
    const calls = await installFixtureRoutes(page);
    const response = await openConsent(page, baseUrl);
    setResponse(response);
    assert(response?.status() === 200, `Direct consent route returned ${response?.status() ?? "no response"}`);
    const layout = await assertConsent(page, locale);
    await page.evaluate(() => document.fonts.ready);
    const screenshotPath = path.join(screenshotDirectory, `${spec.name}-${locale}-${profile.name}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false, animations: "disabled" });
    const screenshotBytes = await readFile(screenshotPath);
    evidence.screenshots.push({
      browser: spec.name,
      locale,
      profile: profile.name,
      path: screenshotPath,
      bytes: (await stat(screenshotPath)).size,
      sha256: sha256(screenshotBytes),
    });
    const decision = locale === "en" ? "approve" : "deny";
    const label = decision === "approve" ? copy[locale].approve : copy[locale].deny;
    const button = page.getByRole("button", { name: label, exact: true });
    await button.focus();
    await page.keyboard.press("Enter");
    await page.waitForURL((url) => url.origin === "http://127.0.0.1:49211", { timeout: 10_000 });
    const callback = new URL(page.url());
    assert(callback.searchParams.get("state") === oauthState, "Callback state was not preserved");
    assert(calls.filter((call) => call.kind === "details").length === 1, "Details call count is not one");
    assert(
      calls.filter((call) => call.kind === "consent" && call.action === decision).length === 1,
      "Consent decision call count is not one",
    );
    assert(calls.every((call) => call.kind !== "unexpected"), "Unexpected fixture request was made");
    assertCleanPageJournal(journal);
    return { decision, layout, callbackPath: callback.pathname };
  });
}

async function runUnauthenticated(browser, spec, locale, profile, baseUrl) {
  const caseId = `${spec.name}-${locale}-${profile.name}-unauthenticated`;
  return await withCase({
    browser,
    browserName: spec.name,
    locale,
    profile,
    baseUrl,
    authenticated: false,
    caseId,
  }, async ({ page, journal, setResponse }) => {
    const response = await openConsent(page, baseUrl);
    setResponse(response);
    assert(response?.status() === 200, "Direct unauthenticated consent route was not 200");
    await page.waitForURL((url) => url.pathname === "/account/", { timeout: 10_000 });
    const loginUrl = new URL(page.url());
    assert(loginUrl.searchParams.get("source") === "website", "Website source binding was lost");
    assert(loginUrl.searchParams.get("mode") === "sign-in", "Sign-in mode was lost");
    assert(
      loginUrl.searchParams.get("returnTo") === `/oauth/consent/?authorization_id=${authorizationId}`,
      "Exact OAuth return path was lost",
    );
    await page.getByRole("heading", { name: copy[locale].accountTitle, exact: true })
      .waitFor({ state: "visible", timeout: 10_000 });
    assertCleanPageJournal(journal);
    return { loginPath: loginUrl.pathname, returnTo: loginUrl.searchParams.get("returnTo") };
  });
}

async function runInvalidRedirect(browser, spec, locale, profile, baseUrl, mode) {
  const caseId = `${spec.name}-${locale}-${profile.name}-${mode}`;
  return await withCase({
    browser,
    browserName: spec.name,
    locale,
    profile,
    baseUrl,
    authenticated: true,
    caseId,
  }, async ({ page, journal, setResponse }) => {
    const calls = await installFixtureRoutes(page, mode);
    const response = await openConsent(page, baseUrl);
    setResponse(response);
    assert(response?.status() === 200, "Invalid redirect route was not 200");
    await assertConsent(page, locale);
    const approve = page.getByRole("button", { name: copy[locale].approve, exact: true });
    await approve.focus();
    await page.keyboard.press("Enter");
    const alert = page.getByRole("alert");
    await alert.waitFor({ state: "visible", timeout: 10_000 });
    assert((await alert.textContent())?.trim() === copy[locale].invalid, "Invalid redirect was not rejected");
    assert(new URL(page.url()).pathname === "/oauth/consent/", "Invalid redirect navigated away");
    assert(calls.filter((call) => call.kind === "consent").length === 1, "Decision call count is not one");
    assertCleanPageJournal(journal);
    return { mode, alertRole: true, remainedOnConsentRoute: true };
  });
}

async function runInvalidDetails(browser, spec, baseUrl, mode) {
  const profile = profiles[0];
  const caseId = `${spec.name}-en-${profile.name}-${mode}`;
  return await withCase({
    browser,
    browserName: spec.name,
    locale: "en",
    profile,
    baseUrl,
    authenticated: true,
    caseId,
  }, async ({ page, journal, setResponse }) => {
    const calls = await installFixtureRoutes(page, mode);
    const response = await openConsent(page, baseUrl);
    setResponse(response);
    assert(response?.status() === 200, "Invalid details route was not 200");
    const alert = page.getByRole("alert");
    await alert.waitFor({ state: "visible", timeout: 10_000 });
    assert((await alert.textContent())?.trim() === copy.en.invalid, "Invalid details were not rejected");
    assert(await page.getByRole("button", { name: copy.en.approve, exact: true }).count() === 0, "Approval remained available");
    assert(calls.filter((call) => call.kind === "details").length === 1, "Details call count is not one");
    assert(calls.filter((call) => call.kind === "consent").length === 0, "Invalid details reached consent");
    assertCleanPageJournal(journal);
    return { browser: spec.name, mode, decisionBlocked: true };
  });
}

let previewProcess = null;
let previewPort = null;
const previewOutput = [];
const browsers = [];
try {
  const consentHtml = path.join(siteDist, "oauth", "consent", "index.html");
  assert(existsSync(consentHtml), "The existing site-dist consent entry is missing");
  const html = readFileSync(consentHtml, "utf8");
  const entry = html.match(/src="([^"]*main-[^"]+\.js)"/u)?.[1];
  assert(entry, "The consent entry does not reference the built main module");
  const entryPath = path.join(siteDist, entry.replace(/^\//u, ""));
  const entrySource = readFileSync(entryPath, "utf8");
  assert(entrySource.includes("/oauth/consent"), "The built main module lacks the consent route");
  assert(entrySource.includes("Authorize this app"), "The built main module lacks consent copy");
  assert(entrySource.includes(fixtureOrigin), "The built module does not match the synthetic fixture origin");
  evidence.siteArtifact = {
    consentEntry: { path: consentHtml, sha256: sha256(Buffer.from(html)) },
    mainEntry: { path: entryPath, sha256: sha256(Buffer.from(entrySource)) },
  };

  previewPort = await freePort();
  const baseUrl = `http://127.0.0.1:${previewPort}/`;
  previewProcess = spawn(process.execPath, [
    path.join(frontendRoot, "node_modules", "vite", "bin", "vite.js"),
    "preview",
    "--config",
    path.join(frontendRoot, "vite.site.config.ts"),
    "--host",
    "127.0.0.1",
    "--port",
    String(previewPort),
    "--strictPort",
  ], {
    cwd: frontendRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  previewProcess.stdout.on("data", (chunk) => previewOutput.push(redactDiagnosticText(chunk, 2_000)));
  previewProcess.stderr.on("data", (chunk) => previewOutput.push(redactDiagnosticText(chunk, 2_000)));
  await waitForPreview(`${baseUrl}oauth/consent/`, previewProcess);
  evidence.preview = { host: "127.0.0.1", port: previewPort, started: true };

  for (const [browserIndex, spec] of browserSpecs.entries()) {
    const browser = await spec.engine.launch(launchOptions(spec));
    browsers.push(browser);
    for (const [localeIndex, locale] of locales.entries()) {
      for (const [profileIndex, profile] of profiles.entries()) {
        const authenticated = await runAuthenticated(browser, spec, locale, profile, baseUrl);
        const unauthenticated = await runUnauthenticated(browser, spec, locale, profile, baseUrl);
        const invalidMode = (browserIndex + localeIndex + profileIndex) % 2 === 0
          ? "invalid-redirect-external"
          : "invalid-redirect-cross-edition";
        const invalidRedirect = await runInvalidRedirect(
          browser,
          spec,
          locale,
          profile,
          baseUrl,
          invalidMode,
        );
        evidence.matrix.push({
          browser: spec.name,
          locale,
          profile: profile.name,
          viewport: profile.viewport,
          authenticated,
          unauthenticated,
          invalidRedirect,
          passed: true,
        });
      }
    }
    evidence.invalidDetailCases.push(await runInvalidDetails(
      browser,
      spec,
      baseUrl,
      browserIndex === 0
        ? "invalid-details-unknown-client"
        : "invalid-details-cross-edition",
    ));
  }
  evidence.status = "passed";
} catch (error) {
  evidence.status = "failed";
  evidence.error = redactDiagnosticText(error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  for (const browser of browsers.reverse()) {
    await browser.close().catch(() => undefined);
  }
  if (previewProcess && !childProcessExited(previewProcess)) {
    previewProcess.kill();
    await new Promise((resolve) => {
      const timeout = setTimeout(resolve, 5_000);
      previewProcess.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });
    });
  }
  evidence.finishedAt = new Date().toISOString();
  evidence.preview.exitCode = previewProcess?.exitCode ?? null;
  evidence.preview.signalCode = previewProcess?.signalCode ?? null;
  evidence.preview.processExited = childProcessExited(previewProcess);
  evidence.preview.listenerClosed = previewPort ? await listenerClosed(previewPort) : true;
  evidence.preview.output = redactDiagnosticText(previewOutput.join("\n"), 2_000);
  if (!evidence.preview.processExited || !evidence.preview.listenerClosed) {
    evidence.status = "failed";
    evidence.error = evidence.error ?? "Owned preview process or listener did not exit cleanly";
    process.exitCode = 1;
  }
  const evidencePath = path.join(outputDirectory, "oauth-consent-audit.json");
  writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  console.log(`EVIDENCE=${evidencePath}`);
  console.log(`STATUS=${evidence.status}`);
  console.log(`MATRIX=${evidence.matrix.length}`);
  console.log(`FAILURES=${evidence.failures.length}`);
  console.log(`LISTENER_CLOSED=${evidence.preview.listenerClosed}`);
}
