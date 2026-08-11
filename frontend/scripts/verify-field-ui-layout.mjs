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
  { id: "field-tablet-en", locale: "en", viewport: { width: 760, height: 900 } },
  { id: "field-tablet-zh", locale: "zh-CN", viewport: { width: 760, height: 900 } },
  { id: "field-mobile-en", locale: "en", viewport: { width: 390, height: 620 } },
  { id: "field-mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 620 } },
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
assert(payloadText.includes("field-lightweight"), "Field Settings consumer marker is missing");
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
    results.push({
      ...testCase,
      theme,
      canvasBounds,
      canvasPixelStats,
      entryBounds,
      droneInteraction: "hover-to-starflight",
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
