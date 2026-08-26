import assert from "node:assert/strict";
import { mkdir, realpath, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const dependencyRoot = await realpath(path.join(frontendRoot, "node_modules"))
  .catch(() => path.join(frontendRoot, "node_modules"));
const label = process.argv[2] || "current";
const outputRoot = path.join(
  repoRoot,
  "artifacts",
  "test-runs",
  "oauth-consent-layout",
  label,
);
const host = "127.0.0.1";
const port = 5197;
const origin = `http://${host}:${port}`;
const callbackPath = "/desktop-auth/autonomy/callback";
const callbackOrigin = "http://127.0.0.1:49214";
const callbackUrl = `${callbackOrigin}${callbackPath}?code=layout-code&state=layout-state`;

process.env.VITE_SUPABASE_URL = origin;
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "oauth-consent-layout-public-key";

const authorization = {
  authorization_id: "authorization-layout-check",
  redirect_uri: `${callbackOrigin}${callbackPath}`,
  scope: "openid email profile",
  client: {
    name: "DroneDream AGENT Windows",
    uri: "https://getdronedream.com",
    logo_uri: "https://getdronedream.com/logo.svg",
  },
  user: {
    id: "docs-preview",
    email: "pilot@example.com",
  },
};

async function mockDesktopAuthorization(page, consentRequests) {
  await page.route("**/auth/v1/oauth/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/consent")) {
      consentRequests.push({ method: request.method(), url: request.url() });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ redirect_url: callbackUrl }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(authorization),
    });
  });
}

async function measureAuthenticationPage(page) {
  return page.evaluate(() => {
    const rect = (selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const bounds = element.getBoundingClientRect();
      return {
        top: Number(bounds.top.toFixed(2)),
        right: Number(bounds.right.toFixed(2)),
        bottom: Number(bounds.bottom.toFixed(2)),
        left: Number(bounds.left.toFixed(2)),
        width: Number(bounds.width.toFixed(2)),
        height: Number(bounds.height.toFixed(2)),
      };
    };
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
      },
      dialog: rect(".site-auth-dialog"),
      brand: rect(".site-auth-brand .brand-lockup"),
      title: rect(".site-auth-dialog h2"),
      form: rect(".site-auth-form"),
      closeButtons: document.querySelectorAll(".site-auth-close").length,
    };
  });
}

function installLocale(context, locale) {
  return context.addInitScript((selectedLocale) => {
    window.localStorage.setItem("drone-dream:locale", selectedLocale);
  }, locale);
}

function installBrowserSession(context) {
  return context.addInitScript(() => {
    window.localStorage.setItem("dronedream-browser-auth:v1", JSON.stringify({
      access_token: "layout-access-token",
      refresh_token: "layout-refresh-token",
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      token_type: "bearer",
      user: {
        id: "docs-preview",
        aud: "authenticated",
        role: "authenticated",
        email: "pilot@example.com",
        user_metadata: {},
        app_metadata: {},
        created_at: "2026-08-18T00:00:00.000Z",
      },
    }));
  });
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.site.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: {
    host,
    port,
    strictPort: true,
    fs: { allow: [repoRoot, dependencyRoot] },
  },
});

let browser;
const results = [];
try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });

  for (const testCase of [
    { id: "desktop-en-1920x1080", locale: "en", width: 1920, height: 1080 },
    { id: "desktop-zh-1920x1080", locale: "zh-CN", width: 1920, height: 1080 },
    { id: "desktop-en-1440x900", locale: "en", width: 1440, height: 900 },
    { id: "wide-en-2560x1246", locale: "en", width: 2560, height: 1246 },
  ]) {
    const context = await browser.newContext({
      viewport: { width: testCase.width, height: testCase.height },
      colorScheme: "dark",
    });
    await installLocale(context, testCase.locale);
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(
      `${origin}/oauth/consent/?authorization_id=${authorization.authorization_id}`,
      { waitUntil: "networkidle" },
    );
    const dialog = page.locator(".site-auth-dialog");
    await dialog.waitFor();
    const expectedTitle = testCase.locale === "zh-CN" ? "登录" : "Sign in";
    await page.getByRole("heading", { name: expectedTitle }).waitFor();

    const metrics = await measureAuthenticationPage(page);
    await page.screenshot({
      path: path.join(outputRoot, `${testCase.id}.png`),
      fullPage: true,
    });

    assert(metrics.dialog, `${testCase.id}: authentication dialog missing`);
    assert(metrics.brand, `${testCase.id}: brand lockup missing`);
    assert(metrics.form, `${testCase.id}: authentication form missing`);
    assert.equal(metrics.closeButtons, 0, `${testCase.id}: OAuth page must not be closable`);
    assert.equal(
      metrics.document.scrollHeight,
      metrics.document.clientHeight,
      `${testCase.id}: page requires vertical scrolling`,
    );
    assert.equal(
      metrics.document.scrollWidth,
      metrics.document.clientWidth,
      `${testCase.id}: page requires horizontal scrolling`,
    );
    assert(metrics.dialog.top >= 24, `${testCase.id}: dialog leaves the top edge`);
    assert(
      metrics.dialog.bottom <= testCase.height - 24,
      `${testCase.id}: dialog leaves the bottom edge`,
    );
    assert.equal(
      await page.getByLabel(testCase.locale === "zh-CN" ? "邮箱地址" : "Email address").count(),
      1,
      `${testCase.id}: email field missing`,
    );
    assert.equal(
      await page.getByLabel(testCase.locale === "zh-CN" ? "密码" : "Password").count(),
      1,
      `${testCase.id}: password field missing`,
    );
    assert.equal(consoleErrors.length, 0, `${testCase.id}: browser console errors`);
    assert.equal(pageErrors.length, 0, `${testCase.id}: browser page errors`);
    results.push({ ...testCase, ...metrics, consoleErrors, pageErrors });
    await context.close();
  }

  const modesContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  });
  await installLocale(modesContext, "en");
  const modesPage = await modesContext.newPage();
  const modesConsoleErrors = [];
  const modesPageErrors = [];
  modesPage.on("console", (message) => {
    if (message.type() === "error") modesConsoleErrors.push(message.text());
  });
  modesPage.on("pageerror", (error) => modesPageErrors.push(error.message));
  await modesPage.goto(
    `${origin}/oauth/consent/?authorization_id=${authorization.authorization_id}`,
    { waitUntil: "networkidle" },
  );

  const captureMode = async (id, expectedTitle) => {
    await modesPage.getByRole("heading", { name: expectedTitle }).waitFor();
    const metrics = await measureAuthenticationPage(modesPage);
    assert(metrics.dialog, `${id}: authentication dialog missing`);
    assert(metrics.dialog.top >= 24, `${id}: dialog leaves the top edge`);
    assert(metrics.dialog.bottom <= 876, `${id}: dialog leaves the bottom edge`);
    await modesPage.screenshot({
      path: path.join(outputRoot, `${id}.png`),
      fullPage: true,
    });
    results.push({ id, ...metrics });
  };

  await modesPage.getByRole("button", { name: "Register" }).click();
  await captureMode("account-register-1440x900", "Create account");
  assert.equal(await modesPage.getByLabel("Confirm password").count(), 1);
  assert.equal(await modesPage.getByLabel("Verification code").count(), 1);

  await modesPage.getByRole("button", { name: "Back to sign in" }).click();
  await modesPage.getByRole("button", { name: "Forgot password" }).click();
  await captureMode("account-recovery-choice-1440x900", "Recover account");
  assert.equal(
    await modesPage.getByRole("button", { name: "Sign in with an email code" }).count(),
    1,
  );
  assert.equal(
    await modesPage.getByRole("button", { name: "Reset password with an email code" }).count(),
    1,
  );

  await modesPage.getByRole("button", { name: "Sign in with an email code" }).click();
  await captureMode("account-code-sign-in-1440x900", "Email code sign-in");
  assert.equal(await modesPage.getByLabel("Verification code").count(), 1);

  await modesPage.getByRole("button", { name: "Back to sign in" }).click();
  await modesPage.getByRole("button", { name: "Forgot password" }).click();
  await modesPage.getByRole("button", { name: "Reset password with an email code" }).click();
  await captureMode("account-code-reset-1440x900", "Reset password");
  assert.equal(await modesPage.getByLabel("Password", { exact: true }).count(), 1);
  assert.equal(await modesPage.getByLabel("Confirm password", { exact: true }).count(), 1);
  assert.equal(await modesPage.getByLabel("Verification code").count(), 1);
  assert.equal(modesConsoleErrors.length, 0, "Authentication modes emitted console errors");
  assert.equal(modesPageErrors.length, 0, "Authentication modes emitted page errors");
  await modesContext.close();

  const callbackContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  });
  await installLocale(callbackContext, "en");
  await installBrowserSession(callbackContext);
  const callbackPage = await callbackContext.newPage();
  const consentRequests = [];
  const callbackConsoleErrors = [];
  const callbackPageErrors = [];
  const callbackHttpErrors = [];
  callbackPage.on("console", (message) => {
    if (message.type() === "error") callbackConsoleErrors.push(message.text());
  });
  callbackPage.on("pageerror", (error) => callbackPageErrors.push(error.message));
  callbackPage.on("response", (response) => {
    if (response.status() >= 400) {
      callbackHttpErrors.push({ status: response.status(), url: response.url() });
    }
  });
  await callbackPage.route("**/functions/v1/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });
  await mockDesktopAuthorization(callbackPage, consentRequests);
  await callbackPage.route(`${callbackOrigin}${callbackPath}**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><title>Returned to AGENT</title><p id='returned'>Returned to AGENT</p>",
    });
  });
  await callbackPage.goto(
    `${origin}/oauth/consent/?authorization_id=${authorization.authorization_id}`,
  );
  await callbackPage.waitForURL(`${callbackOrigin}${callbackPath}**`);
  assert.equal(consentRequests.length, 1, "verified session was not approved exactly once");
  assert.equal(consentRequests[0].method, "POST", "approval did not use POST");
  assert.equal(await callbackPage.locator("#returned").count(), 1, "desktop callback did not load");
  assert.equal(
    callbackConsoleErrors.length,
    0,
    `automatic return emitted console errors: ${JSON.stringify({ callbackConsoleErrors, callbackHttpErrors })}`,
  );
  assert.equal(
    callbackPageErrors.length,
    0,
    `automatic return emitted page errors: ${JSON.stringify(callbackPageErrors)}`,
  );
  results.push({
    id: "authenticated-auto-return",
    callback: callbackPage.url(),
    consentRequests,
  });
  await callbackContext.close();

  await writeFile(
    path.join(outputRoot, "summary.json"),
    `${JSON.stringify({ passed: true, results }, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`OAuth browser authentication layout verification passed: ${outputRoot}\n`);
} finally {
  await browser?.close();
  await server.close();
}
