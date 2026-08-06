import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

import {
  classifyRequest,
  requestDiagnosticsEvidence,
} from "./lab-request-origin-diagnostics.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../../frontend/node_modules/playwright");
const { PNG } = require("../../../../frontend/node_modules/pngjs");

const [endpoint, phase, outputPath] = process.argv.slice(2);
if (!endpoint || !phase || !outputPath) {
  throw new Error(
    "Usage: inspect-lab-e3b427e-live-webview2.mjs <endpoint> <phase> <output.json>",
  );
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(endpoint)) {
  throw new Error("The WebView2 debug endpoint must be an explicit loopback URL.");
}
if (!/^(fresh|overlay)$/.test(phase)) {
  throw new Error("The phase must be fresh or overlay.");
}

const LAB_GRADIENT = ["#A7E84A", "#20C77A", "#087E69"];
const LAB_APP_SHELL_SELECTOR = 'html[data-brand-edition="lab"] .app-shell';
const observedRequests = [];
const forbiddenAuthRequests = [];
const forbiddenProviderRequests = [];
const requestDiagnosticsPath = resolve(
  dirname(outputPath),
  `${phase}-request-diagnostics.json`,
);
let browser;

function recordRequest(rawUrl, metadata = {}) {
  const record = classifyRequest(rawUrl, {
    cdpEndpoint: endpoint,
    ...metadata,
  });
  observedRequests.push(record);
  if (record.authSensitive) forbiddenAuthRequests.push(record);
  if (record.decision === "deny") forbiddenProviderRequests.push(record);
}

function persistRequestDiagnostics(status, failureClass = null) {
  const evidence = requestDiagnosticsEvidence(observedRequests, {
    phase,
    status,
    failureClass,
  });
  mkdirSync(dirname(requestDiagnosticsPath), { recursive: true });
  writeFileSync(requestDiagnosticsPath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  return evidence;
}

function pngStats(buffer) {
  const image = PNG.sync.read(buffer);
  const colors = new Set();
  let nonTransparentPixels = 0;
  let nonBlackPixels = 0;
  for (let offset = 0; offset < image.data.length; offset += 4) {
    const red = image.data[offset];
    const green = image.data[offset + 1];
    const blue = image.data[offset + 2];
    const alpha = image.data[offset + 3];
    if (alpha === 0) continue;
    nonTransparentPixels += 1;
    if (red !== 0 || green !== 0 || blue !== 0) nonBlackPixels += 1;
    if (colors.size <= 4096) colors.add(`${red},${green},${blue},${alpha}`);
  }
  return {
    width: image.width,
    height: image.height,
    nonTransparentPixels,
    nonBlackPixels,
    uniqueColorCount: colors.size,
  };
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

try {
  browser = await chromium.connectOverCDP(endpoint);
  const contexts = browser.contexts();
  const pages = contexts.flatMap((context) => context.pages());
  const page = pages.find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) throw new Error("No inspectable DroneDream WebView2 page was found.");

  page.on("request", (request) => recordRequest(request.url(), {
    resourceType: request.resourceType(),
    observationSource: "playwright-request",
    isNavigationRequest: request.isNavigationRequest(),
  }));
  const priorResourceUrls = await page.evaluate(() =>
    performance.getEntriesByType("resource").map((entry) => ({
      name: entry.name,
      initiatorType: entry.initiatorType,
    })),
  );
  for (const resource of priorResourceUrls) {
    recordRequest(resource.name, {
      resourceType: resource.initiatorType,
      observationSource: "performance-resource",
    });
  }

  await page.waitForSelector(LAB_APP_SHELL_SELECTOR, {
    state: "visible",
    timeout: 30_000,
  });
  await page.waitForTimeout(1_000);

  const rootContract = await page.locator("html").evaluate((root) => {
    const styles = getComputedStyle(root);
    return {
      brandEdition: root.dataset.brandEdition,
      presentationOnly: root.dataset.themePresentationOnly === "true",
      grantsHardwareAuthority: root.dataset.themeGrantsHardwareAuthority === "true",
      gradientStops: [
        styles.getPropertyValue("--dd-brand-start").trim().toUpperCase(),
        styles.getPropertyValue("--dd-brand-middle").trim().toUpperCase(),
        styles.getPropertyValue("--dd-brand-end").trim().toUpperCase(),
      ],
    };
  });
  if (rootContract.brandEdition !== "lab") {
    throw new Error(`Unexpected live theme edition: ${rootContract.brandEdition}`);
  }
  if (!rootContract.presentationOnly || rootContract.grantsHardwareAuthority) {
    throw new Error("The live Lab theme did not remain presentation-only and authority-false.");
  }
  if (rootContract.gradientStops.join(",") !== LAB_GRADIENT.join(",")) {
    throw new Error(`Unexpected live Lab gradient: ${rootContract.gradientStops.join(",")}`);
  }

  const scene = page.locator('.drone-launch-scene[data-theme-edition="lab"]').first();
  await scene.waitFor({ state: "visible", timeout: 10_000 });
  const sceneContract = await scene.evaluate((element) => ({
    primary: element.dataset.themePrimary?.toUpperCase(),
    secondary: element.dataset.themeSecondary?.toUpperCase(),
    tertiary: element.dataset.themeTertiary?.toUpperCase(),
    grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority === "true",
  }));
  if (
    [sceneContract.primary, sceneContract.secondary, sceneContract.tertiary].join(",") !==
      LAB_GRADIENT.join(",") ||
    sceneContract.grantsHardwareAuthority
  ) {
    throw new Error("The live 3D scene is not bound to the authority-false Lab palette.");
  }
  const canvas = scene.locator("canvas.drone-launch-canvas").first();
  await canvas.waitFor({ state: "visible", timeout: 10_000 });
  const canvasBox = await canvas.boundingBox();
  if (!canvasBox || canvasBox.width < 32 || canvasBox.height < 32) {
    throw new Error("The live Lab 3D canvas has no stable rendered dimensions.");
  }
  const canvasBefore = await canvas.screenshot();
  await page.mouse.move(
    canvasBox.x + canvasBox.width * 0.2,
    canvasBox.y + canvasBox.height * 0.25,
  );
  await page.waitForTimeout(900);
  const canvasAfter = await canvas.screenshot();
  const beforeStats = pngStats(canvasBefore);
  const afterStats = pngStats(canvasAfter);
  const beforeSha256 = sha256(canvasBefore);
  const afterSha256 = sha256(canvasAfter);
  if (
    beforeStats.nonTransparentPixels === 0 ||
    beforeStats.nonBlackPixels === 0 ||
    beforeStats.uniqueColorCount < 16 ||
    afterStats.uniqueColorCount < 16
  ) {
    throw new Error("The live Lab 3D canvas was blank or visually degenerate.");
  }
  if (beforeSha256 === afterSha256) {
    throw new Error("The live Lab 3D scene did not respond between observed frames.");
  }

  const initialLocale = await page.locator("html").getAttribute("lang");
  if (initialLocale !== "en" && initialLocale !== "zh-CN") {
    throw new Error(`Unexpected initial Lab locale: ${initialLocale}`);
  }

  const settingsButton = page.locator('button[aria-haspopup="dialog"]').first();
  await settingsButton.click();
  const dialog = page.locator(
    '[role="dialog"][data-brand-edition="lab"][data-presentation-only="true"]' +
      '[data-grants-hardware-authority="false"]',
  ).first();
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

  const settings = await dialog.evaluate((element) => {
    const panels = element.querySelector(".launcher-settings-panels");
    if (!(panels instanceof HTMLElement)) throw new Error("Settings panel container missing.");
    return {
      dialogClientHeight: element.clientHeight,
      dialogScrollHeight: element.scrollHeight,
      panelsClientHeight: panels.clientHeight,
      panelsScrollHeight: panels.scrollHeight,
      singleScreenNoVerticalScroll:
        element.scrollHeight <= element.clientHeight + 1 &&
        panels.scrollHeight <= panels.clientHeight + 1,
      presentationOnly: element.dataset.presentationOnly === "true",
      grantsHardwareAuthority: element.dataset.grantsHardwareAuthority === "true",
    };
  });
  if (!settings.singleScreenNoVerticalScroll) {
    throw new Error("The live Lab Settings surface has vertical overflow.");
  }
  if (!settings.presentationOnly || settings.grantsHardwareAuthority) {
    throw new Error("The live Lab Settings surface did not remain authority-false.");
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

  const storage = await page.evaluate(() => ({
    local: Object.keys(window.localStorage).sort(),
    session: Object.keys(window.sessionStorage).sort(),
  }));
  const authStorageKeys = [...storage.local, ...storage.session].filter((key) =>
    /auth|oauth|token|session/i.test(key),
  );
  if (authStorageKeys.length !== 0) {
    throw new Error("Segment A found forbidden auth/session storage keys.");
  }

  await page.waitForTimeout(500);
  if (forbiddenAuthRequests.length !== 0) {
    throw new Error("Segment A observed a forbidden auth, OAuth, authorize, token, or session request.");
  }
  if (forbiddenProviderRequests.length !== 0) {
    throw new Error("Segment A observed a forbidden non-local provider request.");
  }

  const requestDiagnostics = persistRequestDiagnostics("passed");

  const screenshotPath = resolve(dirname(outputPath), `${phase}-lab-webview2.png`);
  mkdirSync(dirname(outputPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: false });

  const result = {
    schemaVersion: 1,
    phase,
    cdpOrigin: classifyRequest(endpoint, {
      cdpEndpoint: endpoint,
      resourceType: "document",
      observationSource: "playwright-request",
    }),
    pageLocation: classifyRequest(page.url(), {
      cdpEndpoint: endpoint,
      resourceType: "document",
      observationSource: "playwright-request",
      isNavigationRequest: true,
    }),
    initialLocale,
    finalLocale: targetLocale,
    languageTransitionCount: 1,
    languageSurfaceAssertionCount: 2,
    initialDialogTitle,
    finalDialogTitle,
    brand,
    settings,
    theme: rootContract,
    threeD: {
      ...sceneContract,
      rendered: true,
      responded: true,
      beforeSha256,
      afterSha256,
      beforeStats,
      afterStats,
    },
    webView2: {
      provider: "existing-system-webview2-runtime",
      existingRuntimeReadOnly: true,
      installRepairOrUpdateCount: 0,
    },
    storageKeyCounts: {
      local: storage.local.length,
      session: storage.session.length,
    },
    authStorageKeyCount: 0,
    requestDiagnosticsPath,
    observedRequestCount: requestDiagnostics.observedCount,
    forbiddenAuthRequestCount: 0,
    forbiddenProviderRequestCount: 0,
    browserLaunchCount: 0,
    oauthBoundaryCheckCount: 0,
    accountReadCount: 0,
    providerTokenExchangeCount: 0,
    screenshotPath,
    passed: true,
  };
  writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result));
} catch (error) {
  const failureClass = forbiddenAuthRequests.length > 0
    ? "forbidden-auth-sensitive-request"
    : forbiddenProviderRequests.length > 0
      ? "forbidden-external-or-unknown-request"
      : "live-inspector-assertion-failed";
  persistRequestDiagnostics("failed", failureClass);
  throw error;
} finally {
  if (browser) await browser.close();
}
