import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { preview } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const args = new Map(process.argv.slice(2).map((argument) => {
  const [key, ...value] = argument.split("=");
  return [key, value.join("=") || true];
}));
const label = String(args.get("--label") || "working-tree");
const outputRoot = path.resolve(
  repoRoot,
  String(args.get("--output") || path.join(
    "frontend",
    "node_modules",
    ".cache",
    "field-ui-layout",
    label,
  )),
);
const port = Number(args.get("--port") || 5198);
const cases = [
  { id: "field-desktop-en", locale: "en", viewport: { width: 1440, height: 900 } },
  { id: "field-desktop-zh", locale: "zh-CN", viewport: { width: 1440, height: 900 } },
];

function git(...gitArgs) {
  return execFileSync("git", gitArgs, { cwd: repoRoot, encoding: "utf8" }).trim();
}

async function sha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function filesUnder(root) {
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(target));
    else files.push(target);
  }
  return files;
}

await mkdir(outputRoot, { recursive: true });
const distRoot = path.join(frontendRoot, "field-dist");
const distFiles = await filesUnder(distRoot);
const inspectableFiles = distFiles.filter((file) => /\.(?:css|html|js)$/i.test(file));
const payloadText = (await Promise.all(
  inspectableFiles.map((file) => readFile(file, "utf8")),
)).join("\n");
assert(payloadText.includes('consumerProfile:"field"'), "Field Settings consumer marker is missing");
assert(payloadText.includes("data-settings-consumer"), "Shared Settings surface is missing");
assert(payloadText.includes("drone-launch-scene"), "Shared 3D launch scene is missing");
assert(payloadText.includes("REAL DEVICE DOMAIN"), "Field launch telemetry is missing");
assert(!distFiles.some((file) => /gazebo|sitl|hitl|simulator/i.test(path.basename(file))),
  "Field bundle contains a simulator payload path");

const server = await preview({
  configFile: path.join(frontendRoot, "vite.field.config.ts"),
  root: frontendRoot,
  preview: { host: "127.0.0.1", port, strictPort: true },
});
const origin = server.resolvedUrls?.local?.[0]?.replace(/\/$/, "") || `http://127.0.0.1:${port}`;
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];

try {
  for (const testCase of cases) {
    const context = await browser.newContext({ viewport: testCase.viewport });
    await context.addInitScript((locale) => {
      window.localStorage.setItem("dronedream:field:locale", locale);
      const transitions = [];
      const actionAppearances = [];
      window.__FIELD_READINESS_TRANSITIONS__ = transitions;
      window.__FIELD_ACTION_APPEARANCES__ = actionAppearances;
      let lastPercent = null;
      let actionRecorded = false;
      const recordLauncherState = () => {
        const value = document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow");
        if (value !== null && value !== undefined && value !== lastPercent) {
          lastPercent = value;
          transitions.push({ percent: Number(value), atMs: performance.now() });
        }
        const action = document.querySelector(".field-auth-control-launcher button");
        if (action && !actionRecorded) {
          actionRecorded = true;
          actionAppearances.push({
            percent: value === null || value === undefined ? null : Number(value),
            atMs: performance.now(),
          });
        }
      };
      const observer = new MutationObserver(recordLauncherState);
      observer.observe(document, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["aria-valuenow"],
      });
    }, testCase.locale);
    const page = await context.newPage();
    await page.goto(`${origin}/field.html`, { waitUntil: "networkidle" });
    const launcher = page.locator(".field-launcher");
    await launcher.waitFor();
    await page.waitForFunction(() =>
      document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") === "100"
    );

    const theme = await page.locator("html").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        edition: element.dataset.brandEdition,
        presentationOnly: element.dataset.themePresentationOnly,
        grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority,
        colors: [
          style.getPropertyValue("--dd-brand-start").trim().toUpperCase(),
          style.getPropertyValue("--dd-brand-middle").trim().toUpperCase(),
          style.getPropertyValue("--dd-brand-end").trim().toUpperCase(),
        ],
      };
    });
    assert.equal(theme.edition, "field");
    assert.equal(theme.presentationOnly, "true");
    assert.equal(theme.grantsHardwareAuthority, "false");
    assert.deepEqual(theme.colors, ["#FFC247", "#FF754B", "#D746A5"]);
    assert.equal(await launcher.getAttribute("data-authority"), "false");
    assert.equal(await launcher.getAttribute("data-launch-ready"), "true");

    const scene = page.locator(".drone-launch-scene");
    assert.equal(await scene.count(), 1);
    assert.equal(await scene.getAttribute("data-theme-edition"), "field");
    assert.equal(await scene.getAttribute("data-theme-grants-hardware-authority"), "false");
    const canvas = scene.locator("canvas");
    assert.equal(await canvas.count(), 1);
    const canvasBounds = await canvas.boundingBox();
    assert(canvasBounds && canvasBounds.width > 0 && canvasBounds.height > 0,
      `${testCase.id}: Field 3D canvas has no visible area`);

    const layout = await page.evaluate(() => {
      const html = document.documentElement;
      const brand = document.querySelector(".launcher-brand")?.getBoundingClientRect();
      const actions = document.querySelector(".launcher-chrome-actions")?.getBoundingClientRect();
      if (!brand || !actions) throw new Error("Field launcher chrome bounds are unavailable");
      return {
        brandRight: brand.right,
        actionsLeft: actions.left,
        clientWidth: html.clientWidth,
        scrollWidth: html.scrollWidth,
        clientHeight: html.clientHeight,
        scrollHeight: html.scrollHeight,
      };
    });
    assert(layout.brandRight + 8 <= layout.actionsLeft,
      `${testCase.id}: Field lockup overlaps the launcher actions`);
    assert(layout.scrollWidth <= layout.clientWidth + 1,
      `${testCase.id}: Field launcher overflowed horizontally`);
    assert(layout.scrollHeight <= layout.clientHeight + 1,
      `${testCase.id}: Field launcher overflowed vertically`);

    const visibleText = await page.locator("body").innerText();
    assert(!/PX4|Gazebo|SITL|HITL/i.test(visibleText),
      `${testCase.id}: simulator terminology is visible in the Field launcher`);
    const entry = page.getByRole("button", {
      name: testCase.locale === "en"
        ? "Sign in and enter the tuning platform"
        : "登录并进入调优平台",
    });
    await entry.waitFor();
    const launcherTiming = await page.evaluate(() => ({
      transitions: window.__FIELD_READINESS_TRANSITIONS__,
      actionAppearances: window.__FIELD_ACTION_APPEARANCES__,
    }));
    assert(launcherTiming.transitions.length >= 8,
      `${testCase.id}: Field readiness did not expose a smooth multi-step sequence`);
    assert.equal(launcherTiming.transitions.at(-1)?.percent, 100,
      `${testCase.id}: Field readiness did not finish at 100%`);
    assert.equal(launcherTiming.transitions.some((transition) => transition.percent === 99), false,
      `${testCase.id}: Field rendered the prohibited 99% action point`);
    for (let index = 1; index < launcherTiming.transitions.length; index += 1) {
      assert(launcherTiming.transitions[index].percent > launcherTiming.transitions[index - 1].percent,
        `${testCase.id}: Field readiness must increase monotonically`);
    }
    const launcherDurationMs = launcherTiming.transitions.at(-1).atMs
      - launcherTiming.transitions[0].atMs;
    assert(launcherDurationMs >= 4_500 && launcherDurationMs <= 9_000,
      `${testCase.id}: Field readiness duration is outside the visual acceptance window (${launcherDurationMs} ms)`);
    assert(launcherTiming.actionAppearances.length >= 1,
      `${testCase.id}: Field sign-in action never appeared`);
    assert(launcherTiming.actionAppearances.every((appearance) => appearance.percent === 100),
      `${testCase.id}: Field sign-in action appeared before 100% readiness`);
    const entryBounds = await entry.boundingBox();
    assert(entryBounds && entryBounds.x >= 0 && entryBounds.y >= 0 &&
      entryBounds.x + entryBounds.width <= testCase.viewport.width + 1 &&
      entryBounds.y + entryBounds.height <= testCase.viewport.height + 1,
    `${testCase.id}: Field entry action escaped the viewport`);

    const screenshotPath = path.join(outputRoot, `${testCase.id}-launcher.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false });
    const canvasScreenshot = await canvas.screenshot();
    const canvasPixelStats = await page.evaluate(async (imageBase64) => {
      const image = new Image();
      image.src = `data:image/png;base64,${imageBase64}`;
      await image.decode();
      const sample = document.createElement("canvas");
      sample.width = 64;
      sample.height = 64;
      const context = sample.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("Canvas pixel sampler is unavailable");
      context.drawImage(image, 0, 0, sample.width, sample.height);
      const pixels = context.getImageData(0, 0, sample.width, sample.height).data;
      const buckets = new Set();
      let visiblePixels = 0;
      for (let index = 0; index < pixels.length; index += 4) {
        const red = pixels[index];
        const green = pixels[index + 1];
        const blue = pixels[index + 2];
        const alpha = pixels[index + 3];
        if (alpha > 0 && red + green + blue > 24) visiblePixels += 1;
        buckets.add(`${red >> 4}:${green >> 4}:${blue >> 4}:${alpha >> 4}`);
      }
      return { visiblePixels, colorBuckets: buckets.size };
    }, canvasScreenshot.toString("base64"));
    assert(canvasPixelStats.visiblePixels > 512,
      `${testCase.id}: Field 3D canvas pixels are blank`);
    assert(canvasPixelStats.colorBuckets > 24,
      `${testCase.id}: Field 3D canvas has insufficient visual detail`);
    assert.equal(await scene.getAttribute("data-flight-state"), "hover");
    await page.mouse.click(
      canvasBounds.x + canvasBounds.width * 0.5,
      canvasBounds.y + canvasBounds.height * 0.42,
    );
    await page.waitForFunction(() =>
      document.querySelector(".drone-launch-scene")?.getAttribute("data-flight-state") ===
        "starflight"
    );
    await page.locator(".launcher-settings-button").click();
    const quickSettings = page.locator(".quick-settings-dialog");
    await quickSettings.waitFor();
    // Edge can expose the DOM one compositor frame before the newly opened
    // fixed surface is fully painted over the WebGL launcher.
    await page.waitForTimeout(250);
    const quickMetrics = await quickSettings.evaluate((dialog) => {
      const bounds = dialog.getBoundingClientRect();
      return {
        width: bounds.width,
        height: bounds.height,
        aspectRatio: bounds.width / bounds.height,
        clientWidth: dialog.clientWidth,
        scrollWidth: dialog.scrollWidth,
        clientHeight: dialog.clientHeight,
        scrollHeight: dialog.scrollHeight,
        tabCount: dialog.querySelectorAll('[role="tab"]').length,
      };
    });
    assert(quickMetrics.aspectRatio >= 1.55 && quickMetrics.aspectRatio <= 1.65,
      `${testCase.id}: quick settings aspect ratio is not close to 1.6`);
    assert.equal(quickMetrics.tabCount, 0,
      `${testCase.id}: quick settings must not contain category tabs`);
    assert(quickMetrics.scrollWidth <= quickMetrics.clientWidth + 1
      && quickMetrics.scrollHeight <= quickMetrics.clientHeight + 1,
    `${testCase.id}: quick settings overflowed its fixed desktop surface`);
    const quickScreenshotPath = path.join(outputRoot, `${testCase.id}-quick-settings.png`);
    await page.screenshot({ path: quickScreenshotPath, fullPage: false });

    await quickSettings.getByRole("button", {
      name: testCase.locale === "en" ? "All settings" : "全部设置",
    }).click();
    const settingsWorkspace = page.locator(".settings-workspace-surface");
    await settingsWorkspace.waitFor();
    await quickSettings.waitFor({ state: "detached" });
    const workspaceMetrics = await settingsWorkspace.evaluate((surface) => {
      const bounds = surface.getBoundingClientRect();
      const sidebar = surface.querySelector(".settings-workspace-sidebar")?.getBoundingClientRect();
      const content = surface.querySelector(".settings-workspace-content")?.getBoundingClientRect();
      return {
        width: bounds.width,
        height: bounds.height,
        sidebarHeight: sidebar?.height ?? 0,
        contentHeight: content?.height ?? 0,
        clientWidth: surface.clientWidth,
        scrollWidth: surface.scrollWidth,
        clientHeight: surface.clientHeight,
        scrollHeight: surface.scrollHeight,
      };
    });
    assert(workspaceMetrics.width >= testCase.viewport.width - 1
      && workspaceMetrics.height >= testCase.viewport.height - 1,
    `${testCase.id}: full settings did not cover the desktop viewport`);
    assert(workspaceMetrics.sidebarHeight >= testCase.viewport.height - 1
      && workspaceMetrics.contentHeight >= testCase.viewport.height - 1,
    `${testCase.id}: full settings columns did not fill the workspace height`);
    assert(workspaceMetrics.scrollWidth <= workspaceMetrics.clientWidth + 1
      && workspaceMetrics.scrollHeight <= workspaceMetrics.clientHeight + 1,
    `${testCase.id}: full settings surface overflowed the desktop viewport`);
    const categoryList = settingsWorkspace.getByRole("tablist");
    assert.equal(await categoryList.getAttribute("aria-orientation"), "vertical");
    assert.equal(await categoryList.getByRole("tab").count(), 5);
    const workspaceTabScreenshots = {};
    const workspaceTabs = testCase.locale === "en"
      ? [
          ["general", "General"],
          ["memory", "Memory"],
          ["model", "Models"],
          ["runtime", "Runtime & updates"],
        ]
      : [
          ["general", "常规"],
          ["memory", "记忆"],
          ["model", "模型"],
          ["runtime", "Runtime 与更新"],
        ];
    for (const [tabId, tabLabel] of workspaceTabs) {
      await settingsWorkspace.getByRole("tab", { name: tabLabel }).click();
      const panel = settingsWorkspace.locator(`[data-settings-panel="${tabId}"]`);
      await panel.waitFor({ state: "visible" });
      await page.waitForTimeout(100);
      const tabScreenshotPath = path.join(
        outputRoot,
        `${testCase.id}-settings-${tabId}.png`,
      );
      await page.screenshot({ path: tabScreenshotPath, fullPage: false });
      workspaceTabScreenshots[tabId] = {
        path: path.relative(repoRoot, tabScreenshotPath).replaceAll("\\", "/"),
        sha256: await sha256(tabScreenshotPath),
      };
    }
    const courseTab = settingsWorkspace.getByRole("tab", { name: "ECE498BH" });
    await courseTab.click();
    const courseLink = settingsWorkspace.locator(
      'a[href="https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html"]',
    );
    await courseLink.waitFor();
    const courseHref = await courseLink.getAttribute("href");
    assert.equal(await courseLink.getAttribute("target"), "_blank");
    assert.equal(await courseLink.getAttribute("rel"), "noreferrer");
    const settingsScreenshotPath = path.join(outputRoot, `${testCase.id}-settings-workspace.png`);
    await page.screenshot({ path: settingsScreenshotPath, fullPage: false });
    await settingsWorkspace.getByRole("button", {
      name: testCase.locale === "en" ? "Back to app" : "返回应用",
    }).click();
    await settingsWorkspace.waitFor({ state: "detached" });
    assert.equal(await scene.getAttribute("data-flight-state"), "starflight",
      `${testCase.id}: returning from settings reset the launcher scene`);
    results.push({
      ...testCase,
      theme,
      canvasBounds,
      canvasPixelStats,
      entryBounds,
      launcherTiming,
      droneInteraction: "hover-to-starflight",
      quickSettings: {
        metrics: quickMetrics,
        screenshot: {
          path: path.relative(repoRoot, quickScreenshotPath).replaceAll("\\", "/"),
          sha256: await sha256(quickScreenshotPath),
        },
      },
      ece498CourseEntry: {
        href: courseHref,
        workspaceMetrics,
        workspaceTabScreenshots,
        screenshot: {
          path: path.relative(repoRoot, settingsScreenshotPath).replaceAll("\\", "/"),
          sha256: await sha256(settingsScreenshotPath),
        },
      },
      screenshot: {
        path: path.relative(repoRoot, screenshotPath).replaceAll("\\", "/"),
        sha256: await sha256(screenshotPath),
      },
    });
    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}

const receipt = {
  schemaVersion: 2,
  kind: "field-launcher-ui-layout-verification",
  sourceHead: git("rev-parse", "HEAD"),
  builtEntry: "frontend/field.html",
  builtOutput: "frontend/field-dist",
  browser: "Microsoft Edge (Playwright msedge channel)",
  cases: results,
  payload: {
    inspectedFiles: inspectableFiles.map((file) => path.relative(repoRoot, file).replaceAll("\\", "/")),
    forbiddenPayloadPathTermsAbsent: ["Gazebo", "SITL", "HITL", "simulator"],
    allowedProtocolMetadata: [
      "PX4 controller and firmware compatibility labels",
      "shared launcher localization defaults",
    ],
    sharedThreeScenePresent: true,
    simulatorTermsVisibleInLauncher: false,
  },
  authority: {
    presentationOnly: true,
    grantsHardwareAuthority: false,
    validatedPackCount: 0,
  },
};
const receiptPath = path.join(outputRoot, "field-ui-layout-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  receipt: path.relative(repoRoot, receiptPath).replaceAll("\\", "/"),
  receiptSha256: await sha256(receiptPath),
  cases: results.length,
}, null, 2));
