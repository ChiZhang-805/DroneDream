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

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const cases = [
  { id: "desktop-en", locale: "en", viewport: { width: 1440, height: 1000 } },
  { id: "desktop-zh", locale: "zh-CN", viewport: { width: 1440, height: 1000 } },
  { id: "mobile-en", locale: "en", viewport: { width: 390, height: 844 } },
  { id: "mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
];
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
  await page.goto(`${origin}/assistant?docsPreview=1`, { waitUntil: "networkidle" });
  const assistantModel = page.locator(".assistant-model-button");
  await assistantModel.waitFor();
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
  const usage = dialog.locator(".settings-model-usage");
  await usage.scrollIntoViewIfNeeded();
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
  assert.equal(metrics.foregroundColor, "rgb(247, 242, 255)");
  assert.equal(metrics.mutedColor, "rgb(214, 183, 234)");
  assert.equal(metrics.accessModeColor, "rgb(247, 242, 255)");
  assert.equal(metrics.headingColor, "rgb(30, 23, 33)");
  const manage = usage.locator(".settings-model-plan-row .btn");
  const refresh = usage.locator(".settings-model-refresh");
  await manage.focus();
  await page.keyboard.press("Tab");
  assert(await refresh.evaluate((element) => element === document.activeElement));
  const image = await screenshot(page, testCase.id, "settings");
  await dialog.locator(".launcher-settings-close").click();
  return {
    ...metrics,
    keyboardFocusOrder: "manage-subscription -> refresh-usage",
    assistantModelImage,
    image,
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
  if (testCase.viewport.width <= 520) {
    const menuButton = page.locator(".app-mobile-menu-button");
    assert(await menuButton.isVisible(), `${testCase.id}: mobile menu trigger is missing`);
    assert.equal(await page.locator(".app-header").isVisible(), false);
    await menuButton.click();
    const panel = page.locator(".app-mobile-menu-panel");
    await panel.waitFor();
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
        account: bounds(account),
        settings: bounds(settings),
        links: links.map(bounds),
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
    assert.equal(mobileMenu.documentScrollWidth, mobileMenu.documentWidth);
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
    mobileMenuImage,
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
  assert(closeEnough(track.switcher.right, track.visual.right, 2));
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
    const entry = { case: testCase };
    try {
      entry.settings = await verifySettings(page, testCase);
      entry.avatar = await verifyAvatar(page, testCase, avatarBytes);
      entry.fixedScenarios = await verifyFixedScenarios(page, testCase);
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
  if (!failure) {
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
