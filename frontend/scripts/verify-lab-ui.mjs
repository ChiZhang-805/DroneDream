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
      ".lab-page button, .lab-page strong, .lab-page small, .lab-page label > span, "
        + ".lab-hardware-workspace button, .lab-hardware-workspace strong, "
        + ".lab-hardware-workspace small, .lab-hardware-workspace label > span, "
        + ".experiment-assistant-page button, .experiment-assistant-page strong",
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

async function assertSingleScreen(page, testCase, surface, selector) {
  const metrics = await page.locator(selector).evaluate((element) => ({
    documentClientHeight: document.documentElement.clientHeight,
    documentScrollHeight: document.documentElement.scrollHeight,
    bodyClientHeight: document.body.clientHeight,
    bodyScrollHeight: document.body.scrollHeight,
    surfaceClientHeight: element.clientHeight,
    surfaceScrollHeight: element.scrollHeight,
    children: Array.from(element.children).map((child) => ({
      className: child.className,
      clientHeight: child.clientHeight,
      scrollHeight: child.scrollHeight,
      top: child.getBoundingClientRect().top,
      bottom: child.getBoundingClientRect().bottom,
    })),
  }));
  assert(
    metrics.documentScrollHeight <= metrics.documentClientHeight + 1,
    `${testCase.id}/${surface}: document requires vertical scrolling`,
  );
  assert(
    metrics.bodyScrollHeight <= metrics.bodyClientHeight + 1,
    `${testCase.id}/${surface}: body requires vertical scrolling`,
  );
  assert(
    metrics.surfaceScrollHeight <= metrics.surfaceClientHeight + 1,
    `${testCase.id}/${surface}: primary surface requires vertical scrolling ${JSON.stringify(metrics)}`,
  );
}

async function assertElementInsideViewport(page, testCase, surface, selector) {
  const metrics = await page.locator(selector).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const ancestors = [];
    let current = element.parentElement;
    while (current && ancestors.length < 6) {
      const currentRect = current.getBoundingClientRect();
      ancestors.push({
        className: current.className,
        top: currentRect.top,
        bottom: currentRect.bottom,
        height: currentRect.height,
        clientHeight: current.clientHeight,
        scrollHeight: current.scrollHeight,
      });
      current = current.parentElement;
    }
    const layout = document.querySelector(".field-app-embedded-lab .field-layout");
    const sidebar = document.querySelector(".field-app-embedded-lab .field-sidebar");
    const main = document.querySelector(".field-app-embedded-lab .field-main");
    const layoutMetrics = layout && sidebar && main ? {
      display: getComputedStyle(layout).display,
      rows: getComputedStyle(layout).gridTemplateRows,
      sidebarRow: getComputedStyle(sidebar).gridRow,
      sidebarRect: sidebar.getBoundingClientRect().toJSON(),
      mainRow: getComputedStyle(main).gridRow,
      mainRect: main.getBoundingClientRect().toJSON(),
    } : null;
    return {
      top: rect.top,
      bottom: rect.bottom,
      height: rect.height,
      viewportHeight: document.documentElement.clientHeight,
      ancestors,
      layoutMetrics,
    };
  });
  assert(
    metrics.top >= -1 && metrics.bottom <= metrics.viewportHeight + 1,
    `${testCase.id}/${surface}: ${selector} is outside the viewport ${JSON.stringify(metrics)}`,
  );
}

await mkdir(outputRoot, { recursive: true });
const fixture = await readFile(
  path.join(frontendRoot, "src", "lab", "__fixtures__", "sim-qualification-receipt.fake.json"),
);
const calibrationFixture = await readFile(
  path.join(frontendRoot, "src", "lab", "__fixtures__", "calibration-input.fake.json"),
);
const simBridgeFixture = await readFile(
  path.join(frontendRoot, "src", "lab", "__fixtures__", "sim-qualification-bridge.fake.json"),
);
const fieldBridgeFixture = await readFile(
  path.join(frontendRoot, "src", "lab", "__fixtures__", "field-harness-receipt.fake.json"),
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
  "6de4f1343c0239a916949f0486fa63d3f460d6a8",
);
assert.deepEqual(brandManifest.theme.palette, ["#A7E84A", "#20C77A", "#087E69"]);
assert.equal(brandManifest.theme.grantsHardwareAuthority, false);
assert.equal(tauriOverlay.productName, "DroneDream-Lab");
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
    await page.goto(`${origin}/assistant?docsPreview`, { waitUntil: "networkidle" });
    const assistantTitle = testCase.locale === "en"
      ? "What flight experiment should we build?"
      : "想创建怎样的飞行调优实验？";
    await page.getByRole("heading", { name: assistantTitle }).waitFor();
    const assistant = page.locator('.experiment-assistant-page[data-brand-edition="lab"]');
    assert.equal(await assistant.getAttribute("data-grants-hardware-authority"), "false");
    const assistantPalette = await assistant.evaluate(() => {
      const style = getComputedStyle(document.documentElement);
      return ["--dd-brand-start", "--dd-brand-middle", "--dd-brand-end"]
        .map((property) => style.getPropertyValue(property).trim().toUpperCase());
    });
    assert.deepEqual(assistantPalette, ["#A7E84A", "#20C77A", "#087E69"]);
    assert.equal(await page.locator(".assistant-examples button").count(), 3);
    assert.equal(await page.locator(".assistant-composer").count(), 1);
    await assertViewportFits(page, testCase, "assistant");
    await assertSingleScreen(page, testCase, "assistant", ".experiment-assistant-page");
    evidence.push(await screenshot(page, testCase, "assistant"));

    await page.goto(`${origin}/lab/setup`, { waitUntil: "networkidle" });

    const title = testCase.locale === "en"
      ? "Sim-to-Real calibration laboratory"
      : "Sim-to-Real 校准实验室";
    await page.getByRole("heading", { name: title }).waitFor();
    const brandImage = page.locator('img[data-brand-edition="lab"]').first();
    await brandImage.waitFor({ state: "attached" });
    const brandImageState = await brandImage.evaluate((image) => ({
      complete: image instanceof HTMLImageElement && image.complete,
      naturalWidth: image instanceof HTMLImageElement ? image.naturalWidth : 0,
      naturalHeight: image instanceof HTMLImageElement ? image.naturalHeight : 0,
    }));
    assert.deepEqual(brandImageState, { complete: true, naturalWidth: 2386, naturalHeight: 218 });
    assert((await page.getByText("DroneDream · LAB", { exact: false }).count()) > 0);
    const palette = await page.locator(".lab-page").evaluate((element) => {
      const style = getComputedStyle(element);
      return ["--dd-brand-start", "--dd-brand-middle", "--dd-brand-end"]
        .map((property) => style.getPropertyValue(property).trim().toUpperCase());
    });
    assert.deepEqual(palette, ["#A7E84A", "#20C77A", "#087E69"]);
    const activeNavigationColor = await page.locator(".app-nav a.active").first()
      .evaluate((element) => getComputedStyle(element).color);
    assert.equal(activeNavigationColor, "rgb(8, 126, 105)");
    assert.equal(await page.locator("html").getAttribute("lang"), testCase.locale);
    assert.equal(await page.getByText(testCase.locale === "en" ? "0 of 8" : "0 / 8").count(), 1);
    assert.equal(await page.getByText(testCase.locale === "en" ? "DENY" : "拒绝").first().count(), 1);
    const calibration = page.locator('.lab-calibration[data-brand-edition="lab"]');
    assert.equal(await calibration.getAttribute("data-presentation-only"), "true");
    assert.equal(await calibration.getAttribute("data-grants-hardware-authority"), "false");
    const bridge = page.locator('.lab-evidence-bridge[data-grants-hardware-authority="false"]');
    assert.equal(await bridge.getAttribute("data-presentation-only"), "true");
    const bridgeInputs = bridge.locator('input[type="file"]');
    assert.equal(await bridgeInputs.count(), 2);
    await bridgeInputs.nth(0).setInputFiles({
      name: "sim-qualification-bridge.fake.json",
      mimeType: "application/json",
      buffer: simBridgeFixture,
    });
    await bridgeInputs.nth(1).setInputFiles({
      name: "field-harness-receipt.fake.json",
      mimeType: "application/json",
      buffer: fieldBridgeFixture,
    });
    await page.getByText(
      testCase.locale === "en"
        ? "Candidate lineage matched · normalization required"
        : "候选链路已匹配 · 需要指标归一化",
      { exact: true },
    ).waitFor();
    assert.equal(await bridge.getAttribute("data-bridge-state"), "normalization-required");
    assert.equal(
      await page.getByText(
        testCase.locale === "en" ? "Remaining gates · 5" : "剩余门禁 · 5",
        { exact: true },
      ).count(),
      1,
    );
    await page.locator('.lab-calibration-controls input[type="file"]').setInputFiles({
      name: "calibration-input.fake.json",
      mimeType: "application/json",
      buffer: calibrationFixture,
    });
    await page.getByText("lab_job_fixture_001", { exact: true }).waitFor();
    assert(await page.getByRole("button", { name: testCase.locale === "en" ? "DENY" : "拒绝" }).isDisabled());
    await bridge.scrollIntoViewIfNeeded();
    await assertViewportFits(page, testCase, "calibration");
    evidence.push(await screenshot(page, testCase, "calibration"));

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

    await page.goto(`${origin}/lab/hardware`, { waitUntil: "networkidle" });
    const hardwareWorkspace = page.locator(
      '.lab-hardware-workspace[data-brand-edition="lab"]',
    );
    await hardwareWorkspace.getByRole("heading", { name: hardwareLabel }).waitFor();
    assert.equal(await hardwareWorkspace.getAttribute("data-presentation-only"), "true");
    assert.equal(await hardwareWorkspace.getAttribute("data-grants-hardware-authority"), "false");
    const embeddedHardware = hardwareWorkspace.locator(
      '.field-app[data-brand-edition="lab"][data-authority="false"]',
    );
    assert.equal(await embeddedHardware.getAttribute("data-validated-pack-count"), "0");
    assert.equal(await embeddedHardware.getAttribute("data-quorum"), "missing");
    assert.equal(
      await hardwareWorkspace.getByText("0 validated packs", { exact: true }).count(),
      1,
    );
    await assertViewportFits(page, testCase, "hardware-domain");
    await assertSingleScreen(page, testCase, "hardware-domain", ".lab-hardware-workspace");
    evidence.push(await screenshot(page, testCase, "hardware-domain"));
    if (testCase.viewport.width <= 760) {
      await assertElementInsideViewport(
        page,
        testCase,
        "hardware-domain",
        ".field-assistant-composer",
      );
      const planTab = hardwareWorkspace.getByRole("tab", {
        name: testCase.locale === "en" ? "Experiment plan" : "实验方案",
      });
      await planTab.click();
      assert.equal(
        await hardwareWorkspace.locator(".field-assistant-workspace").getAttribute("data-mobile-panel"),
        "plan",
      );
      assert.equal(await planTab.getAttribute("aria-selected"), "true");
      await assertSingleScreen(page, testCase, "hardware-domain-plan", ".lab-hardware-workspace");
      await assertElementInsideViewport(
        page,
        testCase,
        "hardware-domain-plan",
        ".field-assistant-plan > footer",
      );
      evidence.push(await screenshot(page, testCase, "hardware-domain-plan"));
    }

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
    surfaces: [
      "assistant",
      "calibration",
      "hardware",
      "evidence",
      "safety",
      "hardware-domain",
      ...(testCase.viewport.width <= 760 ? ["hardware-domain-plan"] : []),
    ],
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
