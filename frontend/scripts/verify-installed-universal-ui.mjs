import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const args = new Map(
  process.argv.slice(2).map((argument) => {
    const [key, ...value] = argument.split("=");
    return [key, value.join("=") || true];
  }),
);

function required(name) {
  const value = args.get(name);
  if (!value || value === true) throw new Error(`Missing required argument ${name}`);
  return String(value);
}

const cdpEndpoint = required("--cdp-endpoint");
const outputPath = path.resolve(required("--output"));
const screenshotRoot = path.resolve(required("--screenshot-root"));
const caseId = required("--case-id");
const locale = required("--locale");
const edition = required("--edition");
const expectedWidth = Number(required("--width"));
const expectedHeight = Number(required("--height"));

const canonicalColors = Object.freeze({
  universal: ["#FF5574", "#6A4CFF", "#E657D1"],
  sim: ["#00D9FF", "#2671FF", "#744CFF"],
  lab: ["#A7E84A", "#20C77A", "#087E69"],
  field: ["#FFC247", "#FF754B", "#D746A5"],
});

assert(locale === "en" || locale === "zh-CN", `Unsupported locale: ${locale}`);
assert(Object.hasOwn(canonicalColors, edition), `Unsupported presentation edition: ${edition}`);
assert(Number.isInteger(expectedWidth) && expectedWidth >= 390, "Invalid expected width");
assert(Number.isInteger(expectedHeight) && expectedHeight >= 700, "Invalid expected height");
assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP must remain loopback-only");

async function sha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

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

async function saveScreenshot(page, surface) {
  await mkdir(screenshotRoot, { recursive: true });
  const filePath = path.join(screenshotRoot, `${caseId}-${surface}.png`);
  await page.screenshot({ path: filePath, fullPage: false });
  return {
    absolutePath: filePath,
    bytes: (await readFile(filePath)).byteLength,
    sha256: await sha256(filePath),
  };
}

async function visibleSettingsButton(page) {
  const desktopButton = page.locator(".launcher-settings-button:visible").first();
  if (await desktopButton.isVisible()) return desktopButton;

  const menuButton = page.locator(".app-mobile-menu-button:visible").first();
  await menuButton.waitFor({ state: "visible", timeout: 30_000 });
  assert.equal(
    await menuButton.getAttribute("aria-expanded"),
    "false",
    "The compact navigation menu must start collapsed",
  );
  await menuButton.focus();
  await menuButton.press("Enter");
  const mobileButton = page.locator(".app-mobile-settings-entry:visible").first();
  await mobileButton.waitFor({ state: "visible", timeout: 30_000 });
  return mobileButton;
}

const browser = await chromium.connectOverCDP(cdpEndpoint);
{
  const contexts = browser.contexts();
  assert.equal(contexts.length, 1, "Expected exactly one installed-app browser context");
  const pages = contexts[0].pages();
  assert(pages.length >= 1, "Installed app exposed no WebView page");
  const page = pages.find((candidate) => /(?:tauri|localhost)/u.test(candidate.url())) ?? pages[0];
  await page.waitForLoadState("domcontentloaded");
  await page.evaluate(() => {
    // Packaged desktop builds use createHashRouter. Changing pathname here
    // reloads the WebView at an unowned resource URL and the app falls back to
    // its Universal launcher, which can masquerade as a failed theme switch.
    if (window.location.hash !== "#/desktop/setup") {
      const launcherUrl = new URL(window.location.href);
      launcherUrl.hash = "/desktop/setup";
      window.location.replace(launcherUrl.href);
    }
  });
  await page.waitForURL((url) => url.hash === "#/desktop/setup");
  await page.locator(".drone-launch-scene").waitFor({ state: "visible", timeout: 30_000 });

  const initialViewport = await page.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }));
  assert(
    Math.abs(initialViewport.width - expectedWidth) <= 2,
    `${caseId}: actual app client width ${initialViewport.width} != ${expectedWidth}`,
  );
  assert(
    Math.abs(initialViewport.height - expectedHeight) <= 2,
    `${caseId}: actual app client height ${initialViewport.height} != ${expectedHeight}`,
  );

  const startupTheme = await page.locator("html").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      edition: element.dataset.brandEdition,
      productMode: element.dataset.productMode,
      presentationOnly: element.dataset.themePresentationOnly,
      grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority,
      colors: [
        style.getPropertyValue("--dd-brand-start").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-middle").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-end").trim().toUpperCase(),
      ],
    };
  });
  assert.equal(startupTheme.edition, "universal");
  assert.equal(startupTheme.productMode, "universal");
  assert.equal(startupTheme.presentationOnly, "true");
  assert.equal(startupTheme.grantsHardwareAuthority, "false");
  assert.deepEqual(startupTheme.colors, canonicalColors.universal);
  const scene = await page.locator(".drone-launch-scene").evaluate((element) => ({
    edition: element.getAttribute("data-theme-edition"),
    colors: [
      element.getAttribute("data-theme-primary")?.toUpperCase(),
      element.getAttribute("data-theme-secondary")?.toUpperCase(),
      element.getAttribute("data-theme-tertiary")?.toUpperCase(),
    ],
    grantsHardwareAuthority: element.getAttribute("data-theme-grants-hardware-authority"),
  }));
  assert.equal(scene.edition, "universal");
  assert.equal(scene.grantsHardwareAuthority, "false");
  assert.deepEqual(scene.colors, canonicalColors.universal);
  const sceneScreenshot = await saveScreenshot(page, "scene");

  const presentationRoute = edition === "universal"
    ? "/vehicle-studio"
    : edition === "sim"
      ? "/assistant"
      : `/${edition}`;
  await page.evaluate(({ nextLocale, nextEdition, nextRoute }) => {
    window.localStorage.setItem("drone-dream:locale", nextLocale);
    window.localStorage.setItem(
      "dronedream:universal-workspace:v2",
      nextEdition === "universal" ? "sim" : nextEdition,
    );
    // Preserve the packaged app resource URL and change only the router hash.
    const presentationUrl = new URL(window.location.href);
    presentationUrl.hash = nextRoute;
    window.location.replace(presentationUrl.href);
  }, { nextLocale: locale, nextEdition: edition, nextRoute: presentationRoute });
  await page.waitForURL((url) => url.hash === `#${presentationRoute}`);
  await page.waitForLoadState("domcontentloaded");
  await page.locator(
    ".launcher-settings-button:visible, .app-mobile-menu-button:visible",
  ).first().waitFor({
    state: "visible",
    timeout: 30_000,
  });

  const theme = await page.locator("html").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      edition: element.dataset.brandEdition,
      productMode: element.dataset.productMode,
      presentationOnly: element.dataset.themePresentationOnly,
      grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority,
      colors: [
        style.getPropertyValue("--dd-brand-start").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-middle").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-end").trim().toUpperCase(),
      ],
    };
  });
  assert.equal(theme.edition, edition);
  assert.equal(theme.productMode, edition);
  assert.equal(theme.presentationOnly, "true");
  assert.equal(theme.grantsHardwareAuthority, "false");
  assert.deepEqual(theme.colors, canonicalColors[edition]);

  const settingsButton = await visibleSettingsButton(page);
  assert((await settingsButton.getAttribute("aria-label"))?.trim(), "Settings button needs an accessible label");
  await settingsButton.focus();
  await settingsButton.press("Enter");

  const dialog = page.locator(".launcher-settings-dialog");
  await dialog.waitFor({ state: "visible" });
  assert.equal(await dialog.getAttribute("data-brand-edition"), edition);
  assert.equal(await dialog.getAttribute("data-presentation-only"), "true");
  assert.equal(await dialog.getAttribute("data-grants-hardware-authority"), "false");

  const tabs = dialog.getByRole("tab");
  assert.equal(await tabs.count(), 4, "Settings must expose exactly four compact tabs");
  const panels = [];
  for (let index = 0; index < 4; index += 1) {
    const tab = tabs.nth(index);
    assert((await tab.getAttribute("title"))?.trim(), "Every icon tab needs a tooltip title");
    await tab.focus();
    await tab.press("Enter");
    const measurement = await dialog.evaluate((element) => {
      const panel = element.querySelector(".launcher-settings-panel:not([hidden])");
      if (!(panel instanceof HTMLElement)) throw new Error("Active Settings panel is missing");
      const dialogRect = element.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      return {
        id: panel.dataset.settingsPanel,
        dialogClientHeight: element.clientHeight,
        dialogScrollHeight: element.scrollHeight,
        panelClientHeight: panel.clientHeight,
        panelScrollHeight: panel.scrollHeight,
        dialogTop: dialogRect.top,
        dialogBottom: dialogRect.bottom,
        panelTop: panelRect.top,
        panelBottom: panelRect.bottom,
      };
    });
    assert(
      measurement.dialogScrollHeight <= measurement.dialogClientHeight + 1,
      `${caseId}/${measurement.id}: Settings dialog vertically overflowed`,
    );
    assert(
      measurement.panelScrollHeight <= measurement.panelClientHeight + 1,
      `${caseId}/${measurement.id}: active Settings panel vertically overflowed`,
    );
    assert(measurement.dialogTop >= -1 && measurement.dialogBottom <= expectedHeight + 1);
    assert(measurement.panelTop >= measurement.dialogTop - 1);
    assert(measurement.panelBottom <= measurement.dialogBottom + 1);
    panels.push(measurement);
  }

  await tabs.nth(0).focus();
  await tabs.nth(0).press("Enter");
  const settingsScreenshot = await saveScreenshot(page, "settings");
  const closeButton = dialog.locator(".launcher-settings-close");
  assert((await closeButton.getAttribute("aria-label"))?.trim(), "Settings close button needs an accessible label");
  await closeButton.focus();
  await closeButton.press("Enter");
  await dialog.waitFor({ state: "hidden" });

  await atomicJson(outputPath, {
    schemaVersion: 1,
    kind: "dronedream-installed-universal-ui-case-receipt",
    caseId,
    locale,
    presentationEdition: edition,
    presentationOnly: true,
    grantsHardwareAuthority: false,
    actualClientViewport: initialViewport,
    startupTheme,
    theme,
    scene,
    settingsOpenCount: 1,
    settingsTabActivationCount: 4,
    panels,
    screenshots: {
      scene: sceneScreenshot,
      settings: settingsScreenshot,
    },
  });
}

// Do not call browser.close(): this process is only an observer attached to an
// already-running WebView2 instance, and must never own or terminate the app.
// Exiting the helper closes its loopback CDP socket without sending Browser.close.
process.exit(0);
