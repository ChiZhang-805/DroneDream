import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const browser = await chromium.launch({ headless: true });
// Settings are a desktop/Web product surface. Phone layouts are deliberately
// outside this verifier because the full Runtime cannot run on a phone.
const viewports = [
  { name: "desktop-window", width: 1280, height: 800 },
  { name: "web", width: 1440, height: 900 },
  { name: "wide-web", width: 1600, height: 1000 },
];
const page = await browser.newPage({ viewport: viewports[0] });
const locales = ["en", "zh-CN"];
const failures = [];
const textFailures = [];
const behaviorFailures = [];
const captureDirectory = process.env.DD_SETTINGS_CAPTURE_DIR;

async function openQuickSettings(page) {
  await page.locator(".app-shell").waitFor({ state: "visible" });
  await page.locator(".launcher-settings-button").click();
  const quickSettings = page.locator(".quick-settings-dialog");
  await quickSettings.waitFor({ state: "visible" });
  return quickSettings;
}

async function openSettingsWorkspace(page, localeIndex) {
  const quickSettings = await openQuickSettings(page);
  await quickSettings.locator(".quick-settings-language button").nth(localeIndex).click();
  await page.waitForFunction(
    (locale) => window.localStorage.getItem("drone-dream:locale") === locale,
    locales[localeIndex],
  );
  const quickMetrics = await quickSettings.evaluate((dialog) => {
    const bounds = dialog.getBoundingClientRect();
    return {
      left: bounds.left,
      top: bounds.top,
      right: bounds.right,
      bottom: bounds.bottom,
      width: bounds.width,
      height: bounds.height,
      aspectRatio: bounds.width / bounds.height,
      clientHeight: dialog.clientHeight,
      scrollHeight: dialog.scrollHeight,
      clientWidth: dialog.clientWidth,
      scrollWidth: dialog.scrollWidth,
      tabCount: dialog.querySelectorAll('[role="tab"]').length,
      detailedMemoryControlCount: dialog.querySelectorAll(
        ".settings-memory-grid, .settings-memory-domain-consent, .settings-memory-defaults",
      ).length,
    };
  });
  const viewport = page.viewportSize();
  if (!viewport
    || quickMetrics.left < 0
    || quickMetrics.top < 0
    || quickMetrics.right > viewport.width + 1
    || quickMetrics.bottom > viewport.height + 1
    || quickMetrics.aspectRatio < 1.45
    || quickMetrics.aspectRatio > 1.75
    || quickMetrics.scrollHeight > quickMetrics.clientHeight + 1
    || quickMetrics.scrollWidth > quickMetrics.clientWidth + 1
    || quickMetrics.tabCount !== 0
    || quickMetrics.detailedMemoryControlCount !== 0) {
    failures.push({
      viewport: viewport?.width,
      locale: locales[localeIndex],
      surface: "quick-settings",
      metrics: quickMetrics,
    });
  }
  const allSettingsLabel = localeIndex === 0 ? "All settings" : "全部设置";
  await quickSettings.getByRole("button", { name: allSettingsLabel }).click();
  const workspace = page.locator(".settings-workspace-surface");
  await workspace.waitFor({ state: "visible" });
  await quickSettings.waitFor({ state: "detached" });
  return { quickMetrics, workspace };
}

async function auditActivePanel(page, viewport, locale, tabIndex) {
  const panel = page.locator(".launcher-settings-panel:not([hidden])");
  const metrics = await panel.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const scroller = element.closest(".launcher-settings-panels");
    const workspace = element.closest(".settings-workspace-surface");
    return {
      left: bounds.left,
      top: bounds.top,
      right: bounds.right,
      bottom: bounds.bottom,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      scrollerClientHeight: scroller?.clientHeight ?? 0,
      scrollerScrollHeight: scroller?.scrollHeight ?? 0,
      workspaceWidth: workspace?.clientWidth ?? 0,
      workspaceHeight: workspace?.clientHeight ?? 0,
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
  if (metrics.scrollWidth > metrics.clientWidth + 1
    || metrics.documentScrollWidth > metrics.documentWidth + 1
    || metrics.workspaceWidth !== viewport.width
    || metrics.workspaceHeight !== viewport.height) {
    failures.push({ viewport: viewport.name, locale, tabIndex, metrics });
  }
  const clippedText = await panel.evaluate((element) => (
    [...element.querySelectorAll("button, label, strong, p")]
      .filter((node) => {
        const item = /** @type {HTMLElement} */ (node);
        const text = item.innerText?.trim();
        if (!text || item.children.length > 0 || item.hasAttribute("title")) return false;
        return item.scrollWidth > item.clientWidth + 1
          || (getComputedStyle(item).whiteSpace === "nowrap"
            && item.scrollHeight > item.clientHeight + 1);
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
    textFailures.push({ viewport: viewport.name, locale, tabIndex, clippedText });
  }
  return metrics;
}

try {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    for (let localeIndex = 0; localeIndex < locales.length; localeIndex += 1) {
      await page.goto(
        "http://127.0.0.1:4317/console/assistant?docsPreview=1",
        { waitUntil: "networkidle" },
      );
      const { quickMetrics, workspace } = await openSettingsWorkspace(page, localeIndex);
      const sidebar = workspace.locator(".settings-workspace-sidebar");
      const tablist = sidebar.getByRole("tablist");
      if (await tablist.getAttribute("aria-orientation") !== "vertical") {
        behaviorFailures.push({
          check: "workspace-categories-are-vertical",
          viewport: viewport.name,
          locale: locales[localeIndex],
        });
      }
      const tabs = tablist.getByRole("tab");
      const tabCount = await tabs.count();
      for (let tabIndex = 0; tabIndex < tabCount; tabIndex += 1) {
        const tab = tabs.nth(tabIndex);
        if (await tab.isDisabled()) continue;
        await tab.click();
        await page.waitForTimeout(60);
        await auditActivePanel(page, viewport, locales[localeIndex], tabIndex);
        if (captureDirectory) {
          await mkdir(captureDirectory, { recursive: true });
          await workspace.screenshot({
            path: join(
              captureDirectory,
              `${viewport.name}-${locales[localeIndex]}-settings-${tabIndex}.png`,
            ),
          });
        }
      }
      const backLabel = localeIndex === 0 ? "Back to app" : "返回应用";
      await sidebar.getByRole("button", { name: backLabel }).click();
      await workspace.waitFor({ state: "detached" });
      if (captureDirectory) {
        const quickSettings = await openQuickSettings(page);
        await quickSettings.screenshot({
          path: join(
            captureDirectory,
            `${viewport.name}-${locales[localeIndex]}-quick-settings.png`,
          ),
        });
        await page.keyboard.press("Escape");
      }
      if (quickMetrics.tabCount !== 0) {
        behaviorFailures.push({
          check: "quick-settings-has-no-category-tabs",
          viewport: viewport.name,
          locale: locales[localeIndex],
        });
      }
    }
  }

  await page.setViewportSize(viewports[0]);
  await page.goto(
    "http://127.0.0.1:4317/console/assistant?docsPreview=1",
    { waitUntil: "networkidle" },
  );
  const { workspace } = await openSettingsWorkspace(page, 0);

  await workspace.locator(".settings-workspace-sidebar").getByRole("tab", {
    name: "General",
  }).click();
  await page.locator(".settings-appearance-options button").last().click();
  await page.waitForTimeout(100);
  const customizeMetrics = await auditActivePanel(page, viewports[0], "en", "customize");

  await workspace.locator(".settings-workspace-sidebar").getByRole("tab", {
    name: "Models & allowance",
  }).click();
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
    await page.screenshot({ path: join(captureDirectory, "desktop-settings-reset-cards-open.png") });
  }

  console.log(JSON.stringify({
    target: "desktop-and-web",
    locales,
    viewports,
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
