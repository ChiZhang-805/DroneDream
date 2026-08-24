import assert from "node:assert/strict";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const args = new Map(
  process.argv.slice(2).map((argument) => {
    const [key, ...value] = argument.split("=");
    return [key, value.join("=") || true];
  }),
);

const autonomySurfaces = Object.freeze([
  { id: "autonomy-overview", route: "/autonomy" },
  { id: "autonomy-aircraft", route: "/autonomy/aircraft" },
  { id: "autonomy-maps", route: "/autonomy/maps" },
  { id: "autonomy-plugins", route: "/autonomy/plugins" },
  { id: "autonomy-harness", route: "/autonomy/plugins/harness" },
  { id: "autonomy-live", route: "/autonomy/live", settleMilliseconds: 1_400 },
  { id: "autonomy-evidence", route: "/autonomy/evidence" },
]);

const launcherSurface = Object.freeze({
  id: "launcher",
  route: "/desktop/setup",
  expectedSelector: ".drone-launch-scene",
});

const shellSurfaces = Object.freeze([
  { id: "quick-settings", route: "/assistant", action: "quick-settings" },
  ...["general", "memory", "model", "course", "runtime"].map((tab) => ({
    id: `settings-${tab}`,
    route: "/assistant",
    action: `settings:${tab}`,
  })),
  { id: "account-menu", route: "/assistant", action: "account-menu" },
]);

const sharedStaticSurfaces = Object.freeze([
  { id: "assistant", route: "/assistant", expectedSelector: ".experiment-assistant-page" },
  { id: "jobs-new", route: "/jobs/new", action: "name-experiment" },
  { id: "dashboard", route: "/dashboard" },
  { id: "history", route: "/history" },
  { id: "scenarios", route: "/scenarios" },
  { id: "compare", route: "/compare" },
]);

const universalWorkspaceModes = Object.freeze([
  "universal",
  "sim",
  "lab",
  "field",
  "autonomy",
]);

const universalSharedSurfaces = Object.freeze(
  universalWorkspaceModes.flatMap((mode) => sharedStaticSurfaces.map((surface) => ({
    ...surface,
    id: mode === "universal" ? surface.id : `${mode}-${surface.id}`,
    universalMode: mode,
  }))),
);

const surfaceMatrix = Object.freeze({
  universal: Object.freeze([
    launcherSurface,
    ...universalSharedSurfaces,
    { id: "lab-workspace", route: "/lab", universalMode: "lab" },
    { id: "lab-hardware", route: "/lab/hardware", universalMode: "lab" },
    { id: "lab-validation", route: "/lab/validation", universalMode: "lab" },
    { id: "field-device", route: "/field/device", universalMode: "field" },
    { id: "field-tuning", route: "/field/tuning", universalMode: "field" },
    { id: "field-operations", route: "/field/operations", universalMode: "field" },
    ...autonomySurfaces.map((surface) => ({ ...surface, universalMode: "autonomy" })),
    ...shellSurfaces,
  ]),
  sim: Object.freeze([
    launcherSurface,
    ...sharedStaticSurfaces,
    ...autonomySurfaces,
    ...shellSurfaces,
  ]),
  lab: Object.freeze([
    launcherSurface,
    ...sharedStaticSurfaces,
    { id: "lab-workspace", route: "/lab" },
    { id: "lab-hardware", route: "/lab/hardware" },
    { id: "lab-validation", route: "/lab/validation" },
    ...autonomySurfaces,
    ...shellSurfaces,
  ]),
  field: Object.freeze([
    launcherSurface,
    ...sharedStaticSurfaces,
    { id: "field-device", route: "/field/device" },
    { id: "field-tuning", route: "/field/tuning" },
    { id: "field-operations", route: "/field/operations" },
    ...autonomySurfaces,
    ...shellSurfaces,
  ]),
  autonomy: Object.freeze([
    launcherSurface,
    ...sharedStaticSurfaces,
    ...autonomySurfaces,
    ...shellSurfaces,
  ]),
});

const dataDependentSurfaces = Object.freeze([
  {
    id: "job-detail",
    routeTemplate: "/jobs/:jobId",
    status: "skipped",
    reason: "requires a seeded job identifier and its matching backend record",
  },
  {
    id: "trial-detail",
    routeTemplate: "/trials/:trialId",
    status: "skipped",
    reason: "requires a seeded trial identifier and its matching backend record",
  },
]);

function required(name) {
  const value = args.get(name);
  if (!value || value === true) throw new Error(`Missing required argument ${name}`);
  return String(value);
}

function canonicalMatrix() {
  return {
    schemaVersion: 1,
    kind: "dronedream-five-edition-installed-surface-matrix",
    editions: Object.fromEntries(
      Object.entries(surfaceMatrix).map(([edition, surfaces]) => [
        edition,
        surfaces.map(({ settleMilliseconds, ...surface }) => ({
          ...surface,
          ...(settleMilliseconds ? { settleMilliseconds } : {}),
        })),
      ]),
    ),
    skippedDataDependentSurfaces: dataDependentSurfaces,
  };
}

if (args.has("--list-surfaces")) {
  process.stdout.write(`${JSON.stringify(canonicalMatrix(), null, 2)}\n`);
  process.exit(0);
}

const cdpEndpoint = required("--cdp-endpoint");
const edition = required("--edition");
const surfaceId = required("--surface");
const state = required("--state");
const locale = required("--locale");
const expectedEdition = required("--expected-edition");
const expectedDocumentTitle = required("--expected-document-title");
const outputPath = path.resolve(required("--output"));

assert(Object.hasOwn(surfaceMatrix, edition), `Unsupported edition: ${edition}`);
assert.equal(expectedEdition, edition, "Matrix edition and expected application edition must match");
assert(expectedDocumentTitle.trim().length > 0, "Expected document title must not be empty");
assert(state === "default" || state === "maximized", `Unsupported window state: ${state}`);
assert(locale === "en" || locale === "zh-CN", `Unsupported locale: ${locale}`);
assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP endpoint must remain loopback-only");

const surface = surfaceMatrix[edition].find((candidate) => candidate.id === surfaceId);
assert(surface, `Surface '${surfaceId}' is not part of the ${edition} matrix`);

async function atomicJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
    await rename(temporary, filePath);
  } finally {
    await rm(temporary, { force: true });
  }
}

function isInstalledAppUrl(value) {
  try {
    const url = new URL(value);
    return (url.protocol === "tauri:" && url.hostname === "localhost")
      || ((url.protocol === "http:" || url.protocol === "https:")
        && (url.hostname === "tauri.localhost" || url.hostname === "localhost"));
  } catch {
    return false;
  }
}

async function findAppPage(browser) {
  const contexts = browser.contexts();
  assert.equal(contexts.length, 1, "Expected exactly one installed-app WebView context");
  const pages = contexts[0].pages();
  const candidates = pages.filter((page) => isInstalledAppUrl(page.url()));
  assert.equal(
    candidates.length,
    1,
    `Expected exactly one canonical installed-app page; observed ${pages.map((page) => page.url()).join(", ")}`,
  );
  const [page] = candidates;
  await page.waitForFunction(
    (title) => document.title === title,
    expectedDocumentTitle,
    { timeout: 30_000 },
  );
  assert.equal(await page.title(), expectedDocumentTitle, "Installed-app document title mismatch");
  return page;
}

async function reloadAtSurface(page) {
  const universalMode = surface.universalMode ?? edition;
  await page.evaluate(({ nextLocale, nextMode, route }) => {
    window.localStorage.setItem("drone-dream:locale", nextLocale);
    window.localStorage.setItem("dronedream:universal-workspace:v2", nextMode);
    const next = new URL(window.location.href);
    next.hash = route;
    window.history.replaceState(null, "", next.href);
  }, { nextLocale: locale, nextMode: universalMode, route: surface.route });
  await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.waitForURL((url) => url.hash === `#${surface.route}`, { timeout: 30_000 });
  await page.waitForFunction(
    (expectedLocale) => document.documentElement.lang === expectedLocale,
    locale,
    { timeout: 30_000 },
  );
}

async function prepareSurface(page) {
  const expectedSelector = surface.expectedSelector
    ?? (surface.id === "launcher" ? ".drone-launch-scene" : "#main-content");
  await page.locator(expectedSelector).waitFor({ state: "visible", timeout: 30_000 });

  if (surface.id === "launcher") {
    await page.locator(".launcher-runtime-indicator.is-checked").waitFor({
      state: "visible",
      timeout: 120_000,
    });
  }

  if (surface.action === "name-experiment") {
    const nameDialog = page.locator(".wizard-name-modal");
    if (await nameDialog.isVisible()) {
      await nameDialog.locator("input").first().fill(
        `${edition}-${locale}-${state}-desktop-visual-parity`,
      );
      await nameDialog.locator('button[type="submit"]').click();
      await nameDialog.waitFor({ state: "hidden", timeout: 30_000 });
    }
  } else if (surface.action === "quick-settings" || surface.action?.startsWith("settings:")) {
    const settingsButton = page.locator(".app-header .launcher-settings-button:visible").first();
    await settingsButton.waitFor({ state: "visible", timeout: 30_000 });
    await settingsButton.click();
    const quickSettings = page.locator(".quick-settings-dialog");
    await quickSettings.waitFor({ state: "visible", timeout: 30_000 });
    if (surface.action.startsWith("settings:")) {
      await quickSettings.locator(".quick-settings-footer .btn-primary").click();
      const workspace = page.locator(".settings-workspace-host");
      await workspace.waitFor({
        state: "visible",
        timeout: 30_000,
      });
      const tabId = surface.action.slice("settings:".length);
      const tab = workspace.locator(`#settings-tab-${tabId}`);
      await tab.waitFor({ state: "visible", timeout: 30_000 });
      if (!await tab.isEnabled()) {
        return {
          skipped: true,
          reason: `requires an authenticated account; the '${tabId}' settings tab is disabled in the isolated profile`,
        };
      }
      await tab.click();
      await workspace.locator(`#settings-panel-${tabId}`).waitFor({
        state: "visible",
        timeout: 30_000,
      });
    }
  } else if (surface.action === "account-menu") {
    const accountButton = page.locator(".app-account-button:visible").first();
    await accountButton.waitFor({ state: "visible", timeout: 30_000 });
    await accountButton.click();
    await page.locator(".account-menu-popover").waitFor({ state: "visible", timeout: 30_000 });
  }

  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.waitForTimeout(surface.settleMilliseconds ?? 350);
  return { skipped: false };
}

async function collectMetrics(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const isVisible = (element) => {
      if (!(element instanceof Element)) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity) !== 0
        && rect.width > 0
        && rect.height > 0;
    };
    const normalizedText = (element) => (
      element.getAttribute("aria-label")
      || element.getAttribute("title")
      || element.textContent
      || element.id
      || element.tagName
    ).replace(/\s+/gu, " ").trim().slice(0, 180);
    const orderedText = (selector) => [...document.querySelectorAll(selector)]
      .filter(isVisible)
      .map(normalizedText)
      .filter(Boolean);
    const stableClassName = (element) => [...element.classList]
      .filter((name) => !/^(?:active|selected|checked|disabled|loading|pending|open|closed)$/u.test(name))
      .slice(0, 3)
      .join(".");
    const stableElementKey = (element) => {
      const identity = element.id
        || element.getAttribute("data-testid")
        || element.getAttribute("aria-label")
        || element.getAttribute("name")
        || stableClassName(element)
        || normalizedText(element);
      return `${element.tagName.toLowerCase()}:${String(identity).replace(/\s+/gu, " ").trim().slice(0, 120)}`;
    };
    const rectSnapshot = (rect) => ({
      left: Math.round(rect.left * 100) / 100,
      top: Math.round(rect.top * 100) / 100,
      right: Math.round(rect.right * 100) / 100,
      bottom: Math.round(rect.bottom * 100) / 100,
      width: Math.round(rect.width * 100) / 100,
      height: Math.round(rect.height * 100) / 100,
    });
    const intersects = (first, second) => first.right > second.left + 1
      && first.left < second.right - 1
      && first.bottom > second.top + 1
      && first.top < second.bottom - 1;
    const viewportRect = {
      left: 0,
      top: 0,
      right: window.innerWidth,
      bottom: window.innerHeight,
    };
    const overlay = [
      ...document.querySelectorAll(
        ".quick-settings-dialog, .settings-workspace-host, .account-menu-popover",
      ),
    ].find(isVisible);
    const sidebar = document.querySelector(".app-sidebar");
    const main = document.querySelector("#main-content, .launcher-main");
    const captureRoot = overlay ?? main ?? body;
    const primaryTitle = overlay?.querySelector("h1, h2, h3") ?? document.querySelector(
      "#main-content h1, .launcher-main h1, .assistant-hero-question, .state-title",
    );
    const titleRect = primaryTitle?.getBoundingClientRect();
    const titleStyle = primaryTitle ? getComputedStyle(primaryTitle) : null;
    const parsedLineHeight = titleStyle ? Number.parseFloat(titleStyle.lineHeight) : 0;
    const titleLineHeight = Number.isFinite(parsedLineHeight) && parsedLineHeight > 0
      ? parsedLineHeight
      : Number.parseFloat(titleStyle?.fontSize ?? "0") * 1.2;
    const overlayRect = overlay?.getBoundingClientRect();
    const visualElements = [
      ...captureRoot.querySelectorAll(
        "h1, h2, h3, button, input, select, textarea, a[href], summary, "
        + "[role='tab'], [role='menuitem'], [role='option']",
      ),
    ].filter((element, index, elements) => (
      isVisible(element)
      && intersects(element.getBoundingClientRect(), viewportRect)
      && elements.indexOf(element) === index
    ));
    const elementOccurrence = new Map();
    const describeElement = (element) => {
      const baseKey = stableElementKey(element);
      const occurrence = (elementOccurrence.get(baseKey) ?? 0) + 1;
      elementOccurrence.set(baseKey, occurrence);
      const parent = element.parentElement?.closest(
        "section, article, [role='region'], [role='tabpanel'], [role='dialog'], "
        + "[role='menu'], [class*='-card'], [class*='-panel']",
      );
      const rect = element.getBoundingClientRect();
      return {
        key: `${baseKey}#${occurrence}`,
        parent: parent ? stableElementKey(parent) : "root",
        rect: rectSnapshot(rect),
      };
    };
    const visualGeometry = visualElements.map(describeElement);
    const visualOrder = [...visualGeometry]
      .sort((first, second) => first.rect.top - second.rect.top
        || first.rect.left - second.rect.left
        || second.rect.width * second.rect.height - first.rect.width * first.rect.height)
      .map(({ key, parent }) => `${parent}>${key}`);
    const rowSource = [...visualGeometry].sort((first, second) => (
      first.rect.top - second.rect.top || first.rect.left - second.rect.left
    ));
    const visualRows = [];
    for (const descriptor of rowSource) {
      const current = visualRows.at(-1);
      if (!current || Math.abs(descriptor.rect.top - current.anchorTop) > 10) {
        visualRows.push({ anchorTop: descriptor.rect.top, items: [descriptor] });
      } else {
        current.items.push(descriptor);
      }
    }
    const visualTopology = {
      order: visualOrder,
      rows: visualRows.map((row) => row.items
        .sort((first, second) => first.rect.left - second.rect.left)
        .map(({ key, parent }) => `${parent}>${key}`)),
      columnCounts: visualRows.map((row) => row.items.length),
    };

    const moduleElements = [
      ...captureRoot.querySelectorAll(
        "section, article, [role='region'], [role='tabpanel'], [role='dialog'], "
        + "[role='menu'], [class*='-card'], [class*='-panel']",
      ),
    ].filter((element) => isVisible(element) && intersects(element.getBoundingClientRect(), viewportRect));
    const moduleOccurrences = new Map();
    const moduleGeometry = moduleElements.map((element) => {
      const baseKey = stableElementKey(element);
      const occurrence = (moduleOccurrences.get(baseKey) ?? 0) + 1;
      moduleOccurrences.set(baseKey, occurrence);
      const parent = element.parentElement?.closest(
        "section, article, [role='region'], [role='tabpanel'], [role='dialog'], "
        + "[role='menu'], [class*='-card'], [class*='-panel']",
      );
      return {
        key: `${baseKey}#${occurrence}`,
        parent: parent && captureRoot.contains(parent) ? stableElementKey(parent) : "root",
        rect: rectSnapshot(element.getBoundingClientRect()),
      };
    });
    const moduleTopology = {
      hierarchy: moduleGeometry.map(({ key, parent }) => `${parent}>${key}`),
      visualOrder: [...moduleGeometry]
        .sort((first, second) => first.rect.top - second.rect.top
          || first.rect.left - second.rect.left
          || second.rect.width * second.rect.height - first.rect.width * first.rect.height)
        .map(({ key, parent }) => `${parent}>${key}`),
    };

    const clippingSelector = [
      "h1", "h2", "h3", "h4", "h5", "h6", "button", "input", "select", "textarea",
      "a[href]", "summary", "table", "svg", "canvas", "[role='dialog']", "[role='region']",
      "[role='tabpanel']", "[role='menu']", "[role='table']", "[class*='-card']", "[class*='-panel']",
    ].join(", ");
    const clippingIssues = [];
    for (const element of captureRoot.querySelectorAll(clippingSelector)) {
      if (!isVisible(element)) continue;
      const rect = element.getBoundingClientRect();
      if (!intersects(rect, viewportRect)) continue;
      const label = stableElementKey(element);
      if (rect.left < -1 || rect.right > window.innerWidth + 1) {
        clippingIssues.push({ axis: "horizontal", boundary: "viewport", label, rect: rectSnapshot(rect) });
      }
      if (rect.top < -1 || rect.bottom > window.innerHeight + 1) {
        clippingIssues.push({ axis: "vertical", boundary: "viewport", label, rect: rectSnapshot(rect) });
      }
      let ancestor = element.parentElement;
      while (ancestor && ancestor !== captureRoot.parentElement) {
        const style = getComputedStyle(ancestor);
        const ancestorRect = ancestor.getBoundingClientRect();
        const overflowX = style.overflowX;
        const overflowY = style.overflowY;
        if (/(?:auto|scroll|hidden|clip)/u.test(overflowX)
          && intersects(rect, ancestorRect)
          && (rect.left < ancestorRect.left - 1 || rect.right > ancestorRect.right + 1)) {
          clippingIssues.push({
            axis: "horizontal",
            boundary: stableElementKey(ancestor),
            label,
            rect: rectSnapshot(rect),
          });
          break;
        }
        if (/(?:auto|scroll|hidden|clip)/u.test(overflowY)
          && intersects(rect, ancestorRect)
          && (rect.top < ancestorRect.top - 1 || rect.bottom > ancestorRect.bottom + 1)) {
          clippingIssues.push({
            axis: "vertical",
            boundary: stableElementKey(ancestor),
            label,
            rect: rectSnapshot(rect),
          });
          break;
        }
        ancestor = ancestor.parentElement;
      }
      if (element.matches("h1, h2, h3, h4, h5, h6, button, a[href], summary")
        && (element.scrollWidth > element.clientWidth + 1
          || element.scrollHeight > element.clientHeight + 1)) {
        clippingIssues.push({
          axis: element.scrollWidth > element.clientWidth + 1 ? "horizontal" : "vertical",
          boundary: "content-box",
          label,
          rect: rectSnapshot(rect),
        });
      }
    }
    const horizontalClipping = clippingIssues.filter(({ axis }) => axis === "horizontal");
    const verticalClipping = clippingIssues.filter(({ axis }) => axis === "vertical");

    const overlapIssues = [];
    for (let firstIndex = 0; firstIndex < visualElements.length; firstIndex += 1) {
      const first = visualElements[firstIndex];
      const firstDescriptor = visualGeometry[firstIndex];
      for (let secondIndex = firstIndex + 1; secondIndex < visualElements.length; secondIndex += 1) {
        const second = visualElements[secondIndex];
        const secondDescriptor = visualGeometry[secondIndex];
        if (first.contains(second) || second.contains(first)
          || firstDescriptor.parent !== secondDescriptor.parent) continue;
        const left = Math.max(firstDescriptor.rect.left, secondDescriptor.rect.left);
        const right = Math.min(firstDescriptor.rect.right, secondDescriptor.rect.right);
        const top = Math.max(firstDescriptor.rect.top, secondDescriptor.rect.top);
        const bottom = Math.min(firstDescriptor.rect.bottom, secondDescriptor.rect.bottom);
        const area = Math.max(0, right - left) * Math.max(0, bottom - top);
        const firstArea = firstDescriptor.rect.width * firstDescriptor.rect.height;
        const secondArea = secondDescriptor.rect.width * secondDescriptor.rect.height;
        if (area > 4 && area / Math.min(firstArea, secondArea) > 0.1) {
          overlapIssues.push({ first: firstDescriptor.key, second: secondDescriptor.key, area });
        }
      }
    }
    const mobileNavigationVisible = [
      ...document.querySelectorAll(".app-mobile-menu-button, .app-mobile-menu-panel"),
    ].some(isVisible);

    return {
      route: window.location.hash.replace(/^#/u, ""),
      documentTitle: document.title,
      brandEdition: root.dataset.brandEdition ?? "",
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        width: Math.max(root.scrollWidth, body.scrollWidth),
        height: Math.max(root.scrollHeight, body.scrollHeight),
      },
      title: primaryTitle?.textContent?.replace(/\s+/gu, " ").trim() ?? "",
      titleLineCount: titleRect && titleLineHeight > 0
        ? Math.max(1, Math.round(titleRect.height / titleLineHeight))
        : 0,
      headings: orderedText("#main-content h1, #main-content h2, #main-content h3, .launcher-main h1"),
      navigationOrder: orderedText(".app-sidebar .app-nav a, .app-sidebar .app-nav button"),
      controlOrder: orderedText(
        "#main-content button, #main-content input, #main-content select, "
        + "#main-content textarea, #main-content a[href], .launcher-main button, .launcher-main a[href]",
      ),
      overlay: overlay?.className ?? "",
      overlayHeadings: overlay
        ? [...overlay.querySelectorAll("h1, h2, h3")].filter(isVisible).map(normalizedText)
        : [],
      overlayControlOrder: overlay
        ? [...overlay.querySelectorAll("button, input, select, textarea, a[href]")]
          .filter(isVisible)
          .map(normalizedText)
          .filter(Boolean)
        : [],
      visualGeometry,
      visualTopology,
      moduleGeometry,
      moduleTopology,
      sidebarWidth: sidebar?.getBoundingClientRect().width ?? 0,
      mainWidth: main?.getBoundingClientRect().width ?? 0,
      overlayFits: !overlayRect || (
        overlayRect.left >= -1
        && overlayRect.top >= -1
        && overlayRect.right <= window.innerWidth + 1
        && overlayRect.bottom <= window.innerHeight + 1
      ),
      horizontalClipping,
      verticalClipping,
      overlapIssues,
      mobileNavigationVisible,
      errorBoundary: Boolean(document.querySelector(".error-page, [data-error-boundary]")),
      appIdentity: {
        universalModeSwitchVisible: [...document.querySelectorAll(".universal-mode-switch")]
          .some(isVisible),
        fixedTitleEditions: [...document.querySelectorAll(".app-title [data-brand-edition]")]
          .filter(isVisible)
          .map((element) => element.getAttribute("data-brand-edition")),
        visibleBrandEditions: [...document.querySelectorAll("[data-brand-edition]")]
          .filter(isVisible)
          .map((element) => element.getAttribute("data-brand-edition"))
          .filter(Boolean),
      },
    };
  });
}

async function waitForStableMetrics(page) {
  let previous = "";
  let stableSamples = 0;
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const latest = await collectMetrics(page);
    const fingerprint = JSON.stringify(latest);
    if (fingerprint === previous) stableSamples += 1;
    else stableSamples = 0;
    if (stableSamples >= 2) return latest;
    previous = fingerprint;
    await page.waitForTimeout(150);
  }
  throw new Error(`${edition}/${surfaceId}/${state}: semantic layout did not stabilize`);
}

const browser = await chromium.connectOverCDP(cdpEndpoint);
try {
  const page = await findAppPage(browser);
  await reloadAtSurface(page);
  const preparation = await prepareSurface(page);
  if (preparation.skipped) {
    const skippedReceipt = {
      schemaVersion: 1,
      kind: "dronedream-installed-surface-semantic-receipt",
      status: "skipped",
      reason: preparation.reason,
      edition,
      surface: surfaceId,
      state,
      locale,
      expectedIdentity: { edition: expectedEdition, documentTitle: expectedDocumentTitle },
      expectedRoute: surface.route,
      action: surface.action ?? null,
    };
    await atomicJson(outputPath, skippedReceipt);
    process.stdout.write(`${JSON.stringify(skippedReceipt)}\n`);
  } else {
  const metrics = await waitForStableMetrics(page);
  const expectedPresentationEdition = edition === "universal"
    ? (surface.universalMode ?? "universal")
    : edition;

  assert.equal(metrics.route, surface.route, `${edition}/${surfaceId}: route mismatch`);
  assert.equal(metrics.documentTitle, expectedDocumentTitle, `${edition}/${surfaceId}: document title mismatch`);
  assert.equal(
    metrics.brandEdition,
    expectedPresentationEdition,
    `${edition}/${surfaceId}: presentation edition identity mismatch`,
  );
  if (edition === "universal" && surface.id !== "launcher") {
    assert(metrics.appIdentity.universalModeSwitchVisible, `${edition}/${surfaceId}: Universal app identity is missing`);
  } else if (edition !== "universal" && surface.id !== "launcher") {
    assert(
      metrics.appIdentity.fixedTitleEditions.includes(edition),
      `${edition}/${surfaceId}: fixed-edition app identity is missing`,
    );
    assert(!metrics.appIdentity.universalModeSwitchVisible, `${edition}/${surfaceId}: fixed edition rendered Universal identity`);
  } else {
    assert(
      metrics.appIdentity.visibleBrandEditions.includes(expectedPresentationEdition),
      `${edition}/${surfaceId}: launcher edition identity is missing`,
    );
  }
  assert(metrics.title.length > 0, `${edition}/${surfaceId}: primary title is missing`);
  assert(!metrics.errorBoundary, `${edition}/${surfaceId}: error boundary rendered`);
  assert(!metrics.mobileNavigationVisible, `${edition}/${surfaceId}: mobile navigation rendered`);
  assert.equal(metrics.horizontalClipping.length, 0, `${edition}/${surfaceId}: content is horizontally clipped`);
  assert.equal(metrics.verticalClipping.length, 0, `${edition}/${surfaceId}: content is vertically clipped`);
  assert.equal(metrics.overlapIssues.length, 0, `${edition}/${surfaceId}: peer controls overlap`);
  assert(metrics.document.width <= metrics.viewport.width + 1, `${edition}/${surfaceId}: page horizontally overflows`);
  assert(metrics.document.height <= metrics.viewport.height + 1, `${edition}/${surfaceId}: page vertically overflows`);
  assert(metrics.overlayFits, `${edition}/${surfaceId}: overlay does not fit inside the viewport`);
  if (surface.id === "launcher") {
    assert.equal(metrics.sidebarWidth, 0, `${edition}/${surfaceId}: launcher rendered a sidebar`);
  } else {
    assert(metrics.sidebarWidth >= 200, `${edition}/${surfaceId}: desktop sidebar is missing`);
  }

  const receipt = {
    schemaVersion: 1,
    kind: "dronedream-installed-surface-semantic-receipt",
    status: "captured",
    edition,
    surface: surfaceId,
    state,
    locale,
    expectedIdentity: {
      edition: expectedEdition,
      documentTitle: expectedDocumentTitle,
      presentationEdition: expectedPresentationEdition,
    },
    expectedRoute: surface.route,
    action: surface.action ?? null,
    metrics,
  };
  await atomicJson(outputPath, receipt);
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
  }
} finally {
  // The helper observes an already-running WebView and must never send Browser.close.
}

process.exit(0);
