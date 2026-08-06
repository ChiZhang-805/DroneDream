import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
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
const payloadText = (await Promise.all(inspectableFiles.map((file) => readFile(file, "utf8")))).join("\n");
for (const forbidden of ["PX4 SITL", "Gazebo", "SITL", "HITL"]) {
  assert(!payloadText.toLowerCase().includes(forbidden.toLowerCase()), `Field bundle contains ${forbidden}`);
}
assert(payloadText.includes("field-lightweight"), "Field Settings consumer marker is missing");
assert(payloadText.includes("data-settings-consumer"), "Shared Settings surface is missing");
assert(!distFiles.some((file) => /three|drone-launch-scene/i.test(path.basename(file))),
  "Field bundle unexpectedly contains a Three.js scene chunk");

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
      window.localStorage.setItem("dronedream:field-locale", locale);
    }, testCase.locale);
    const page = await context.newPage();
    await page.goto(`${origin}/field.html`, { waitUntil: "networkidle" });
    await page.locator(".field-app").waitFor();

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
    assert.equal(await page.locator(".field-app").getAttribute("data-authority"), "false");
    assert.equal(await page.locator(".field-app").getAttribute("data-validated-pack-count"), "0");

    await page.getByRole("button", { name: testCase.locale === "en" ? "Settings" : "设置" }).click();
    const dialog = page.locator(".launcher-settings-dialog");
    await dialog.waitFor();
    assert.equal(await dialog.getAttribute("data-settings-consumer"), "field-lightweight");
    assert.equal(await dialog.getAttribute("data-grants-hardware-authority"), "false");

    const panels = [];
    for (const tab of await dialog.getByRole("tab").all()) {
      await tab.click();
      const measurement = await dialog.evaluate((element) => {
        const panel = element.querySelector('.launcher-settings-panel:not([hidden])');
        if (!(panel instanceof HTMLElement)) throw new Error("Active Field Settings panel is missing");
        const bounds = element.getBoundingClientRect();
        return {
          tab: panel.dataset.settingsPanel,
          dialogClientHeight: element.clientHeight,
          dialogScrollHeight: element.scrollHeight,
          panelClientHeight: panel.clientHeight,
          panelScrollHeight: panel.scrollHeight,
          top: bounds.top,
          bottom: bounds.bottom,
        };
      });
      assert(measurement.dialogScrollHeight <= measurement.dialogClientHeight + 1,
        `${testCase.id}: Settings dialog overflowed on ${measurement.tab}`);
      assert(measurement.panelScrollHeight <= measurement.panelClientHeight + 1,
        `${testCase.id}: Settings panel overflowed on ${measurement.tab}`);
      assert(measurement.top >= 0 && measurement.bottom <= testCase.viewport.height + 1,
        `${testCase.id}: Settings dialog escaped the viewport`);
      panels.push(measurement);
    }

    const screenshotPath = path.join(outputRoot, `${testCase.id}-settings.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false });
    results.push({
      ...testCase,
      theme,
      panels,
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
  schemaVersion: 1,
  kind: "field-ui-layout-verification",
  sourceHead: git("rev-parse", "HEAD"),
  donorCommit: "4933e214a57a048099d8f0bdd11c9748b620ac3e",
  builtEntry: "frontend/field.html",
  builtOutput: "frontend/field-dist",
  browser: "Microsoft Edge (Playwright msedge channel)",
  cases: results,
  payload: {
    inspectedFiles: inspectableFiles.map((file) => path.relative(repoRoot, file).replaceAll("\\", "/")),
    forbiddenTermsAbsent: ["PX4 SITL", "Gazebo", "SITL", "HITL"],
    allowedProtocolMetadata: ["PX4 controller and firmware compatibility labels"],
    threeSceneChunkAbsent: true,
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
