import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const browser = await chromium.launch({ headless: true });
const viewports = [
  { name: "desktop", width: 1337, height: 800 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
];
const page = await browser.newPage({ viewport: viewports[0] });
const locales = ["en", "zh-CN", "zh-TW", "es", "ja", "ko"];
const failures = [];
const textFailures = [];
const behaviorFailures = [];
const captureDirectory = process.env.DD_SETTINGS_CAPTURE_DIR;

async function openSettings(page) {
  await page.locator(".app-shell").waitFor({ state: "visible" });
  await page.evaluate(() => window.dispatchEvent(new Event("dronedream:open-settings")));
  await page.locator(".launcher-settings-dialog").waitFor({ state: "visible" });
}

try {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto("http://127.0.0.1:4317/console/assistant?docsPreview=1", { waitUntil: "networkidle" });
    await openSettings(page);

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
        // Tablet/mobile may scroll vertically inside the bounded dialog, but
        // horizontal overflow is never acceptable at any viewport.
        if ((viewport.name === "desktop" && metrics.scrollHeight > metrics.clientHeight + 1)
          || metrics.scrollWidth > metrics.clientWidth + 1) {
          failures.push({ viewport: viewport.name, locale: locales[localeIndex], tabIndex, metrics });
        }
        const clippedText = await page.locator(".launcher-settings-panel:not([hidden])").evaluate((panel) => (
          [...panel.querySelectorAll("button, label, strong, p, span")]
            .filter((node) => {
              const element = /** @type {HTMLElement} */ (node);
              const text = element.innerText?.trim();
              if (!text || element.children.length > 0) return false;
              return element.scrollWidth > element.clientWidth + 1
                || (getComputedStyle(element).whiteSpace === "nowrap"
                  && element.scrollHeight > element.clientHeight + 1);
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
          textFailures.push({ viewport: viewport.name, locale: locales[localeIndex], tabIndex, clippedText });
        }
      }
    }
    await page.locator(".launcher-settings-close").click();
  }

  await page.setViewportSize(viewports[0]);
  await page.goto("http://127.0.0.1:4317/console/assistant?docsPreview=1", { waitUntil: "networkidle" });
  await openSettings(page);

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
  const readyLabelMetrics = await page.locator(".settings-model-reset-summary span").last().evaluate((label) => {
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
  const resetCardNumberCount = await resetCardMenu.locator("small").evaluateAll((nodes) => (
    nodes.filter((node) => /DD-[A-Z0-9-]+/u.test(node.textContent ?? "")).length
  ));
  const selectedCardMetrics = await page.locator(".settings-reset-card-trigger").evaluate((trigger) => {
    const rect = trigger.getBoundingClientRect();
    const amount = trigger.querySelector("strong");
    const expiry = trigger.querySelector("small");
    return {
      width: rect.width,
      amountColor: amount ? getComputedStyle(amount).color : null,
      expiryColor: expiry ? getComputedStyle(expiry).color : null,
      arrowCount: trigger.querySelectorAll(".settings-reset-card-trigger-arrow").length,
    };
  });
  const resetActionMetrics = await page.locator(".settings-model-reset-action").evaluate((button) => {
    const rect = button.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width };
  });
  const refreshActionMetrics = await page.locator(".settings-model-refresh").evaluate((button) => {
    const rect = button.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width };
  });
  if (resetCardCount !== 4 || resetCardIconCount !== 4 || resetCardExpiryCount !== 4
    || resetCardNumberCount !== 0
    || resetCardMetrics.top < 0 || resetCardMetrics.left < 0
    || resetCardMetrics.right > resetCardMetrics.viewportWidth
    || resetCardMetrics.bottom > resetCardMetrics.viewportHeight) {
    behaviorFailures.push({
      check: "four-reset-card-menu-visible",
      resetCardCount,
      resetCardIconCount,
      resetCardExpiryCount,
      resetCardNumberCount,
      resetCardMetrics,
    });
  }
  if (selectedCardMetrics.amountColor !== "rgb(255, 255, 255)"
    || selectedCardMetrics.arrowCount !== 1
    || Math.abs(resetCardMetrics.right - resetCardMetrics.left - selectedCardMetrics.width) > 1
    || Math.abs(resetActionMetrics.left - refreshActionMetrics.left) > 1
    || Math.abs(resetActionMetrics.right - refreshActionMetrics.right) > 1
    || Math.abs(resetActionMetrics.width - refreshActionMetrics.width) > 1) {
    behaviorFailures.push({
      check: "reset-card-trigger-and-actions-aligned",
      selectedCardMetrics,
      resetCardMetrics,
      resetActionMetrics,
      refreshActionMetrics,
    });
  }
  await resetCardMenu.locator("button").first().click();
  await page.locator(".settings-model-reset-action").click();
  const confirmVisible = await page.locator(".settings-model-reset-action").getAttribute("class");
  const confirmText = await page.locator(".settings-model-reset-action").innerText();
  const cancelCount = await page.locator(".settings-model-reset-cancel").count();
  if (!confirmVisible || confirmText !== "Confirm" || cancelCount !== 1) {
    behaviorFailures.push({ check: "reset-card-second-confirmation", confirmText, cancelCount });
  }

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
    selectedCardMetrics,
    resetActionMetrics,
    refreshActionMetrics,
  }, null, 2));
  if (failures.length > 0 || textFailures.length > 0 || behaviorFailures.length > 0) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
