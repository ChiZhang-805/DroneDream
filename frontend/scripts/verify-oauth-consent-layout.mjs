import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
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

process.env.VITE_SUPABASE_URL = origin;
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "oauth-consent-layout-public-key";

const authorization = {
  authorization_id: "authorization-layout-check",
  redirect_uri: "http://127.0.0.1:49211/desktop-auth/sim/callback",
  scope: "openid email profile",
  client: {
    name: "DroneDream SIM Windows",
    uri: "https://getdronedream.com",
    logo_uri: "https://getdronedream.com/logo.svg",
  },
  user: {
    id: "docs-preview",
    email: "pilot@example.com",
  },
};

async function mockAuthorizationApi(page) {
  await page.route("**/auth/v1/oauth/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(authorization),
    });
  });
}

async function measure(page) {
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
    const lineCount = (selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const range = document.createRange();
      range.selectNodeContents(element);
      const tops = [];
      for (const box of range.getClientRects()) {
        if (box.width < 1 || box.height < 1) continue;
        if (!tops.some((top) => Math.abs(top - box.top) < 1)) tops.push(box.top);
      }
      return tops.length;
    };
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
      },
      card: rect(".site-oauth-card"),
      title: rect(".site-oauth-card h1"),
      product: rect(".site-oauth-product"),
      localReturn: rect(".site-oauth-local-return"),
      approve: rect(".site-oauth-actions .site-button-primary"),
      cancel: rect(".site-oauth-actions .site-button-ghost"),
      titleLines: lineCount(".site-oauth-card h1"),
      productNameLines: lineCount(".site-oauth-product strong"),
      productBodyLines: lineCount(".site-oauth-product p"),
      localReturnLines: lineCount(".site-oauth-local-return"),
      visibleButtons: document.querySelectorAll(".site-oauth-actions button").length,
    };
  });
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.site.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
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
    await context.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
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
    }, testCase.locale);
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const authRequests = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("request", (request) => {
      if (request.url().includes("/auth/v1/")) authRequests.push(request.url());
    });
    await mockAuthorizationApi(page);
    await page.goto(
      `${origin}/oauth/consent/?authorization_id=${authorization.authorization_id}&docsPreview=1`,
      { waitUntil: "networkidle" },
    );
    try {
      await page.locator(".site-oauth-actions .site-button-primary").waitFor({
        timeout: 8_000,
      });
    } catch (error) {
      await page.screenshot({
        path: path.join(outputRoot, `${testCase.id}-failure.png`),
        fullPage: true,
      });
      await writeFile(
        path.join(outputRoot, `${testCase.id}-failure.html`),
        await page.content(),
        "utf8",
      );
      const authStorage = await page.evaluate(() => Object.fromEntries(
        Object.keys(window.localStorage)
          .filter((key) => key.includes("auth"))
          .map((key) => [key, window.localStorage.getItem(key)]),
      ));
      const authClientState = await page.evaluate(async () => {
        const client = globalThis.__droneDreamSupabaseClient;
        if (!client) return null;
        const auth = client.auth;
        const session = await auth.getSession();
        return {
          storageKey: auth.storageKey,
          url: auth.url,
          ownKeys: Object.keys(auth),
          session: session.data.session,
          error: session.error?.message ?? null,
        };
      });
      process.stderr.write(`${JSON.stringify({
        consoleErrors,
        pageErrors,
        authRequests,
        authStorage,
        authClientState,
      })}\n`);
      throw error;
    }
    const metrics = await measure(page);
    await page.screenshot({
      path: path.join(outputRoot, `${testCase.id}.png`),
      fullPage: true,
    });

    assert(metrics.card, `${testCase.id}: consent card missing`);
    assert(metrics.approve && metrics.cancel, `${testCase.id}: consent actions missing`);
    assert.equal(metrics.visibleButtons, 2, `${testCase.id}: action count changed`);
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
    assert(metrics.card.top >= 96, `${testCase.id}: card overlaps the fixed header`);
    assert(metrics.card.bottom <= testCase.height, `${testCase.id}: card leaves the viewport`);
    assert(metrics.approve.bottom <= testCase.height, `${testCase.id}: approve action is below the fold`);
    assert.equal(metrics.titleLines, 1, `${testCase.id}: title wrapped`);
    assert.equal(metrics.productNameLines, 1, `${testCase.id}: product name wrapped`);
    assert.equal(metrics.productBodyLines, 1, `${testCase.id}: product request wrapped`);
    assert.equal(metrics.localReturnLines, 1, `${testCase.id}: local-return copy wrapped`);
    assert.equal(consoleErrors.length, 0, `${testCase.id}: browser console errors`);
    assert.equal(pageErrors.length, 0, `${testCase.id}: browser page errors`);
    results.push({ ...testCase, ...metrics, consoleErrors, pageErrors });
    await context.close();
  }

  const accountContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  });
  await accountContext.addInitScript(() => {
    window.localStorage.setItem("drone-dream:locale", "en");
  });
  const accountPage = await accountContext.newPage();
  const accountConsoleErrors = [];
  const accountPageErrors = [];
  accountPage.on("console", (message) => {
    if (message.type() === "error") accountConsoleErrors.push(message.text());
  });
  accountPage.on("pageerror", (error) => accountPageErrors.push(error.message));
  await accountPage.goto(
    `${origin}/oauth/consent/?authorization_id=${authorization.authorization_id}`,
    { waitUntil: "networkidle" },
  );
  const dialog = accountPage.locator(".site-auth-dialog");
  await dialog.waitFor();

  const captureAccountDialog = async (id, expectedTitle) => {
    await accountPage.getByRole("heading", { name: expectedTitle }).waitFor();
    const bounds = await dialog.boundingBox();
    assert(bounds, `${id}: account dialog missing`);
    assert(bounds.y >= 0, `${id}: account dialog starts above the viewport`);
    assert(bounds.y + bounds.height <= 900, `${id}: account dialog leaves the viewport`);
    await accountPage.screenshot({
      path: path.join(outputRoot, `${id}.png`),
      fullPage: true,
    });
    results.push({ id, dialog: bounds });
  };

  await captureAccountDialog("account-sign-in-1440x900", "Sign in");
  assert.equal(
    await accountPage.getByRole("button", { name: "Forgot your password? Reset it by email" }).count(),
    1,
    "Sign-in dialog lost the password reset entry",
  );
  assert.equal(
    await accountPage.getByRole("button", { name: "New to DroneDream? Register now" }).count(),
    1,
    "Sign-in dialog lost the registration entry",
  );

  await accountPage.getByRole("button", {
    name: "Forgot your password? Reset it by email",
  }).click();
  await captureAccountDialog("account-reset-request-1440x900", "Reset password");
  assert.equal(
    await accountPage.getByRole("button", { name: "Send reset link" }).count(),
    1,
    "Password reset request lost its email-link action",
  );

  await accountPage.getByRole("button", { name: "Already registered? Sign in" }).click();
  await accountPage.getByRole("button", { name: "New to DroneDream? Register now" }).click();
  await captureAccountDialog("account-register-1440x900", "Create account");
  assert.equal(
    await accountPage.getByRole("button", { name: "Create account" }).count(),
    1,
    "Registration dialog lost its account creation action",
  );
  assert.equal(accountConsoleErrors.length, 0, "Account dialogs emitted console errors");
  assert.equal(accountPageErrors.length, 0, "Account dialogs emitted page errors");
  await accountContext.close();

  await writeFile(
    path.join(outputRoot, "summary.json"),
    `${JSON.stringify({ passed: true, results }, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`OAuth consent layout verification passed: ${outputRoot}\n`);
} finally {
  await browser?.close();
  await server.close();
}
