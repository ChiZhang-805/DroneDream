import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1337, height: 800 } });
const locales = ["en", "zh-CN", "zh-TW", "es", "ja", "ko"];
const failures = [];
const textFailures = [];
const behaviorFailures = [];
const captureDirectory = process.env.DD_SETTINGS_CAPTURE_DIR;

try {
  await page.goto("http://127.0.0.1:4317/console/assistant?docsPreview=1", { waitUntil: "networkidle" });
  await page.locator(".app-header .launcher-settings-button").click();
  await page.locator(".launcher-settings-dialog").waitFor({ state: "visible" });

  for (let localeIndex = 0; localeIndex < locales.length; localeIndex += 1) {
    await page.locator(".launcher-settings-tabs button").first().click();
    await page.locator(".launcher-language-options button").nth(localeIndex).click();
    await page.waitForTimeout(100);

    for (let tabIndex = 0; tabIndex < 4; tabIndex += 1) {
      const tabs = page.locator(".launcher-settings-tabs button");
      await tabs.nth(tabIndex).click();
      await page.waitForTimeout(60);
      const metrics = await page.locator(".launcher-settings-panel:not([hidden])").evaluate((panel) => ({
        clientHeight: panel.clientHeight,
        scrollHeight: panel.scrollHeight,
        clientWidth: panel.clientWidth,
        scrollWidth: panel.scrollWidth,
      }));
      if (metrics.scrollHeight > metrics.clientHeight + 1 || metrics.scrollWidth > metrics.clientWidth + 1) {
        failures.push({ locale: locales[localeIndex], tabIndex, metrics });
      }
      const clippedText = await page.locator(".launcher-settings-panel:not([hidden])").evaluate((panel) => (
        [...panel.querySelectorAll("button, label, strong, p, span")]
          .filter((node) => {
            const element = /** @type {HTMLElement} */ (node);
            const text = element.innerText?.trim();
            if (!text || element.children.length > 0) return false;
            return element.scrollWidth > element.clientWidth + 1
              || element.scrollHeight > element.clientHeight + 1;
          })
          .map((node) => ({
            text: /** @type {HTMLElement} */ (node).innerText.trim().slice(0, 80),
            clientWidth: /** @type {HTMLElement} */ (node).clientWidth,
            scrollWidth: /** @type {HTMLElement} */ (node).scrollWidth,
            clientHeight: /** @type {HTMLElement} */ (node).clientHeight,
            scrollHeight: /** @type {HTMLElement} */ (node).scrollHeight,
          }))
      ));
      if (clippedText.length > 0) {
        textFailures.push({ locale: locales[localeIndex], tabIndex, clippedText });
      }
    }
  }

  await page.locator(".launcher-settings-tabs button").first().click();
  await page.locator(".settings-appearance-options button").last().click();
  await page.waitForTimeout(100);
  const customizeMetrics = await page.locator(".launcher-settings-panel:not([hidden])").evaluate((panel) => ({
    clientHeight: panel.clientHeight,
    scrollHeight: panel.scrollHeight,
    clientWidth: panel.clientWidth,
    scrollWidth: panel.scrollWidth,
  }));
  if (customizeMetrics.scrollHeight > customizeMetrics.clientHeight + 1
    || customizeMetrics.scrollWidth > customizeMetrics.clientWidth + 1) {
    failures.push({ locale: "ko", tabIndex: "customize", metrics: customizeMetrics });
  }

  await page.locator(".launcher-settings-tabs button").first().click();
  await page.locator(".launcher-language-options button").first().click();
  await page.locator(".launcher-settings-tabs button").nth(2).click();
  const readyLabelMetrics = await page.locator(".settings-reset-card-picker > span").evaluate((label) => {
    const element = /** @type {HTMLElement} */ (label);
    const style = getComputedStyle(element);
    return {
      text: element.innerText.trim(),
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      whiteSpace: style.whiteSpace,
    };
  });
  if (readyLabelMetrics.text !== "Ready to use"
    || readyLabelMetrics.scrollHeight > readyLabelMetrics.clientHeight + 1
    || readyLabelMetrics.whiteSpace !== "nowrap") {
    behaviorFailures.push({ check: "reset-card-label-single-line", readyLabelMetrics });
  }

  await page.locator(".settings-reset-card-trigger").click();
  const resetCardMenu = page.locator(".settings-reset-card-menu");
  await resetCardMenu.waitFor({ state: "visible" });
  const resetCardMetrics = await resetCardMenu.evaluate((menu) => {
    const rect = menu.getBoundingClientRect();
    return {
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      left: rect.left,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  const resetCardCount = await resetCardMenu.locator("button").count();
  const resetCardIconCount = await resetCardMenu.locator(".settings-reset-card-icon").count();
  const resetCardExpiryCount = await resetCardMenu.locator("small").count();
  if (resetCardCount !== 4 || resetCardIconCount !== 4 || resetCardExpiryCount !== 4
    || resetCardMetrics.top < 0 || resetCardMetrics.left < 0
    || resetCardMetrics.right > resetCardMetrics.viewportWidth
    || resetCardMetrics.bottom > resetCardMetrics.viewportHeight) {
    behaviorFailures.push({
      check: "four-reset-card-menu-visible",
      resetCardCount,
      resetCardIconCount,
      resetCardExpiryCount,
      resetCardMetrics,
    });
  }
  await resetCardMenu.locator("button").first().click();

  if (captureDirectory) {
    await mkdir(captureDirectory, { recursive: true });
    await page.locator(".launcher-settings-tabs button").first().click();
    await page.locator(".launcher-language-options button").first().click();
    for (let tabIndex = 0; tabIndex < 4; tabIndex += 1) {
      await page.locator(".launcher-settings-tabs button").nth(tabIndex).click();
      await page.waitForTimeout(80);
      await page.locator(".launcher-settings-dialog").screenshot({
        path: join(captureDirectory, `settings-tab-${tabIndex}.png`),
      });
    }
    await page.locator(".launcher-settings-tabs button").nth(2).click();
    await page.locator(".settings-reset-card-trigger").click();
    await page.waitForTimeout(80);
    await page.screenshot({ path: join(captureDirectory, "settings-reset-cards-open.png") });
  }

  console.log(JSON.stringify({
    locales,
    failures,
    textFailures,
    behaviorFailures,
    customizeMetrics,
    readyLabelMetrics,
    resetCardMetrics,
  }, null, 2));
  if (failures.length > 0 || textFailures.length > 0 || behaviorFailures.length > 0) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
