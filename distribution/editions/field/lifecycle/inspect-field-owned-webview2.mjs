import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../../frontend/node_modules/playwright");

const [endpoint, phase, outputPath] = process.argv.slice(2);
if (!endpoint || !phase || !outputPath) {
  throw new Error("Usage: inspect-field-owned-webview2.mjs <endpoint> <fresh|overlay> <output.json>");
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(endpoint)) {
  throw new Error("The WebView2 debug endpoint must be an explicit loopback URL.");
}
if (!/^(fresh|overlay)$/.test(phase)) throw new Error("Invalid lifecycle phase.");

const expectedTheme = {
  "--dd-brand-start": "#ffc247",
  "--dd-brand-middle": "#ff754b",
  "--dd-brand-end": "#d746a5",
  "--dd-brand-light-surface": "#fff8ef",
  "--dd-brand-dark-surface": "#28140d",
};
const authPattern = /(?:\/auth\/v1\/|oauth|authorize|token)/i;
const forbiddenNetwork = [];
const observedRequests = [];
let browser;

try {
  browser = await chromium.connectOverCDP(endpoint);
  const page = browser.contexts().flatMap((context) => context.pages())
    .find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) throw new Error("No inspectable Field WebView2 page was found.");

  page.on("request", (request) => {
    const url = request.url();
    observedRequests.push(url);
    if (authPattern.test(url) || /^https?:/i.test(url) && !/^https?:\/\/(?:127\.0\.0\.1|tauri\.localhost)(?::\d+)?\//i.test(url)) {
      forbiddenNetwork.push(url);
    }
  });

  await page.setViewportSize({ width: 390, height: 620 });
  await page.waitForSelector('.field-app[data-authority="false"]', { state: "visible", timeout: 30_000 });
  await page.waitForTimeout(500);

  const shell = await page.evaluate((tokens) => {
    const app = document.querySelector(".field-app");
    if (!(app instanceof HTMLElement)) throw new Error("Field app root missing");
    const themed = app.closest('[data-brand-edition="field"]') ?? document.documentElement;
    const style = getComputedStyle(themed);
    const theme = Object.fromEntries(Object.keys(tokens).map((name) => [name, style.getPropertyValue(name).trim().toLowerCase()]));
    return {
      authority: app.dataset.authority,
      validatedPackCount: app.dataset.validatedPackCount,
      quorum: app.dataset.quorum,
      brandEdition: themed.getAttribute("data-brand-edition"),
      theme,
      canvasCount: app.querySelectorAll("canvas").length,
      launchSceneCount: app.querySelectorAll(".drone-launch-scene").length,
    };
  }, expectedTheme);
  if (shell.authority !== "false" || shell.validatedPackCount !== "0" || shell.quorum !== "missing") {
    throw new Error("Field authority or zero-pack contract drifted.");
  }
  if (shell.brandEdition !== "field") throw new Error("Field theme provider is not active.");
  for (const [name, value] of Object.entries(expectedTheme)) {
    if (shell.theme[name] !== value) throw new Error(`Field theme token drifted: ${name}`);
  }
  if (shell.canvasCount !== 0 || shell.launchSceneCount !== 0) {
    throw new Error("Field currently defines no live Three.js surface; an unexpected scene appeared.");
  }

  const initialLocale = await page.locator("html").getAttribute("lang");
  if (initialLocale !== "en" && initialLocale !== "zh-CN") throw new Error("Unexpected Field locale.");
  await page.locator('button[aria-haspopup="dialog"]').first().click();
  const dialog = page.locator('.launcher-settings-dialog[data-settings-consumer="field-lightweight"]');
  await dialog.waitFor({ state: "visible", timeout: 10_000 });

  async function inspectSettings(locale) {
    return dialog.evaluate((element, expectedLocale) => {
      const panel = element.querySelector('.launcher-settings-panel:not([hidden])');
      if (!(panel instanceof HTMLElement)) throw new Error("Visible settings panel missing");
      const rect = element.getBoundingClientRect();
      return {
        locale: document.documentElement.lang,
        expectedLocale,
        dialogClientHeight: element.clientHeight,
        dialogScrollHeight: element.scrollHeight,
        panelClientHeight: panel.clientHeight,
        panelScrollHeight: panel.scrollHeight,
        withinViewport: rect.top >= 0 && rect.left >= 0 && rect.bottom <= innerHeight && rect.right <= innerWidth,
        bodyHasVerticalOverflow: document.documentElement.scrollHeight > innerHeight,
        presentationOnly: element.dataset.presentationOnly,
        grantsHardwareAuthority: element.dataset.grantsHardwareAuthority,
        safetyAuthority: element.querySelector('.field-settings-safety')?.getAttribute('data-authority') ?? null,
      };
    }, locale);
  }

  const languageButtons = dialog.locator(".field-settings-languages button");
  if (await languageButtons.count() !== 2) throw new Error("Field settings must expose EN and ZH.");
  const initialMetrics = await inspectSettings(initialLocale);
  const targetLocale = initialLocale === "en" ? "zh-CN" : "en";
  await languageButtons.nth(targetLocale === "en" ? 0 : 1).click();
  await page.waitForFunction((locale) => document.documentElement.lang === locale, targetLocale);
  const finalMetrics = await inspectSettings(targetLocale);
  for (const metrics of [initialMetrics, finalMetrics]) {
    if (metrics.locale !== metrics.expectedLocale || !metrics.withinViewport || metrics.bodyHasVerticalOverflow ||
        metrics.dialogClientHeight !== metrics.dialogScrollHeight || metrics.panelClientHeight !== metrics.panelScrollHeight ||
        metrics.presentationOnly !== "true" || metrics.grantsHardwareAuthority !== "false") {
      throw new Error(`Field settings single-screen contract failed for ${metrics.expectedLocale}.`);
    }
  }

  await dialog.getByRole("tab").nth(1).click();
  const safety = await page.evaluate(() => ({
    validatedCount: document.querySelector(".field-sidebar-status strong")?.textContent?.trim(),
    controlCount: document.querySelectorAll(".field-control-buttons button").length,
    disabledControlCount: document.querySelectorAll(".field-control-buttons button:disabled").length,
    deniedActionCount: document.querySelectorAll(".field-action-matrix > div").length,
    settingsAuthority: document.querySelector(".field-settings-safety")?.getAttribute("data-authority"),
    authStorageKeys: Object.keys(localStorage).filter((key) => /auth|oauth|token|session/i.test(key)),
  }));
  if (safety.validatedCount !== "0" || safety.controlCount !== 2 || safety.disabledControlCount !== 2 ||
      safety.deniedActionCount !== 3 || safety.settingsAuthority !== "false" || safety.authStorageKeys.length !== 0) {
    throw new Error("Field safety surface did not remain fail-closed.");
  }
  await page.waitForTimeout(500);
  if (forbiddenNetwork.length !== 0) throw new Error("Forbidden browser, OAuth, provider, or external network request observed.");

  const brand = await page.locator('img.brand-lockup[data-brand-edition="field"]').first().evaluate((image) => ({
    complete: image.complete,
    naturalWidth: image.naturalWidth,
    naturalHeight: image.naturalHeight,
  }));
  if (!brand.complete || brand.naturalWidth !== 2581 || brand.naturalHeight !== 218) {
    throw new Error("Canonical Field lockup did not render at its exact natural dimensions.");
  }

  const screenshotPath = resolve(dirname(outputPath), `${phase}-field-390x620.png`);
  mkdirSync(dirname(outputPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const result = {
    schemaVersion: 1,
    phase,
    endpoint,
    viewport: { width: 390, height: 620 },
    initialLocale,
    finalLocale: targetLocale,
    languageTransitionCount: 1,
    settingsInspections: [initialMetrics, finalMetrics],
    shell,
    safety,
    brand,
    live3dRequired: false,
    live3dObserved: false,
    shared3dSourceBindingRequired: true,
    observedRequestCount: observedRequests.length,
    forbiddenRequestCount: 0,
    screenshotPath,
    passed: true,
  };
  writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result));
} finally {
  if (browser) await browser.close();
}
