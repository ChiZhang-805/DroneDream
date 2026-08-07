import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { deflateSync } from "node:zlib";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const args = new Map(
  process.argv.slice(2).map((argument) => {
    const [key, ...value] = argument.split("=");
    return [key, value.join("=") || true];
  }),
);
const label = String(args.get("--label") || "working-tree");
const outputRoot = path.resolve(
  repoRoot,
  String(
    args.get("--output")
      || path.join("frontend", "node_modules", ".cache", "software-ui-layout", label),
  ),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5197);
const origin = `http://${host}:${port}`;
const mobileMenuOnly = Boolean(args.get("--mobile-menu-only"));
const fixedScenariosOnly = Boolean(args.get("--fixed-scenarios-only"));
const settingsOnly = Boolean(args.get("--settings-only"));

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const baseCases = [
  { id: "desktop-en", locale: "en", edition: "sim", viewport: { width: 1440, height: 1000 } },
  { id: "desktop-zh", locale: "zh-CN", edition: "sim", viewport: { width: 1440, height: 1000 } },
  { id: "tablet-en", locale: "en", edition: "sim", viewport: { width: 760, height: 900 } },
  { id: "tablet-zh", locale: "zh-CN", edition: "sim", viewport: { width: 760, height: 900 } },
  { id: "mobile-en", locale: "en", edition: "sim", viewport: { width: 390, height: 844 } },
  { id: "mobile-zh", locale: "zh-CN", edition: "sim", viewport: { width: 390, height: 844 } },
].filter((testCase) => !mobileMenuOnly || testCase.viewport.width <= 520);
const cases = baseCases.flatMap((testCase) => (
  settingsOnly
    ? ["dark", "light"].map((appearance) => ({
        ...testCase,
        id: `${testCase.id}-${appearance}`,
        appearance,
      }))
    : [{ ...testCase, appearance: "dark" }]
));
const canonicalThemeColors = Object.freeze({
  universal: ["#FF5574", "#6A4CFF", "#E657D1"],
  sim: ["#00D9FF", "#2671FF", "#744CFF"],
  lab: ["#A7E84A", "#20C77A", "#087E69"],
  field: ["#FFC247", "#FF754B", "#D746A5"],
});
const fixedScenarioOnlyCases = [
  {
    id: "tablet-fixed-scenarios-en",
    locale: "en",
    viewport: { width: 760, height: 900 },
  },
];

function git(...gitArgs) {
  return execFileSync("git", gitArgs, {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, payload) {
  const typeBytes = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(payload.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, payload])));
  return Buffer.concat([length, typeBytes, payload, checksum]);
}

function syntheticAvatarPng(width = 640, height = 480) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  const scanlines = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    const row = y * (width * 4 + 1);
    scanlines[row] = 0;
    for (let x = 0; x < width; x += 1) {
      const pixel = row + 1 + x * 4;
      scanlines[pixel] = Math.round((x / width) * 220 + 20);
      scanlines[pixel + 1] = Math.round((y / height) * 170 + 40);
      scanlines[pixel + 2] = x < width / 2 ? 235 : 120;
      scanlines[pixel + 3] = 255;
    }
  }
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(scanlines, { level: 9 })),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function closeEnough(left, right, tolerance = 2) {
  return Math.abs(left - right) <= tolerance;
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

async function screenshot(page, id, surface) {
  const target = path.join(outputRoot, `${id}-${surface}.png`);
  await page.screenshot({ path: target, fullPage: false });
  return {
    path: path.relative(repoRoot, target).replaceAll("\\", "/"),
    sha256: await sha256File(target),
  };
}

async function openAccountCropper(page, avatarBytes) {
  const account = page.locator(".account-dialog");
  if (!(await account.isVisible())) {
    const accountButton = page.locator(".app-account-button");
    if (!(await accountButton.isVisible())) {
      await page.locator(".app-mobile-menu-button").click();
    }
    await accountButton.click();
  }
  await account.waitFor();
  await account.locator('input[type="file"]').setInputFiles({
    name: "synthetic-avatar.png",
    mimeType: "image/png",
    buffer: avatarBytes,
  });
  const cropper = page.locator(".avatar-crop-dialog");
  await cropper.waitFor();
  await cropper.locator(".avatar-crop-viewport img").waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const image = document.querySelector(".avatar-crop-viewport img");
    const confirm = document.querySelector(".avatar-crop-dialog .btn-primary");
    return image instanceof HTMLImageElement
      && image.complete
      && image.naturalWidth > 0
      && confirm instanceof HTMLButtonElement
      && !confirm.disabled;
  });
  return { account, cropper };
}

async function verifySettings(page, testCase) {
  const settingsViewport = testCase.viewport.width === 1440
    ? { width: 1440, height: 900 }
    : testCase.viewport.width === 390
      ? { width: 390, height: 700 }
      : testCase.viewport;
  await page.setViewportSize(settingsViewport);
  await page.goto(`${origin}/assistant?docsPreview=1`, { waitUntil: "networkidle" });
  const themeBinding = await page.locator("html").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      edition: element.dataset.brandEdition,
      appearance: element.dataset.ddAppearance,
      presentationOnly: element.dataset.themePresentationOnly,
      grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority,
      colors: [
        style.getPropertyValue("--dd-brand-start").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-middle").trim().toUpperCase(),
        style.getPropertyValue("--dd-brand-end").trim().toUpperCase(),
      ],
    };
  });
  assert.equal(themeBinding.edition, testCase.edition);
  assert.equal(themeBinding.appearance, testCase.appearance);
  assert.equal(themeBinding.presentationOnly, "true");
  assert.equal(themeBinding.grantsHardwareAuthority, "false");
  assert.deepEqual(themeBinding.colors, canonicalThemeColors[testCase.edition]);
  const assistantModel = page.locator(".assistant-model-button");
  await assistantModel.waitFor();
  const workspacePresentation = await page.evaluate(() => {
    const heading = document.querySelector(".assistant-empty-state h1");
    const stage = document.querySelector(".app-main:has(.experiment-assistant-page)");
    const brand = document.querySelector(".app-title .brand-lockup");
    const rgb = (value) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const luminance = (value) => {
      const channels = rgb(value).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const foreground = getComputedStyle(heading).color;
    const rawBackground = getComputedStyle(stage).backgroundColor;
    const background = rawBackground === "rgba(0, 0, 0, 0)"
      ? document.documentElement.dataset.ddAppearance === "dark"
        ? "rgb(7, 27, 49)"
        : "rgb(241, 250, 255)"
      : rawBackground;
    const lighter = Math.max(luminance(foreground), luminance(background));
    const darker = Math.min(luminance(foreground), luminance(background));
    return {
      brandEdition: brand?.getAttribute("data-brand-edition"),
      foreground,
      background,
      contrast: (lighter + 0.05) / (darker + 0.05),
    };
  });
  assert.equal(workspacePresentation.brandEdition, testCase.edition);
  assert(workspacePresentation.contrast >= 4.5);
  assert.equal(await assistantModel.locator("option").count(), 3);
  assert.equal(
    await assistantModel.getAttribute("aria-label"),
    testCase.locale === "en" ? "Model" : "模型",
  );
  await assistantModel.scrollIntoViewIfNeeded();
  const assistantModelImage = await screenshot(page, testCase.id, "assistant-models");
  if (testCase.viewport.width <= 520) {
    await page.locator(".app-mobile-menu-button").click();
    await page.locator(".app-mobile-settings-entry").click();
  } else {
    await page.locator(".launcher-settings-button").click();
  }
  const dialog = page.locator(".launcher-settings-dialog");
  await dialog.waitFor();
  const layerBinding = await page.locator(".launcher-settings-backdrop").evaluate((element) => {
    const readZIndex = (target) => {
      if (!(target instanceof Element)) return 0;
      const parsed = Number.parseInt(getComputedStyle(target).zIndex, 10);
      return Number.isFinite(parsed) ? parsed : 0;
    };
    return {
      backdropZIndex: readZIndex(element),
      mobileHeaderZIndex: readZIndex(document.querySelector(".app-sidebar")),
    };
  });
  assert(
    layerBinding.backdropZIndex > layerBinding.mobileHeaderZIndex,
    `${testCase.id}: Settings modal must render above the mobile application header`,
  );
  const panelMeasurements = [];
  const panelImages = [];
  for (const tab of await dialog.getByRole("tab").all()) {
    await tab.click();
    const measurement = await dialog.evaluate((element) => {
      const panel = element.querySelector('.launcher-settings-panel:not([hidden])');
      if (!(panel instanceof HTMLElement)) throw new Error("Active Settings panel is missing");
      const dialogBounds = element.getBoundingClientRect();
      const panelBounds = panel.getBoundingClientRect();
      const notificationList = panel.querySelector(".settings-notification-list");
      const modelLoop = panel.querySelector(".settings-model-loop");
      return {
        tab: panel.dataset.settingsPanel,
        dialogClientHeight: element.clientHeight,
        dialogScrollHeight: element.scrollHeight,
        dialogTop: dialogBounds.top,
        dialogBottom: dialogBounds.bottom,
        panelClientHeight: panel.clientHeight,
        panelScrollHeight: panel.scrollHeight,
        panelTop: panelBounds.top,
        panelBottom: panelBounds.bottom,
        grantsHardwareAuthority: element.getAttribute("data-grants-hardware-authority"),
        notificationList: notificationList instanceof HTMLElement ? {
          borderRadius: getComputedStyle(notificationList).borderRadius,
          backgroundColor: getComputedStyle(notificationList).backgroundColor,
          rowCount: notificationList.querySelectorAll(".settings-toggle-row").length,
        } : null,
        memoryDefaultCount: panel.querySelectorAll(".settings-memory-defaults > label").length,
        memoryFactCount: panel.querySelectorAll(".settings-memory-facts").length,
        modelLoopVisible: modelLoop instanceof HTMLElement
          && modelLoop.getBoundingClientRect().bottom <= panelBounds.bottom + 1,
        runtimeRowsWithoutBorders: Array.from(
          panel.querySelectorAll(".settings-runtime-checks li"),
        ).every((row) => getComputedStyle(row).borderBottomWidth === "0px"),
        runtimeLastCheckWithoutBorder: (() => {
          const footer = panel.querySelector(".settings-runtime-last-check");
          return footer === null || getComputedStyle(footer).borderTopWidth === "0px";
        })(),
      };
    });
    const panelImage = await screenshot(page, testCase.id, `settings-${measurement.tab}`);
    assert(
      measurement.dialogScrollHeight <= measurement.dialogClientHeight + 1,
      `${testCase.id}: Settings dialog vertically overflowed on ${measurement.tab}`,
    );
    assert(
      measurement.panelScrollHeight <= measurement.panelClientHeight + 1,
      `${testCase.id}: Settings panel vertically overflowed on ${measurement.tab}: ${JSON.stringify(measurement)}`,
    );
    assert(measurement.dialogTop >= 0 && measurement.dialogBottom <= settingsViewport.height + 1);
    assert(measurement.panelTop >= measurement.dialogTop - 1);
    assert(measurement.panelBottom <= measurement.dialogBottom + 1);
    assert.equal(measurement.grantsHardwareAuthority, "false");
    if (measurement.tab === "general") {
      assert.deepEqual(measurement.notificationList, {
        borderRadius: "0px",
        backgroundColor: "rgba(0, 0, 0, 0)",
        rowCount: 6,
      });
    }
    if (measurement.tab === "memory") {
      assert.equal(measurement.memoryDefaultCount, 6);
      assert.equal(measurement.memoryFactCount, 0);
    }
    if (measurement.tab === "model") assert.equal(measurement.modelLoopVisible, true);
    if (measurement.tab === "runtime") {
      assert.equal(measurement.runtimeRowsWithoutBorders, true);
      assert.equal(measurement.runtimeLastCheckWithoutBorder, true);
    }
    panelMeasurements.push(measurement);
    panelImages.push(panelImage);
  }
  await dialog.getByRole("tab", {
    name: testCase.locale === "en" ? "Model" : "模型",
  }).click();
  const usage = dialog.locator(".settings-model-usage");
  const metrics = await usage.evaluate((element) => {
    const rect = (selector) => {
      const target = element.querySelector(selector);
      if (!(target instanceof HTMLElement)) return null;
      const bounds = target.getBoundingClientRect();
      return {
        left: bounds.left,
        right: bounds.right,
        top: bounds.top,
        bottom: bounds.bottom,
        width: bounds.width,
      };
    };
    const usageBounds = element.getBoundingClientRect();
    return {
      manage: rect(".settings-model-plan-row .btn"),
      refresh: rect(".settings-model-refresh"),
      period: rect(".settings-model-period"),
      footer: rect(".settings-model-usage-footer"),
      usage: {
        left: usageBounds.left,
        right: usageBounds.right,
        top: usageBounds.top,
        bottom: usageBounds.bottom,
        width: usageBounds.width,
      },
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      managedModelOptions: element.querySelectorAll(
        ".settings-managed-model-row select option",
      ).length,
      usageValuesFit: Array.from(
        element.querySelectorAll(".settings-model-usage-grid strong"),
      ).every((value) => value.scrollWidth <= value.clientWidth + 1),
      foregroundColor: getComputedStyle(element).color,
      mutedColor: getComputedStyle(
        element.querySelector(".settings-model-period"),
      ).color,
      accessModeColor: getComputedStyle(
        element.parentElement?.querySelector(".settings-model-access-mode > button"),
      ).color,
      headingColor: getComputedStyle(
        element.parentElement?.querySelector(".settings-model-heading h3"),
      ).color,
    };
  });
  assert(metrics.manage && metrics.refresh && metrics.period && metrics.usage);
  assert(
    closeEnough(metrics.manage.right, metrics.refresh.right, testCase.viewport.width < 600 ? 4 : 2),
    `${testCase.id}: Refresh and Manage right edges diverged`,
  );
  assert(
    metrics.refresh.top < metrics.period.bottom && metrics.refresh.bottom > metrics.period.top,
    `${testCase.id}: Refresh and reset time are not on the same row`,
  );
  assert.equal(
    metrics.documentScrollWidth,
    metrics.documentWidth,
    `${testCase.id}: Settings caused horizontal document overflow`,
  );
  assert.equal(metrics.managedModelOptions, 3);
  assert(metrics.usageValuesFit, `${testCase.id}: Usage values were visually truncated`);
  const expectedSettingsColors = testCase.appearance === "light"
    ? {
        foreground: "rgb(16, 40, 59)",
        muted: "rgb(92, 113, 129)",
      }
    : {
        foreground: "rgb(244, 248, 255)",
        muted: "rgb(174, 189, 208)",
      };
  assert.equal(metrics.foregroundColor, expectedSettingsColors.foreground);
  assert.equal(metrics.mutedColor, expectedSettingsColors.muted);
  assert.equal(metrics.accessModeColor, expectedSettingsColors.foreground);
  assert.equal(metrics.headingColor, expectedSettingsColors.foreground);
  const manage = usage.locator(".settings-model-plan-row .btn");
  const refresh = usage.locator(".settings-model-refresh");
  await manage.focus();
  await page.keyboard.press("Tab");
  assert(await refresh.evaluate((element) => element === document.activeElement));
  const image = await screenshot(page, testCase.id, "settings");
  await dialog.locator(".launcher-settings-close").click();
  await page.setViewportSize(testCase.viewport);
  return {
    ...metrics,
    themeBinding,
    workspacePresentation,
    layerBinding,
    settingsViewport,
    panelMeasurements,
    panelImages,
    keyboardFocusOrder: "manage-subscription -> refresh-usage",
    assistantModelImage,
    image,
  };
}

async function verifyDistributionSetup(page, testCase) {
  await page.goto(`${origin}/desktop/setup?docsPreview=1`, { waitUntil: "networkidle" });
  const panel = page.locator(".distribution-setup-panel-setup");
  await panel.waitFor();
  await panel.scrollIntoViewIfNeeded();
  const metrics = await panel.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const stored = window.localStorage.getItem("dronedream:distribution-selection:v1");
    return {
      left: bounds.left,
      right: bounds.right,
      width: bounds.width,
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      canApply: element.getAttribute("data-can-apply"),
      buttonCount: element.querySelectorAll("button").length,
      stored,
      storedHasSensitiveField: /password|api.?key|secret|token|hardwareAuthorized/i.test(
        stored ?? "",
      ),
      visibleSelects: Array.from(element.querySelectorAll("select")).every((select) => {
        const selectBounds = select.getBoundingClientRect();
        return selectBounds.width > 0 && select.scrollWidth <= select.clientWidth + 1;
      }),
    };
  });
  assert.equal(metrics.canApply, "false");
  assert.equal(metrics.buttonCount, 0);
  assert(metrics.stored, `${testCase.id}: Distribution draft was not persisted`);
  assert.equal(metrics.storedHasSensitiveField, false);
  assert(metrics.visibleSelects, `${testCase.id}: Setup selection overflowed a select`);
  assert.equal(
    metrics.documentScrollWidth,
    metrics.documentWidth,
    `${testCase.id}: Distribution setup caused horizontal document overflow`,
  );
  assert(metrics.left >= 0 && metrics.right <= testCase.viewport.width + 1);
  return {
    ...metrics,
    image: await screenshot(page, testCase.id, "distribution-setup"),
  };
}

async function verifyAvatar(page, testCase, avatarBytes) {
  const { cropper } = await openAccountCropper(page, avatarBytes);
  const initial = await cropper.evaluate((element) => {
    const viewport = element.querySelector(".avatar-crop-viewport");
    const preview = element.querySelector(".avatar-crop-preview");
    const dialog = element.getBoundingClientRect();
    const viewportRect = viewport?.getBoundingClientRect();
    const previewRect = preview?.getBoundingClientRect();
    return {
      dialog: { width: dialog.width, height: dialog.height },
      viewport: viewportRect
        ? { width: viewportRect.width, height: viewportRect.height }
        : null,
      preview: previewRect
        ? { width: previewRect.width, height: previewRect.height }
        : null,
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
  assert(initial.viewport && closeEnough(initial.viewport.width, initial.viewport.height, 1));
  assert(initial.preview && closeEnough(initial.preview.width, initial.preview.height, 1));
  assert.equal(initial.documentScrollWidth, initial.documentWidth);

  const cropArea = cropper.locator(".avatar-crop-viewport");
  const beforeTransform = await cropper.locator(".avatar-crop-viewport img")
    .evaluate((image) => image.style.transform);
  await cropper.locator('input[type="range"]').fill("1.55");
  await cropArea.focus();
  await page.keyboard.press("ArrowRight");
  const afterTransform = await cropper.locator(".avatar-crop-viewport img")
    .evaluate((image) => image.style.transform);
  assert.notEqual(afterTransform, beforeTransform, `${testCase.id}: Crop transform did not change`);
  const image = await screenshot(page, testCase.id, "avatar-crop");

  await cropper.locator("footer .btn").first().click();
  await cropper.waitFor({ state: "detached" });
  assert.equal(await page.locator(".account-avatar img").count(), 0);

  const reopened = await openAccountCropper(page, avatarBytes);
  await reopened.cropper.locator("footer .btn-primary").click();
  await reopened.cropper.waitFor({ state: "detached" });
  await page.locator(".account-avatar img").waitFor();
  const savedAvatar = await page.locator(".account-avatar img").getAttribute("src");
  assert(savedAvatar?.startsWith("data:image/jpeg;base64,"));
  return {
    ...initial,
    syntheticInput: true,
    cancelPreservedAvatar: true,
    confirmedFormat: "image/jpeg",
    outputPixels: "512x512",
    image,
  };
}

async function verifyEce498ExternalEntry(page, testCase) {
  const courseUrl =
    "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html";
  await page.goto(`${origin}/dashboard?docsPreview=1`, { waitUntil: "networkidle" });
  if (testCase.viewport.width <= 520) {
    await page.locator(".app-mobile-menu-button").click();
  }
  const courseLink = page.getByRole("link", { name: "ECE498BH" });
  await courseLink.waitFor();
  assert.equal(await courseLink.getAttribute("href"), courseUrl);
  assert.equal(await courseLink.getAttribute("target"), "_blank");
  assert.equal(await courseLink.getAttribute("rel"), "noreferrer");
  assert.equal(await page.getByRole("tab").count(), 0);
  assert.equal(await page.locator(".ece498-stage-detail").count(), 0);

  await page.context().route(courseUrl, (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: "<!doctype html><title>ECE498BH course fixture</title>",
  }));
  const popupPromise = page.waitForEvent("popup");
  await courseLink.click();
  const popup = await popupPromise;
  // A target=_blank page is observable first as its transient about:blank
  // document. Waiting only for DOMContentLoaded can therefore pass before the
  // course navigation commits and turn a healthy link into a false failure.
  await popup.waitForURL(courseUrl);
  await popup.waitForLoadState("domcontentloaded");
  assert.equal(popup.url(), courseUrl);
  await popup.close();
  await page.context().unroute(courseUrl);

  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
  }));
  assert.equal(dimensions.documentScrollWidth, dimensions.documentWidth);
  const image = await screenshot(page, testCase.id, "ece498-external-entry");
  return {
    courseUrl,
    target: "_blank",
    internalCoursePageRemoved: true,
    popupReachedExactUrl: true,
    ...dimensions,
    image,
  };
}

async function verifyFixedScenarios(page, testCase) {
  await page.goto(`${origin}/scenarios?docsPreview=1`, { waitUntil: "networkidle" });
  const nav = page.locator(".app-nav");
  const navEntries = nav.locator(":scope > a");
  const activeEntry = nav.locator('a[href="/scenarios"]');
  const cards = page.locator(".fixed-scenario-card");
  let mobileMenuImage = null;
  let mobileMenuMetrics = null;
  if (testCase.viewport.width <= 520) {
    const menuButton = page.locator(".app-mobile-menu-button");
    assert(await menuButton.isVisible(), `${testCase.id}: mobile menu trigger is missing`);
    assert.equal(await page.locator(".app-header").isVisible(), false);
    await menuButton.click();
    const panel = page.locator(".app-mobile-menu-panel");
    await panel.waitFor();
    const menuButtonBounds = await menuButton.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, width: rect.width };
    });
    const mobileMenu = await panel.evaluate((element) => {
      const bounds = (target) => {
        const rect = target.getBoundingClientRect();
        return {
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
          width: rect.width,
        };
      };
      const account = element.querySelector(".app-sidebar-footer");
      const settings = element.querySelector(".app-mobile-settings-entry");
      const links = Array.from(element.querySelectorAll(".app-nav > a"));
      if (!(account instanceof HTMLElement) || !(settings instanceof HTMLElement)) {
        throw new Error("Mobile navigation is missing its account or settings row");
      }
      return {
        panel: bounds(element),
        panelMinWidth: getComputedStyle(element).minWidth,
        account: bounds(account),
        settings: bounds(settings),
        links: links.map(bounds),
        rowsFit: [account, ...links, settings].every((row) => (
          row.scrollWidth <= row.clientWidth + 1
          && row.scrollHeight <= row.clientHeight + 1
        )),
        documentWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
      };
    });
    assert.equal(mobileMenu.links.length, 5);
    assert(mobileMenu.account.bottom <= mobileMenu.links[0].top + 1);
    assert(mobileMenu.links.at(-1).bottom <= mobileMenu.settings.top + 1);
    assert(mobileMenu.links.every((entry) => closeEnough(
      entry.width,
      mobileMenu.panel.width,
      2,
    )));
    assert(mobileMenu.rowsFit, `${testCase.id}: mobile menu text is clipped or wrapped`);
    assert.equal(
      mobileMenu.panelMinWidth,
      "0px",
      `${testCase.id}: mobile menu still has a fixed minimum width`,
    );
    assert(closeEnough(
      mobileMenu.panel.right,
      menuButtonBounds.right,
      2,
    ), `${testCase.id}: mobile menu is not right-aligned with its trigger`);
    assert(
      mobileMenu.panel.width < mobileMenu.documentWidth * 0.65,
      `${testCase.id}: mobile menu is ${mobileMenu.panel.width}px instead of shrink-wrapping its longest row`,
    );
    assert.equal(mobileMenu.documentScrollWidth, mobileMenu.documentWidth);
    mobileMenuMetrics = { ...mobileMenu, trigger: menuButtonBounds };
    mobileMenuImage = await screenshot(page, testCase.id, "mobile-navigation");
  }
  await activeEntry.waitFor();
  assert.equal(await navEntries.count(), 5);
  assert.equal(await cards.count(), 4);
  assert(await activeEntry.evaluate((element) => element.classList.contains("active")));

  const metrics = await page.evaluate(() => {
    const bounds = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      };
    };
    const navElement = document.querySelector(".app-nav");
    const pageElement = document.querySelector(".fixed-scenarios-page");
    const version = document.querySelector(".fixed-scenarios-version");
    const navLinks = Array.from(document.querySelectorAll(".app-nav > a"));
    const scenarioCards = Array.from(document.querySelectorAll(".fixed-scenario-card"));
    if (!(navElement instanceof HTMLElement) || !(pageElement instanceof HTMLElement)) {
      throw new Error("Fixed-scenario layout is missing its navigation or page root");
    }
    return {
      nav: bounds(navElement),
      page: bounds(pageElement),
      version: version instanceof HTMLElement ? bounds(version) : null,
      navEntries: navLinks.map((link) => {
        const label = link.querySelector(".app-nav-entry > span");
        return {
          ...bounds(link),
          href: link.getAttribute("href"),
          active: link.classList.contains("active"),
          labelFits: label instanceof HTMLElement
            ? label.scrollWidth <= label.clientWidth + 1
            : false,
        };
      }),
      cards: scenarioCards.map(bounds),
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });

  assert(metrics.version, `${testCase.id}: scenario catalog version badge is missing`);
  assert.equal(metrics.navEntries.filter((entry) => entry.active).length, 1);
  assert.equal(
    metrics.navEntries.find((entry) => entry.active)?.href,
    "/scenarios",
  );
  assert(
    metrics.navEntries.every((entry) => entry.labelFits),
    `${testCase.id}: a primary-navigation label is clipped`,
  );
  assert.equal(
    metrics.documentScrollWidth,
    metrics.documentWidth,
    `${testCase.id}: fixed scenarios caused horizontal document overflow`,
  );
  assert(
    metrics.version.left >= metrics.page.left - 1
      && metrics.version.right <= metrics.page.right + 1,
    `${testCase.id}: catalog version badge escaped the page bounds`,
  );

  if (testCase.viewport.width >= 1000) {
    assert(closeEnough(metrics.cards[0].top, metrics.cards[1].top, 1));
    assert(closeEnough(metrics.cards[2].top, metrics.cards[3].top, 1));
    assert(closeEnough(metrics.cards[0].width, metrics.cards[1].width, 1));
    assert(closeEnough(metrics.cards[2].width, metrics.cards[3].width, 1));
    assert(
      metrics.navEntries.every((entry, index, entries) => (
        index === 0 || entry.top > entries[index - 1].top
      )),
      `${testCase.id}: desktop navigation entries are not vertically ordered`,
    );
  } else {
    assert(
      metrics.cards.every((card) => (
        closeEnough(card.left, metrics.cards[0].left, 1)
        && closeEnough(card.right, metrics.cards[0].right, 1)
      )),
      `${testCase.id}: mobile scenario cards do not share one column`,
    );
    const trailingEntry = metrics.navEntries.at(-1);
    assert(trailingEntry);
    if (testCase.viewport.width <= 520) {
      assert(closeEnough(trailingEntry.left, metrics.nav.left, 1));
      assert(closeEnough(trailingEntry.right, metrics.nav.right, 1));
      assert(
        trailingEntry.top > metrics.navEntries.at(-2).top,
        `${testCase.id}: trailing navigation entry did not receive its full-width row`,
      );
    } else {
      const penultimateEntry = metrics.navEntries.at(-2);
      assert(penultimateEntry);
      assert(closeEnough(penultimateEntry.top, trailingEntry.top, 1));
      assert(penultimateEntry.top > metrics.navEntries.at(-3).top);
      assert(penultimateEntry.left > metrics.nav.left);
      assert(trailingEntry.right < metrics.nav.right);
      assert(closeEnough(
        (penultimateEntry.left + trailingEntry.right) / 2,
        (metrics.nav.left + metrics.nav.right) / 2,
        2,
      ));
    }
  }

  if (testCase.viewport.width <= 520) {
    await page.locator(".app-mobile-menu-button").click();
  }
  const previews = page.locator(".experience-preview");
  assert.equal(await previews.count(), 4);
  assert.equal(await page.locator(".experience-preview-meta").count(), 0);
  assert.equal(await page.locator('.experience-preview-canvas[data-view="3d"]').count(), 4);
  assert.equal(await page.locator(".experience-preview-view-switcher").count(), 4);
  assert(await previews.evaluateAll((elements) => elements.every((element) => (
    element.scrollWidth <= element.clientWidth + 1
  ))), `${testCase.id}: a 3D scenario preview overflows its card`);
  const firstPreview = previews.first();
  const nextViewButton = firstPreview.getByRole("button", {
    name: testCase.locale === "en" ? "Next view" : "下一个视图",
  });
  await nextViewButton.focus();
  assert(await nextViewButton.evaluate((element) => element === document.activeElement));
  await page.keyboard.press("Enter");
  assert.equal(await firstPreview.locator('.experience-preview-canvas[data-view="xy"]').count(), 1);
  const switchedViewImage = await screenshot(page, testCase.id, "fixed-scenarios-xy-view");
  await firstPreview.getByRole("button", {
    name: testCase.locale === "en" ? "Previous view" : "上一个视图",
  }).click();
  assert.equal(await firstPreview.locator('.experience-preview-canvas[data-view="3d"]').count(), 1);
  const image = await screenshot(page, testCase.id, "fixed-scenarios");
  let createRequests = 0;
  const countCreateRequest = (request) => {
    if (request.method() === "POST" && /\/api\/v1\/jobs(?:\?|$)/u.test(request.url())) {
      createRequests += 1;
    }
  };
  page.on("request", countCreateRequest);
  const combinedScenario = page.locator(
    '.fixed-scenario-card[data-template-key="wind-sensor-circle@1"] .fixed-scenario-use',
  );
  await combinedScenario.focus();
  assert(await combinedScenario.evaluate((element) => element === document.activeElement));
  await page.keyboard.press("Enter");
  await page.locator(".wizard-name-modal").waitFor();
  assert.equal(new URL(page.url()).searchParams.get("scenario"), "wind-sensor-circle@1");
  assert.equal(await page.locator(".wizard-name-modal input").inputValue(), "");
  assert.equal(await page.locator(".wizard-stepper").count(), 0);
  assert.equal(createRequests, 0);
  page.off("request", countCreateRequest);

  return {
    ...metrics,
    balancedNavigation: true,
    keyboardScenarioSelection: true,
    freshNameRequired: true,
    createRequests,
    mobileMenu: mobileMenuMetrics,
    mobileMenuImage,
    switchedViewImage,
    image,
  };
}

async function enterWizard(page, testCase) {
  await page.goto(`${origin}/jobs/new?docsPreview=1`, { waitUntil: "networkidle" });
  const nameDialog = page.locator(".wizard-name-modal");
  await nameDialog.waitFor();
  await nameDialog.locator("input").fill(`Synthetic UI audit ${testCase.id}`);
  await nameDialog.locator("button").last().click();
  await nameDialog.waitFor({ state: "detached" });
}

async function verifyTrackAndScenario(page, testCase) {
  await enterWizard(page, testCase);
  await page.locator("#track_type").selectOption("custom");
  await page.locator(".generated-track-callout button").click();
  const trackDialog = page.locator(".wizard-track-modal");
  await trackDialog.waitFor();
  const track = await trackDialog.evaluate((element) => {
    const box = (selector) => {
      const target = element.querySelector(selector);
      if (!(target instanceof HTMLElement)) return null;
      const bounds = target.getBoundingClientRect();
      return {
        left: bounds.left,
        right: bounds.right,
        top: bounds.top,
        bottom: bounds.bottom,
        width: bounds.width,
      };
    };
    return {
      switcher: box(".track-view-switcher"),
      actions: box(".track-editor-actions"),
      visual: box(".track-canvas-shell"),
      data: box(".track-waypoint-table-wrap"),
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
  assert(track.switcher && track.actions && track.visual && track.data);
  assert(track.switcher.bottom <= track.visual.top + 1);
  if (testCase.viewport.width >= 1000) {
    assert(closeEnough(track.switcher.right, track.visual.right, 2));
  } else {
    assert(
      track.switcher.left >= track.visual.left - 1
        && track.switcher.right <= track.visual.right + 1,
      `${testCase.id}: track view switcher escaped the visual column`,
    );
  }
  assert(track.actions.bottom <= track.data.top + 1);
  assert(track.data.left - track.visual.right <= 12);
  assert.equal(track.documentScrollWidth, track.documentWidth);
  const trackImage = await screenshot(page, testCase.id, "track-editor");
  await trackDialog.locator(".wizard-modal-close").click();

  const actions = page.locator(".wizard-actions button");
  await actions.last().click();
  const parameterGroups = page.locator(".parameter-groups");
  await parameterGroups.waitFor();
  const collapsedParameterGroup = parameterGroups.locator(
    '.parameter-group button[aria-expanded="false"]',
  ).first();
  await collapsedParameterGroup.evaluate((button) => button.click());
  const additionalParameters = parameterGroups.locator(
    '.parameter-use-checkbox:not(:checked)',
  );
  assert(
    await additionalParameters.count() >= 3,
    `${testCase.id}: Fewer than three additional parameters were available`,
  );
  for (let index = 0; index < 3; index += 1) {
    await additionalParameters.first().check({ force: true });
  }
  await actions.last().click();
  const scenarioPanel = page.locator(".wizard-panel:not([hidden])");
  await scenarioPanel.locator(".scenario-case-selector").waitFor();
  const scenario = await scenarioPanel.evaluate((element) => {
    const panel = element;
    const selects = Array.from(
      element.querySelectorAll(".scenario-case-option select"),
    ).map((select) => {
      const style = getComputedStyle(select);
      const context = document.createElement("canvas").getContext("2d");
      if (context) context.font = style.font;
      const selected = select.options[select.selectedIndex]?.text || "";
      const textWidth = context?.measureText(selected).width ?? 0;
      return {
        value: selected,
        clientWidth: select.clientWidth,
        textWidth,
        requiredWidth: Math.ceil(textWidth + 42),
      };
    });
    const lastGroup = element.querySelector(".scenario-advanced-group:last-child");
    const panelBounds = panel.getBoundingClientRect();
    const lastBounds = lastGroup?.getBoundingClientRect();
    return {
      panel: {
        clientHeight: panel.clientHeight,
        scrollHeight: panel.scrollHeight,
        overflowY: getComputedStyle(panel).overflowY,
        bottom: panelBounds.bottom,
      },
      lastGroupBottom: lastBounds?.bottom ?? null,
      selects,
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
  assert.equal(scenario.selects.length, 5);
  assert(
    scenario.selects.every((select) => select.clientWidth >= select.requiredWidth),
    `${testCase.id}: Enable/Disable value does not fit its select`,
  );
  assert.equal(scenario.documentScrollWidth, scenario.documentWidth);
  if (testCase.viewport.width >= 1000) {
    assert(
      scenario.panel.scrollHeight <= scenario.panel.clientHeight + 1,
      `${testCase.id}: Scenario panel still requires an inner scrollbar`,
    );
    assert(
      scenario.lastGroupBottom !== null
        && scenario.lastGroupBottom <= scenario.panel.bottom + 1,
      `${testCase.id}: Scenario fields extend below the visible panel`,
    );
  }
  const scenarioImage = await screenshot(page, testCase.id, "scenario");

  await actions.last().click();
  const constraintsPanel = page.locator(".wizard-panel:not([hidden])");
  const completionPolicy = constraintsPanel.locator(".completion-policy-card");
  await completionPolicy.waitFor();
  const continuationToggle = completionPolicy.locator('input[type="checkbox"]');
  assert.equal(await continuationToggle.isChecked(), false);
  await continuationToggle.check();
  const continuationBudget = completionPolicy.locator(".completion-policy-budget");
  await continuationBudget.waitFor();
  const completion = await completionPolicy.evaluate((element) => {
    const policyBounds = element.getBoundingClientRect();
    const panel = element.closest(".wizard-panel");
    if (!(panel instanceof HTMLElement)) {
      throw new Error("Completion policy is not inside the active wizard panel");
    }
    const panelBounds = panel.getBoundingClientRect();
    const budget = element.querySelector(".completion-policy-budget");
    const inputs = Array.from(element.querySelectorAll('input[type="number"]'));
    const providerTurns = element.querySelector("#exploration_additional_provider_turns");
    return {
      policy: {
        left: policyBounds.left,
        right: policyBounds.right,
        top: policyBounds.top,
        bottom: policyBounds.bottom,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      },
      panel: {
        left: panelBounds.left,
        right: panelBounds.right,
        top: panelBounds.top,
        bottom: panelBounds.bottom,
      },
      budgetVisible: budget instanceof HTMLElement
        && getComputedStyle(budget).display !== "none",
      numberInputCount: inputs.length,
      allInputsInsideCard: inputs.every((input) => {
        const bounds = input.getBoundingClientRect();
        return bounds.left >= policyBounds.left - 1 && bounds.right <= policyBounds.right + 1;
      }),
      providerTurnsDisabled: providerTurns instanceof HTMLInputElement
        && providerTurns.disabled,
      providerTurnsValue: providerTurns instanceof HTMLInputElement
        ? providerTurns.value
        : null,
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
  assert(completion.budgetVisible, `${testCase.id}: continuation budget is hidden`);
  assert.equal(completion.numberInputCount, 4);
  assert(completion.allInputsInsideCard, `${testCase.id}: continuation field escaped its card`);
  assert.equal(completion.providerTurnsDisabled, true);
  assert.equal(completion.providerTurnsValue, "0");
  assert(completion.policy.left >= completion.panel.left - 1);
  assert(completion.policy.right <= completion.panel.right + 1);
  assert(completion.policy.scrollWidth <= completion.policy.clientWidth + 1);
  assert.equal(completion.documentScrollWidth, completion.documentWidth);
  const completionImage = await screenshot(page, testCase.id, "completion-policy");

  await actions.last().click();
  const parameterPreview = page.locator(".review-parameter-preview");
  await parameterPreview.waitFor();
  const parameterWheel = await parameterPreview.evaluate(async (element) => {
    const items = Array.from(element.querySelectorAll("code"));
    const bounds = element.getBoundingClientRect();
    const before = {
      scrollLeft: element.scrollLeft,
      itemCount: items.length,
      childTags: Array.from(element.children).map((child) => child.tagName),
      overflowX: getComputedStyle(element).overflowX,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    };
    element.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaY: -100,
      deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    }));
    const deadline = performance.now() + 1_500;
    let last = items.at(-1)?.getBoundingClientRect();
    while (
      (!last || last.right > bounds.right + 1 || last.left >= bounds.right) &&
      performance.now() < deadline
    ) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      last = items.at(-1)?.getBoundingClientRect();
    }
    const wrapped = {
      scrollLeft: element.scrollLeft,
      lastItemVisible: Boolean(
        last && last.right <= bounds.right + 1 && last.left < bounds.right,
      ),
    };
    element.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaY: 100,
      deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    }));
    const returnDeadline = performance.now() + 1_500;
    while (element.scrollLeft > 1 && performance.now() < returnDeadline) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    return {
      before,
      wrapped,
      returnedScrollLeft: element.scrollLeft,
    };
  });
  assert(parameterWheel.before.itemCount >= 7);
  assert(parameterWheel.before.childTags.every((tag) => tag === "CODE"));
  assert.equal(parameterWheel.before.overflowX, "hidden");
  assert(
    parameterWheel.before.scrollWidth > parameterWheel.before.clientWidth,
    `${testCase.id}: parameter preview did not overflow: ${
      JSON.stringify(parameterWheel.before)
    }`,
  );
  assert(parameterWheel.wrapped.scrollLeft > 0);
  assert(parameterWheel.wrapped.lastItemVisible);
  assert(parameterWheel.returnedScrollLeft <= 1);
  const parameterImage = await screenshot(
    page,
    testCase.id,
    "parameter-wheel",
  );

  return {
    track: { ...track, image: trackImage },
    scenario: { ...scenario, image: scenarioImage },
    completionPolicy: { ...completion, image: completionImage },
    parameterWheel: { ...parameterWheel, image: parameterImage },
  };
}

async function verifyWorkspaceLifecycle(page, testCase) {
  const firstName = `Synthetic UI audit ${testCase.id}`;
  const secondName = `Fresh workspace ${testCase.id}`;
  const sidebar = page.locator(".app-workspaces");
  const rows = sidebar.locator(".app-workspace-row");
  assert.equal(await rows.count(), 1);

  await rows.first().locator(".app-workspace-actions button").first().evaluate(
    (button) => button.click(),
  );
  await rows.first().locator(".app-workspace-pinned-indicator").waitFor({
    state: "attached",
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.locator(".app-workspace-pinned-indicator").waitFor({
    state: "attached",
  });

  await page.goto(`${origin}/jobs/new?docsPreview=1`, { waitUntil: "networkidle" });
  const nameDialog = page.locator(".wizard-name-modal");
  await nameDialog.waitFor();
  const nameInput = nameDialog.locator("input");
  assert.equal(await nameInput.inputValue(), "");
  await nameInput.fill(firstName.toUpperCase());
  await nameDialog.locator("button").last().click();
  await nameDialog.locator(".form-error").waitFor();
  assert(await nameDialog.isVisible());

  await nameInput.fill(secondName);
  await nameDialog.locator("button").last().click();
  await page.locator(".wizard-stepper").waitFor();
  assert.equal(await sidebar.locator(".app-workspace-row").count(), 2);
  assert.equal(
    await sidebar.locator(".app-workspace-pinned-indicator").count(),
    1,
  );
  const pinnedImage = await screenshot(page, testCase.id, "workspace-pinned");

  let dragPreviewImage = null;
  if (testCase.viewport.width >= 1000) {
    const list = sidebar.locator(".app-workspace-list");
    await list.evaluate((element) => {
      const workspaceRows = element.querySelectorAll(".app-workspace-row");
      const source = workspaceRows[1];
      const target = workspaceRows[0];
      if (!(source instanceof HTMLElement) || !(target instanceof HTMLElement)) {
        throw new Error("Expected two workspace rows");
      }
      const transfer = new DataTransfer();
      source.dispatchEvent(new DragEvent("dragstart", {
        bubbles: true,
        cancelable: true,
        dataTransfer: transfer,
      }));
      const targetBounds = target.getBoundingClientRect();
      element.dispatchEvent(new DragEvent("dragover", {
        bubbles: true,
        cancelable: true,
        clientY: targetBounds.top,
        dataTransfer: transfer,
      }));
    });
    await sidebar.locator(".app-workspace-drop-preview").waitFor();
    assert(await sidebar.locator(".app-workspace-row").nth(1).evaluate(
      (element) => element.classList.contains("is-drag-source"),
    ));
    dragPreviewImage = await screenshot(
      page,
      testCase.id,
      "workspace-drag-preview",
    );
    await list.evaluate((element) => {
      element.dispatchEvent(new DragEvent("drop", {
        bubbles: true,
        cancelable: true,
        dataTransfer: new DataTransfer(),
      }));
    });
    await page.waitForFunction((expectedName) => (
      document.querySelector(".app-workspace-row a")?.getAttribute("title")
        === expectedName
    ), secondName);
    assert.equal(
      await sidebar.locator(".app-workspace-pinned-indicator").count(),
      2,
    );
  }

  const resumeLink = sidebar.locator(`.app-workspace-row a[title="${firstName}"]`);
  await resumeLink.evaluate((link) => link.click());
  await page.locator(".wizard-stepper").waitFor();
  assert(
    new URL(page.url()).searchParams.has("experiment"),
    `${testCase.id}: Resume link did not use an explicit workspace identity`,
  );
  assert.equal(await page.locator(".wizard-name-modal").count(), 0);

  return {
    freshEntryStartedBlank: true,
    duplicateActiveNameRejected: true,
    pinnedMarkerPersisted: true,
    explicitResumeIdentity: true,
    draggedUnpinnedBeforePinnedBecamePinned:
      testCase.viewport.width >= 1000,
    pinnedImage,
    dragPreviewImage,
  };
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  root: frontendRoot,
  server: { host, port, strictPort: true },
  logLevel: "error",
});
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const avatarBytes = syntheticAvatarPng();
const results = [];
let failure;

try {
  for (const testCase of cases) {
    const context = await browser.newContext({ viewport: testCase.viewport });
    await context.addInitScript(({ locale, appearance }) => {
      window.localStorage.setItem("drone-dream:locale", locale);
      window.localStorage.setItem("dronedream:appearance", appearance);
    }, { locale: testCase.locale, appearance: testCase.appearance });
    await context.route("**/api/v1/**", (route) => route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Offline visual-validation fixture" }),
    }));
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const entry = { case: testCase };
    try {
      entry.settings = await verifySettings(page, testCase);
      if (settingsOnly) {
        entry.scope = "settings-only";
        entry.pageErrors = pageErrors;
        assert.deepEqual(pageErrors, [], `${testCase.id}: page errors`);
        entry.status = "pass";
        results.push(entry);
        await context.close();
        continue;
      }
      entry.distributionSetup = await verifyDistributionSetup(page, testCase);
      entry.avatar = await verifyAvatar(page, testCase, avatarBytes);
      entry.fixedScenarios = await verifyFixedScenarios(page, testCase);
      if (mobileMenuOnly || fixedScenariosOnly) {
        entry.scope = mobileMenuOnly ? "mobile-menu-only" : "fixed-scenarios-only";
        entry.pageErrors = pageErrors;
        assert.deepEqual(pageErrors, [], `${testCase.id}: page errors`);
        entry.status = "pass";
        results.push(entry);
        await context.close();
        continue;
      }
      entry.ece498 = await verifyEce498ExternalEntry(page, testCase);
      entry.wizard = await verifyTrackAndScenario(page, testCase);
      entry.workspace = await verifyWorkspaceLifecycle(page, testCase);
      entry.pageErrors = pageErrors;
      assert.deepEqual(pageErrors, [], `${testCase.id}: page errors`);
      entry.status = "pass";
    } catch (error) {
      entry.status = "fail";
      entry.error = error instanceof Error ? error.stack : String(error);
      failure = error;
    }
    results.push(entry);
    await context.close();
    if (failure) break;
  }
  if (!failure && !mobileMenuOnly && !settingsOnly) {
    for (const testCase of fixedScenarioOnlyCases) {
      const context = await browser.newContext({ viewport: testCase.viewport });
      await context.addInitScript((locale) => {
        window.localStorage.setItem("drone-dream:locale", locale);
      }, testCase.locale);
      await context.route("**/api/v1/**", (route) => route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Offline visual-validation fixture" }),
      }));
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      const entry = { case: testCase, scope: "fixed-scenarios-only" };
      try {
        entry.fixedScenarios = await verifyFixedScenarios(page, testCase);
        entry.pageErrors = pageErrors;
        assert.deepEqual(pageErrors, [], `${testCase.id}: page errors`);
        entry.status = "pass";
      } catch (error) {
        entry.status = "fail";
        entry.error = error instanceof Error ? error.stack : String(error);
        failure = error;
      }
      results.push(entry);
      await context.close();
      if (failure) break;
    }
  }
} finally {
  await browser.close();
  await server.close();
}

const receipt = {
  schema_version: 1,
  subject_commit: git("rev-parse", "HEAD"),
  subject_dirty: Boolean(git("status", "--short")),
  branch: git("branch", "--show-current"),
  browser: "Microsoft Edge (Playwright msedge channel)",
  api_mode: "offline 503 fixture; no API key, backend write, or user photo",
  generated_at: new Date().toISOString(),
  cases: results,
  status: failure ? "fail" : "pass",
};
const receiptPath = path.join(outputRoot, "software-ui-layout-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({
  status: receipt.status,
  receipt: path.relative(repoRoot, receiptPath).replaceAll("\\", "/"),
  receipt_sha256: await sha256File(receiptPath),
  completed_cases: results.length,
}, null, 2)}\n`);
if (failure) throw failure;
