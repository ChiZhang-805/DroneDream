import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const args = new Map(process.argv.slice(2).map((argument) => {
  const [key, ...value] = argument.split("=");
  return [key, value.join("=") || true];
}));
const label = String(args.get("--label") || "working-tree");
const outputRoot = path.resolve(
  repoRoot,
  String(args.get("--output") || path.join("artifacts", "test-runs", `lab-ui-${label}`)),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5198);
const origin = `http://${host}:${port}`;
const cases = [
  { id: "1440-en", locale: "en", viewport: { width: 1440, height: 1000 } },
  { id: "1440-zh", locale: "zh-CN", viewport: { width: 1440, height: 1000 } },
  { id: "760-en", locale: "en", viewport: { width: 760, height: 900 } },
  { id: "760-zh", locale: "zh-CN", viewport: { width: 760, height: 900 } },
  { id: "390-en", locale: "en", viewport: { width: 390, height: 844 } },
  { id: "390-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
];

process.env.VITE_DRONEDREAM_EDITION = "lab";
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";
process.env.VITE_API_BASE_URL = `${origin}/api/v1`;

function git(...gitArgs) {
  return execFileSync("git", gitArgs, { cwd: repoRoot, encoding: "utf8" }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function screenshot(page, testCase, surface) {
  const filePath = path.join(outputRoot, `${testCase.id}-${surface}.png`);
  await page.screenshot({ path: filePath, fullPage: false });
  return {
    path: path.relative(repoRoot, filePath).replaceAll("\\", "/"),
    sha256: await sha256File(filePath),
  };
}

async function assertViewportFits(page, testCase, surface) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    clippedText: Array.from(document.querySelectorAll(
      ".lab-page button, .lab-page strong, .lab-page small, .lab-page label > span",
    )).filter((element) => (
      element instanceof HTMLElement
      && element.offsetParent !== null
      && element.scrollWidth > element.clientWidth + 1
    )).map((element) => element.textContent?.trim()).filter(Boolean),
  }));
  assert.equal(
    metrics.scrollWidth,
    metrics.clientWidth,
    `${testCase.id}/${surface}: document has horizontal overflow`,
  );
  assert.deepEqual(
    metrics.clippedText,
    [],
    `${testCase.id}/${surface}: visible text is clipped`,
  );
}

await mkdir(outputRoot, { recursive: true });
const fixture = await readFile(
  path.join(frontendRoot, "src", "lab", "__fixtures__", "sim-qualification-receipt.fake.json"),
);
const profile = JSON.parse(await readFile(
  path.join(repoRoot, "distribution", "build-profiles", "lab-preview.v1.json"),
  "utf8",
));
const brandManifestPath = path.join(
  repoRoot,
  "distribution",
  "editions",
  "lab",
  "brand-source-manifest.v1.json",
);
const brandManifest = JSON.parse(await readFile(brandManifestPath, "utf8"));
const tauriOverlayPath = path.join(
  repoRoot,
  "desktop",
  "src-tauri",
  "tauri.lab-preview.conf.json",
);
const tauriOverlay = JSON.parse(await readFile(tauriOverlayPath, "utf8"));
assert.equal(brandManifest.displayName, "DroneDream · LAB");
assert.equal(
  brandManifest.sourceAuthority.donorCommit,
  "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
);
assert.deepEqual(brandManifest.theme.palette, ["#A7E84A", "#20C77A", "#087E69"]);
assert.equal(brandManifest.theme.grantsHardwareAuthority, false);
assert.equal(tauriOverlay.productName, brandManifest.displayName);
assert.equal(tauriOverlay.app.windows[0].title, brandManifest.displayName);

for (const asset of brandManifest.assets) {
  const assetPath = path.join(repoRoot, ...asset.repositoryPath.split("/"));
  assert.equal(await sha256File(assetPath), asset.repositorySha256);
}
const installerIcons = [];
for (const iconPath of tauriOverlay.bundle.icon) {
  const absolutePath = path.resolve(path.dirname(tauriOverlayPath), iconPath);
  installerIcons.push({
    path: path.relative(repoRoot, absolutePath).replaceAll("\\", "/"),
    sha256: await sha256File(absolutePath),
  });
}
const commonCoreListing = execFileSync(
  "git",
  [
    "ls-tree",
    "-r",
    "--full-tree",
    profile.commonCore.productSourceCommit,
    "--",
    ...profile.commonCore.paths,
  ],
  { cwd: repoRoot },
);
const commonCoreHash = createHash("sha256")
  .update(commonCoreListing.toString("utf8").trim())
  .digest("hex");
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.config.ts"),
  server: { host, port, strictPort: true },
});
await server.listen();
const browser = await chromium.launch({ headless: true });
const evidence = [];

try {
  for (const testCase of cases) {
    const context = await browser.newContext({ viewport: testCase.viewport });
    const page = await context.newPage();
    await page.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
    }, testCase.locale);
    await page.goto(`${origin}/lab/setup`, { waitUntil: "networkidle" });

    const title = testCase.locale === "en"
      ? "Simulation and hardware laboratory"
      : "仿真与真机实验室";
    await page.getByRole("heading", { name: title }).waitFor();
    const brandImage = page.locator('img[data-brand-edition="lab"]').first();
    await brandImage.waitFor({ state: "attached" });
    const brandImageState = await brandImage.evaluate((image) => ({
      complete: image instanceof HTMLImageElement && image.complete,
      naturalWidth: image instanceof HTMLImageElement ? image.naturalWidth : 0,
      naturalHeight: image instanceof HTMLImageElement ? image.naturalHeight : 0,
    }));
    assert.deepEqual(brandImageState, { complete: true, naturalWidth: 1840, naturalHeight: 340 });
    assert((await page.getByText("DroneDream · LAB", { exact: false }).count()) > 0);
    const palette = await page.locator(".lab-page").evaluate((element) => {
      const style = getComputedStyle(element);
      return ["--dd-brand-start", "--dd-brand-middle", "--dd-brand-end"]
        .map((property) => style.getPropertyValue(property).trim().toUpperCase());
    });
    assert.deepEqual(palette, ["#A7E84A", "#20C77A", "#087E69"]);
    assert.equal(await page.locator("html").getAttribute("lang"), testCase.locale);
    assert.equal(await page.getByText(testCase.locale === "en" ? "0 of 8" : "0 / 8").count(), 1);
    assert.equal(await page.getByText(testCase.locale === "en" ? "DENY" : "拒绝").first().count(), 1);
    await assertViewportFits(page, testCase, "simulation");
    evidence.push(await screenshot(page, testCase, "simulation"));

    const hardwareLabel = testCase.locale === "en" ? "Hardware laboratory" : "真机实验室";
    await page.getByRole("button", { name: new RegExp(hardwareLabel) }).click();
    const disabledActions = page.locator(".lab-hardware-actions button:disabled");
    assert.equal(await disabledActions.count(), 4, `${testCase.id}: hardware actions were exposed`);
    assert.equal(await page.locator('.lab-workspace-switch button[aria-pressed="true"]').count(), 1);
    await page.locator("#lab-panel-setup").scrollIntoViewIfNeeded();
    await assertViewportFits(page, testCase, "hardware");
    evidence.push(await screenshot(page, testCase, "hardware"));

    const setupTab = page.getByRole("tab", { name: testCase.locale === "en" ? "Setup" : "配置" });
    await setupTab.focus();
    await page.keyboard.press("ArrowRight");
    const evidenceTab = page.getByRole("tab", {
      name: testCase.locale === "en" ? "Qualification evidence" : "资格证据",
    });
    assert(await evidenceTab.evaluate((element) => element === document.activeElement));
    await page.locator('.lab-file-button input[type="file"]').setInputFiles({
      name: "sim-qualification-receipt.fake.json",
      mimeType: "application/json",
      buffer: fixture,
    });
    await page.getByText(
      testCase.locale === "en" ? "PREVIEW ONLY" : "仅预览",
      { exact: true },
    ).waitFor();
    assert.equal(await page.getByText("MPC_XY_P").count(), 1);
    await page.locator(".lab-evidence-preview").scrollIntoViewIfNeeded();
    await assertViewportFits(page, testCase, "evidence");
    evidence.push(await screenshot(page, testCase, "evidence"));

    await page.keyboard.press("ArrowRight");
    const confirmLabel = testCase.locale === "en" ? "Confirm hardware action" : "确认真机动作";
    assert(await page.getByRole("button", { name: confirmLabel }).isDisabled());
    assert(await page.locator(".lab-operator-confirmation input").isDisabled());
    assert.equal(await page.locator(".lab-quorum > div > strong").count(), 4);
    await page.locator(".lab-quorum").scrollIntoViewIfNeeded();
    await assertViewportFits(page, testCase, "safety");
    evidence.push(await screenshot(page, testCase, "safety"));

    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}

const report = {
  schemaVersion: 1,
  kind: "dronedream-lab-ui-green-verification",
  sourceCommit: git("rev-parse", "HEAD"),
  sourceStatus: git("status", "--porcelain=v1", "--untracked-files=all") || "clean",
  commonCoreCommit: profile.commonCore.productSourceCommit,
  commonCoreHash,
  editionId: "lab",
  executionAuthority: false,
  validatedVehiclePackCount: 0,
  hardwareActionDecision: "deny",
  brand: {
    displayName: brandManifest.displayName,
    palette: brandManifest.theme.palette,
    grantsHardwareAuthority: brandManifest.theme.grantsHardwareAuthority,
    sourceManifest: {
      path: path.relative(repoRoot, brandManifestPath).replaceAll("\\", "/"),
      sha256: await sha256File(brandManifestPath),
    },
    canonicalDonor: {
      commit: brandManifest.sourceAuthority.donorCommit,
      contract: brandManifest.sourceAuthority.canonicalContract,
      assetManifest: brandManifest.sourceAuthority.canonicalAssetManifest,
      visualReceipt: brandManifest.sourceAuthority.canonicalVisualReceipt,
    },
    exactByteAssets: brandManifest.assets.map((asset) => ({
      role: asset.role,
      path: asset.repositoryPath,
      sha256: asset.repositorySha256,
    })),
    applicationLockupLoaded: true,
    installerOverlay: {
      path: path.relative(repoRoot, tauriOverlayPath).replaceAll("\\", "/"),
      sha256: await sha256File(tauriOverlayPath),
      productName: tauriOverlay.productName,
      icons: installerIcons,
      generatedNsiVerified: false,
    },
  },
  cases: cases.map((testCase) => ({
    ...testCase,
    surfaces: ["simulation", "hardware", "evidence", "safety"],
  })),
  screenshots: evidence,
  sideEffects: {
    installed: false,
    runtimeMigrated: false,
    simulationStarted: false,
    hardwareConnected: false,
    providerCalled: false,
    tauriBuilt: false,
    nsisBuilt: false,
  },
};
const reportPath = path.join(outputRoot, "lab-ui-verification.json");
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  report: path.relative(repoRoot, reportPath).replaceAll("\\", "/"),
  cases: cases.length,
  screenshots: evidence.length,
  hardwareActionDecision: "deny",
}, null, 2));
