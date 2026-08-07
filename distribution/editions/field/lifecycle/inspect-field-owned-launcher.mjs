import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(resolve(process.cwd(), "frontend", "node_modules", "playwright"));

const [endpoint, phase, outputPath] = process.argv.slice(2);
if (!endpoint || !phase || !outputPath) {
  throw new Error("Usage: inspect-field-owned-launcher.mjs <endpoint> <fresh|overlay> <output.json>");
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
const forbiddenPattern = /(?:\/auth\/v1\/|oauth|authorize|token)/i;
const forbiddenNetwork = [];
const observedRequests = [];
let browser;

function sanitizedNetworkLocation(value) {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch {
    return "invalid-url";
  }
}

try {
  browser = await chromium.connectOverCDP(endpoint);
  const page = browser.contexts().flatMap((context) => context.pages())
    .find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) throw new Error("No inspectable Field WebView2 page was found.");

  page.on("request", (request) => {
    const url = request.url();
    observedRequests.push(url);
    if (forbiddenPattern.test(url)
        || (/^https?:/i.test(url)
          && !/^https?:\/\/(?:127\.0\.0\.1|tauri\.localhost|ipc\.localhost)(?::\d+)?\//i.test(url))) {
      forbiddenNetwork.push(url);
    }
  });

  await page.setViewportSize({ width: 390, height: 620 });
  const launcher = page.locator('.field-launcher[data-authority="false"]');
  await launcher.waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForFunction(() => (
    document.querySelector(".field-launcher")?.getAttribute("data-launch-ready") === "true"
    && document.querySelector('.launcher-progress-track[aria-valuenow="100"]') !== null
  ), undefined, { timeout: 30_000 });

  const shell = await page.evaluate((tokens) => {
    const root = document.querySelector(".field-launcher");
    const scene = document.querySelector(".drone-launch-scene");
    const themed = root?.closest('[data-brand-edition="field"]') ?? document.documentElement;
    if (!(root instanceof HTMLElement) || !(scene instanceof HTMLElement)) {
      throw new Error("Field launcher or DroneLaunchScene is missing.");
    }
    const style = getComputedStyle(themed);
    const theme = Object.fromEntries(
      Object.keys(tokens).map((name) => [name, style.getPropertyValue(name).trim().toLowerCase()]),
    );
    const progress = document.querySelector(".launcher-progress-track");
    const auth = document.querySelector(".field-auth-control-launcher");
    const authButton = auth?.querySelector("button");
    return {
      authority: root.dataset.authority,
      launchReady: root.dataset.launchReady,
      brandEdition: themed.getAttribute("data-brand-edition"),
      theme,
      progressNow: progress?.getAttribute("aria-valuenow"),
      progressText: document.querySelector(".launcher-progress-percent")?.textContent?.trim(),
      sceneThemeEdition: scene.dataset.themeEdition,
      sceneThemePrimary: scene.dataset.themePrimary,
      sceneThemeSecondary: scene.dataset.themeSecondary,
      sceneThemeTertiary: scene.dataset.themeTertiary,
      sceneGrantsAuthority: scene.dataset.themeGrantsHardwareAuthority,
      canvasCount: scene.querySelectorAll("canvas.drone-launch-canvas").length,
      fallbackCount: scene.querySelectorAll(".drone-launch-fallback").length,
      authAuthority: auth?.getAttribute("data-authority"),
      authButtonDisabled: authButton instanceof HTMLButtonElement ? authButton.disabled : null,
      authButtonLabel: authButton?.getAttribute("aria-label") ?? "",
      fieldAppCount: document.querySelectorAll(".field-app").length,
      bodyHasVerticalOverflow: document.documentElement.scrollHeight > innerHeight,
    };
  }, expectedTheme);

  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify({
    schemaVersion: 1,
    kind: "dronedream-field-installed-launcher-inspection",
    phase,
    stage: "preclassification",
    viewport: { width: 390, height: 620 },
    shell,
    passed: false,
  }, null, 2)}\n`, "utf8");

  if (shell.authority !== "false" || shell.launchReady !== "true"
      || shell.progressNow !== "100" || shell.progressText !== "100%") {
    throw new Error("Field launcher readiness contract drifted.");
  }
  if (shell.brandEdition !== "field") throw new Error("Field theme provider is not active.");
  for (const [name, value] of Object.entries(expectedTheme)) {
    if (shell.theme[name] !== value) throw new Error(`Field theme token drifted: ${name}`);
  }
  if (shell.sceneThemeEdition !== "field" || shell.sceneThemePrimary !== "#ffc247"
      || shell.sceneThemeSecondary !== "#ff754b" || shell.sceneThemeTertiary !== "#d746a5"
      || shell.sceneGrantsAuthority !== "false") {
    throw new Error("Field DroneLaunchScene theme or authority contract drifted.");
  }
  if (shell.canvasCount !== 1 || shell.fallbackCount !== 0) {
    throw new Error("The installed Field launcher did not render its live Three.js canvas.");
  }
  if (shell.authAuthority !== "false" || shell.authButtonDisabled !== false
      || shell.authButtonLabel.length === 0 || shell.fieldAppCount !== 0) {
    throw new Error("Field launcher authentication boundary drifted.");
  }
  if (shell.bodyHasVerticalOverflow) throw new Error("Field launcher vertically overflows 390x620.");

  const brand = await page.locator('img.brand-lockup[data-brand-edition="field"]').first()
    .evaluate((image) => ({
      complete: image.complete,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    }));
  if (!brand.complete || brand.naturalWidth !== 2581 || brand.naturalHeight !== 218) {
    throw new Error("Canonical centered Field lockup did not render at its exact natural dimensions.");
  }

  const scene = page.locator(".drone-launch-scene");
  const box = await scene.boundingBox();
  if (!box || box.width < 100 || box.height < 100) throw new Error("Field 3D scene has no stable viewport.");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForFunction(() => (
    document.querySelector(".drone-launch-scene")?.getAttribute("data-flight-state") === "starflight"
  ), undefined, { timeout: 5_000 });

  const initialLocale = await page.locator("html").getAttribute("lang");
  if (initialLocale !== "en" && initialLocale !== "zh-CN") throw new Error("Unexpected Field locale.");
  await page.locator("button.field-launcher-language").click();
  const finalLocale = initialLocale === "en" ? "zh-CN" : "en";
  await page.waitForFunction((locale) => document.documentElement.lang === locale, finalLocale);

  const existingExternalResources = await page.evaluate(() => (
    performance.getEntriesByType("resource")
      .map((entry) => entry.name)
      .filter((url) => /^https?:/i.test(url)
        && !/^https?:\/\/(?:127\.0\.0\.1|tauri\.localhost|ipc\.localhost)(?::\d+)?\//i.test(url))
  ));
  if (forbiddenNetwork.length !== 0 || existingExternalResources.length !== 0) {
    writeFileSync(outputPath, `${JSON.stringify({
      schemaVersion: 1,
      kind: "dronedream-field-installed-launcher-inspection",
      phase,
      stage: "external-network-classification",
      viewport: { width: 390, height: 620 },
      shell,
      networkDiagnostics: {
        observedAfterAttach: [...new Set(forbiddenNetwork.map(sanitizedNetworkLocation))],
        existingResources: [...new Set(existingExternalResources.map(sanitizedNetworkLocation))],
        queryAndFragmentPersisted: false,
      },
      passed: false,
    }, null, 2)}\n`, "utf8");
    throw new Error("Forbidden browser, OAuth, provider, or external network request observed.");
  }

  const screenshotPath = resolve(dirname(outputPath), `${phase}-field-launcher-390x620.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const result = {
    schemaVersion: 1,
    kind: "dronedream-field-installed-launcher-inspection",
    phase,
    endpoint,
    viewport: { width: 390, height: 620 },
    initialLocale,
    finalLocale,
    languageTransitionCount: 1,
    settingsInspections: [],
    shell,
    brand,
    live3dRequired: true,
    live3dObserved: true,
    live3dInteractionObserved: true,
    observedRequestCount: observedRequests.length,
    forbiddenRequestCount: 0,
    authButtonClicked: false,
    fieldAppEntered: false,
    screenshotPath,
    passed: true,
  };
  writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result));
} finally {
  if (browser) await browser.close();
}
