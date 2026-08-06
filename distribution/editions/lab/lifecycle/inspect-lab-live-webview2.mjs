import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../../frontend/node_modules/playwright");

const [endpoint, phase, outputPath] = process.argv.slice(2);
if (!endpoint || !phase || !outputPath) {
  throw new Error("Usage: inspect-lab-live-webview2.mjs <endpoint> <phase> <output.json>");
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(endpoint)) {
  throw new Error("The WebView2 debug endpoint must be an explicit loopback URL.");
}
if (!/^(fresh|overlay)$/.test(phase)) {
  throw new Error("The phase must be fresh or overlay.");
}

const authPattern = /(?:\/auth\/v1\/|oauth|authorize|token)/i;
const observedRequests = [];
const blockedAuthRequests = [];
let browser;

try {
  browser = await chromium.connectOverCDP(endpoint);
  const contexts = browser.contexts();
  const pages = contexts.flatMap((context) => context.pages());
  const page = pages.find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) throw new Error("No inspectable DroneDream WebView2 page was found.");

  page.on("request", (request) => {
    const url = request.url();
    observedRequests.push(url);
    if (authPattern.test(url)) blockedAuthRequests.push(url);
  });

  await page.waitForSelector('.app-shell[data-brand-edition="lab"]', {
    state: "visible",
    timeout: 30_000,
  });
  await page.waitForTimeout(1_000);

  const initialLocale = await page.locator("html").getAttribute("lang");
  if (initialLocale !== "en" && initialLocale !== "zh-CN") {
    throw new Error(`Unexpected initial Lab locale: ${initialLocale}`);
  }

  const settingsButton = page.locator('button[aria-haspopup="dialog"]').first();
  await settingsButton.click();
  const dialog = page.locator('[role="dialog"]').first();
  await dialog.waitFor({ state: "visible", timeout: 10_000 });
  const initialDialogTitle = (await dialog.locator("h2").textContent())?.trim() ?? "";

  const targetLocale = initialLocale === "en" ? "zh-CN" : "en";
  const languageButtons = dialog.locator(".launcher-language-options button");
  if ((await languageButtons.count()) !== 2) {
    throw new Error("The Lab settings dialog must expose exactly two language buttons.");
  }
  await languageButtons.nth(targetLocale === "en" ? 0 : 1).click();
  await page.waitForFunction(
    (expected) => document.documentElement.lang === expected,
    targetLocale,
    { timeout: 10_000 },
  );
  const finalDialogTitle = (await dialog.locator("h2").textContent())?.trim() ?? "";
  if (!initialDialogTitle || !finalDialogTitle || initialDialogTitle === finalDialogTitle) {
    throw new Error("The live Lab settings title did not change across EN/ZH.");
  }

  const brand = await page.locator('img.brand-lockup[data-brand-edition="lab"]').first().evaluate(
    (image) => ({
      complete: image.complete,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      sourceTail: new URL(image.currentSrc || image.src).pathname.split("/").pop(),
    }),
  );
  if (!brand.complete || brand.naturalWidth <= 0 || brand.naturalHeight <= 0) {
    throw new Error("The canonical Lab lockup did not render in WebView2.");
  }

  const storageKeys = await page.evaluate(() => Object.keys(window.localStorage).sort());
  const authStorageKeys = storageKeys.filter((key) => /auth|oauth|token|session/i.test(key));
  if (authStorageKeys.length !== 0) {
    throw new Error(`Segment A found forbidden auth/session storage keys: ${authStorageKeys.join(", ")}`);
  }

  await page.waitForTimeout(1_000);
  if (blockedAuthRequests.length !== 0) {
    throw new Error("Segment A observed a forbidden auth, OAuth, authorize, or token request.");
  }

  const screenshotPath = resolve(dirname(outputPath), `${phase}-lab-webview2.png`);
  mkdirSync(dirname(outputPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: false });

  const result = {
    schemaVersion: 1,
    phase,
    endpoint,
    pageUrl: page.url(),
    title: await page.title(),
    initialLocale,
    finalLocale: targetLocale,
    languageTransitionCount: 1,
    initialDialogTitle,
    finalDialogTitle,
    brand,
    storageKeys,
    authStorageKeyCount: 0,
    observedRequestCount: observedRequests.length,
    forbiddenAuthRequestCount: 0,
    browserLaunchCount: 0,
    oauthBoundaryCheckCount: 0,
    accountReadCount: 0,
    tokenReadOrExchangeCount: 0,
    screenshotPath,
    passed: true,
  };
  writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result));
} finally {
  if (browser) await browser.close();
}
