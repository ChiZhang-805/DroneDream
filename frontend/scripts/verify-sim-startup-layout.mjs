import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { PNG } from "pngjs";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const args = new Map(process.argv.slice(2).map((argument) => {
  const [key, ...value] = argument.split("=");
  return [key, value.join("=") || true];
}));
const edition = String(args.get("--edition") || "sim");
assert(
  ["universal", "sim", "lab"].includes(edition),
  `Unsupported shared desktop launcher edition: ${edition}`,
);
const label = String(args.get("--label") || "working-tree");
const outputRoot = path.resolve(
  repoRoot,
  String(args.get("--output") || path.join(
    "frontend",
    "node_modules",
    ".cache",
    "sim-startup-layout",
    label,
  )),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5198);
const origin = `http://${host}:${port}`;

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";
process.env.VITE_DRONEDREAM_EDITION = edition;
process.env.VITE_SUPABASE_URL = "https://visual-fixture.supabase.co";
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_visual_fixture";
const productionEnvironment = await readFile(
  path.join(frontendRoot, ".env.production"),
  "utf8",
);
const runtimeManifestLines = productionEnvironment.match(
  /^VITE_RUNTIME_RELEASE_MANIFEST_URL=(\S+)$/gm,
) ?? [];
assert.equal(runtimeManifestLines.length, 1);
process.env.VITE_RUNTIME_RELEASE_MANIFEST_URL = runtimeManifestLines[0].split("=", 2)[1];

const viewports = [
  { id: "desktop", width: 1440, height: 900 },
  { id: "tablet", width: 760, height: 900 },
  { id: "mobile", width: 390, height: 700 },
];
const cases = ["en", "zh-CN"].flatMap((locale) =>
  ["dark", "light"].flatMap((appearance) =>
    viewports.flatMap((viewport) =>
      ["missing", "ready"].map((scenario) => ({
        id: `${viewport.id}-${locale === "en" ? "en" : "zh"}-${appearance}-${scenario}`,
        locale,
        appearance,
        scenario,
        viewport,
      })),
    ),
  ),
);

const componentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
];

function git(...gitArgs) {
  return execFileSync("git", gitArgs, { cwd: repoRoot, encoding: "utf8" }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function desktopFixture(scenario) {
  const ready = {
    runtimeName: "DroneDreamRuntime",
    installed: true,
    running: true,
    ready: true,
    version: "2026.08",
    dataRoot: "X:\\DroneDreamVisualFixture\\Runtime",
    components: componentIds.map((id) => ({
      id,
      label: id,
      status: "ready",
      required: true,
      version: null,
      detail: null,
    })),
    diagnostics: [],
  };
  const missing = {
    ...ready,
    installed: false,
    running: false,
    ready: false,
    version: null,
    dataRoot: null,
    components: ready.components.map((component) => ({
      ...component,
      status: "missing",
    })),
  };
  return { ready, missing, scenario };
}

async function installDesktopFixture(context, testCase) {
  await context.addInitScript(({ locale, appearance, fixture }) => {
    window.localStorage.setItem("drone-dream:locale", locale);
    window.localStorage.setItem("dronedream:appearance", appearance);
    const calls = [];
    window.__SIM_VISUAL_CALLS__ = calls;
    const readinessTransitions = [];
    window.__SIM_READINESS_TRANSITIONS__ = readinessTransitions;
    const primaryActionAppearances = [];
    window.__SIM_PRIMARY_ACTION_APPEARANCES__ = primaryActionAppearances;
    let lastReadinessPercent = null;
    let lastPrimaryActionSignature = null;
    const recordReadinessPercent = () => {
      const value = document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow");
      if (value !== null && value !== undefined && value !== lastReadinessPercent) {
        lastReadinessPercent = value;
        readinessTransitions.push({ percent: Number(value), atMs: performance.now() });
      }
      const primaryAction = document.querySelector(".launcher-primary-action");
      if (!primaryAction) return;
      const signature = `${value ?? "none"}:${primaryAction.textContent?.trim() ?? ""}`;
      if (signature === lastPrimaryActionSignature) return;
      lastPrimaryActionSignature = signature;
      primaryActionAppearances.push({
        percent: value === null || value === undefined ? null : Number(value),
        text: primaryAction.textContent?.trim() ?? "",
        atMs: performance.now(),
      });
    };
    const readinessObserver = new MutationObserver(recordReadinessPercent);
    readinessObserver.observe(document, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-valuenow"],
    });
    const prerequisites = {
      platform: "windows",
      supported: true,
      windows: {
        caption: "Windows 11 Pro",
        version: "10.0.26100",
        buildNumber: "26100",
        architecture: "64-bit",
      },
      wsl: { executableAvailable: true, distributions: [] },
      memory: { totalBytes: 34359738368, availableBytes: 17179869184 },
      disks: [{
        drive: "C:",
        totalBytes: 1099511627776,
        freeBytes: 536870912000,
        isSystemDrive: true,
      }],
      gpus: [],
      probeErrors: [],
    };
    const installPlan = {
      runtimeName: "DroneDreamRuntime",
      targetRoot: "C:\\DroneDream",
      estimatedDownloadBytes: 8589934592,
      estimatedInstalledBytes: 25769803776,
      requiresAdministrator: true,
      requiresRestart: false,
      canInstall: true,
      blockers: [],
      steps: [
        ["preflight", "Validate prerequisites", null],
        ["enable-wsl", "Enable WSL2", null],
        ["download", "Download runtime", 8589934592],
        ["import", "Import runtime", 25769803776],
        ["smoke-test", "Verify runtime", null],
      ].map(([id, title, estimatedBytes]) => ({
        id,
        title,
        description: String(title),
        requiresAdministrator: id === "enable-wsl",
        destructive: false,
        estimatedBytes,
      })),
    };
    const idleInstall = {
      operationId: null,
      phase: "idle",
      bytesDownloaded: 0,
      bytesTotal: null,
      currentPart: null,
      totalParts: null,
      message: null,
      error: null,
      resumable: false,
      requiresRestart: false,
      targetRoot: null,
      installedVersion: null,
      updatedAt: null,
    };
    const enginePackStatus = {
      supported: true,
      updateRequired: false,
      embeddedPackId: `sha256:${"1".repeat(64)}`,
      embeddedSourceCommit: "2".repeat(40),
      installedPackId: `sha256:${"1".repeat(64)}`,
      installedSourceCommit: "2".repeat(40),
      message: null,
    };
    window.__TAURI__ = {
      core: {
        invoke: async (command) => {
          calls.push(command);
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") {
            return fixture.scenario === "missing" ? fixture.missing : fixture.ready;
          }
          if (command === "start_runtime") return fixture.ready;
          if (command === "get_runtime_install_progress") return idleInstall;
          if (command === "get_runtime_install_plan") return installPlan;
          if (command === "get_installer_runtime_intent") {
            return { status: "none", mode: null, targetRoot: null, message: null };
          }
          if (command === "get_engine_pack_status") return enginePackStatus;
          if (command === "restore_browser_auth_vault") return null;
          if (command === "clear_browser_auth_vault") return true;
          if (command === "get_installer_locale") return locale;
          if (command === "desktop_api_request") {
            return {
              status: 401,
              contentType: "application/json",
              bodyBase64: btoa(JSON.stringify({
                success: false,
                data: null,
                error: {
                  code: "UNAUTHORIZED",
                  message: "Missing bearer token",
                  details: null,
                },
              })),
            };
          }
          if (command.includes("updater") || command.includes("plugin:updater")) return null;
          throw new Error(`Offline startup fixture rejected command: ${command}`);
        },
      },
    };
  }, {
    locale: testCase.locale,
    appearance: testCase.appearance,
    fixture: desktopFixture(testCase.scenario),
  });
}

async function verifyCase(browser, testCase) {
  const context = await browser.newContext({ viewport: testCase.viewport });
  await installDesktopFixture(context, testCase);
  await context.route("**/api/v1/**", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Offline startup visual fixture" }),
  }));
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    // Packaged desktop builds use hash history so a WebView reload never asks a
    // nonexistent HTTP server to resolve an application route. Exercise the
    // same URL shape here instead of accidentally testing the hosted router.
    await page.goto(`${origin}/#/desktop/setup`, { waitUntil: "networkidle" });
    const progress = page.getByRole("progressbar");
    const expectedPercent = testCase.scenario === "ready" ? "100" : null;
    if (expectedPercent !== null) {
      await progress.waitFor();
      try {
        await page.waitForFunction((expected) => {
          return document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") === expected;
        }, expectedPercent, { timeout: 26_000 });
      } catch (error) {
        const diagnosticPath = path.join(outputRoot, `${testCase.id}-progress-diagnostic.png`);
        await page.screenshot({ path: diagnosticPath, fullPage: false });
        const diagnostic = await page.evaluate(() => ({
          value: document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
          calls: window.__SIM_VISUAL_CALLS__,
          text: document.body.innerText,
        }));
        throw new Error(`Startup progress did not reach ${expectedPercent}: ${JSON.stringify(diagnostic)}`, { cause: error });
      }
    }

    const installText = testCase.locale === "en"
      ? "Install DroneDreamRuntime"
      : "安装 DroneDreamRuntime";
    const signInText = {
      universal: ["Sign in and enter DroneDream", "登录并进入 DroneDream"],
      sim: ["Sign in and enter simulation workspace", "登录并进入仿真工作区"],
      lab: ["Sign in and enter laboratory workspace", "登录并进入实验室工作区"],
    }[edition][testCase.locale === "en" ? 0 : 1];
    const install = page.getByRole("button", { name: installText });
    const signIn = page.getByRole("button", { name: signInText });
    const startRuntime = page.getByRole("button", { name: /Start Runtime|启动 Runtime/i });
    const repairRuntime = page.getByRole("button", { name: /Repair Runtime|修复 Runtime/i });

    if (testCase.scenario === "missing") {
      try {
        await install.waitFor({ timeout: 30_000 });
      } catch (error) {
        const diagnosticPath = path.join(outputRoot, `${testCase.id}-diagnostic.png`);
        await page.screenshot({ path: diagnosticPath, fullPage: false });
        const diagnostic = await page.evaluate(() => ({
          progress: document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
          calls: window.__SIM_VISUAL_CALLS__,
          text: document.body.innerText,
        }));
        throw new Error(`Missing Runtime install action did not appear: ${JSON.stringify(diagnostic)}`, { cause: error });
      }
      if (!(await install.isVisible())) {
        const diagnosticPath = path.join(outputRoot, `${testCase.id}-diagnostic.png`);
        await page.screenshot({ path: diagnosticPath, fullPage: false });
        const detailsButton = page.getByRole("button", { name: /View error information|查看错误信息/ });
        if (await detailsButton.count()) await detailsButton.click();
        throw new Error(`Missing Runtime did not expose its install action. Visible text: ${await page.locator("body").innerText()}`);
      }
      if (await progress.count()) {
        const missingPercent = await progress.getAttribute("aria-valuenow");
        assert.notEqual(missingPercent, "100");
      }
      assert.equal(await signIn.count(), 0);
    } else {
      await signIn.waitFor();
      assert.equal(await install.count(), 0);
    }
    assert.equal(await startRuntime.count(), 0);
    assert.equal(await repairRuntime.count(), 0);
    assert.equal(await install.count() > 0 && await signIn.count() > 0, false);

    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.clientHeight,
      scrollHeight: document.documentElement.scrollHeight,
      brandEdition: document.querySelector(".launcher-brand [data-brand-edition]")
        ?.getAttribute("data-brand-edition"),
      appearance: document.documentElement.dataset.ddAppearance,
      grantsHardwareAuthority: document.documentElement.dataset.themeGrantsHardwareAuthority,
      calls: window.__SIM_VISUAL_CALLS__,
      readinessTransitions: window.__SIM_READINESS_TRANSITIONS__,
      primaryActionAppearances: window.__SIM_PRIMARY_ACTION_APPEARANCES__,
      sceneStars: document.querySelector(".drone-launch-scene")?.getAttribute("data-scene-stars"),
      sceneParticles: document.querySelector(".drone-launch-scene")
        ?.getAttribute("data-scene-particles"),
      lightContrast: (() => {
        const runtimeIndicator = document.querySelector(".launcher-runtime-indicator");
        const settingsButton = document.querySelector(".launcher-settings-button");
        const leftHud = document.querySelector(".drone-launch-hud-left");
        const leftHudStrong = leftHud?.querySelector("strong");
        if (!runtimeIndicator || !settingsButton || !leftHud || !leftHudStrong) return null;
        return {
          runtimeIndicatorColor: getComputedStyle(runtimeIndicator).color,
          settingsButtonColor: getComputedStyle(settingsButton).color,
          hudColor: getComputedStyle(leftHud).color,
          hudStrongColor: getComputedStyle(leftHudStrong).color,
          hudBackground: getComputedStyle(leftHud).backgroundImage,
        };
      })(),
    }));
    assert.equal(dimensions.scrollWidth, dimensions.documentWidth);
    assert(dimensions.scrollHeight <= dimensions.documentHeight + 1);
    assert.equal(dimensions.appearance, testCase.appearance);
    assert.equal(dimensions.brandEdition, edition);
    assert.equal(dimensions.grantsHardwareAuthority, "false");
    assert.equal(dimensions.sceneStars, testCase.appearance === "light" ? "false" : "true");
    assert.equal(dimensions.sceneParticles, testCase.appearance === "light" ? "false" : "true");
    if (testCase.appearance === "light") {
      assert(dimensions.lightContrast, `${testCase.id}: light contrast metrics are missing`);
      if (edition === "sim") {
        assert.equal(
          dimensions.lightContrast.runtimeIndicatorColor,
          testCase.scenario === "ready" ? "rgb(16, 40, 59)" : "rgb(23, 51, 75)",
        );
        assert.equal(dimensions.lightContrast.settingsButtonColor, "rgb(23, 51, 75)");
      }
      assert.equal(dimensions.lightContrast.hudColor, "rgba(255, 255, 255, 0.82)");
      assert.equal(dimensions.lightContrast.hudStrongColor, "rgb(255, 255, 255)");
      assert.match(dimensions.lightContrast.hudBackground, /rgba\(7, 42, 86, 0\.96\)/u);
    }
    const imagePath = path.join(outputRoot, `${testCase.id}.png`);
    await page.screenshot({ path: imagePath, fullPage: false });
    const canvasScreenshot = await page.locator(".drone-launch-canvas").screenshot({ type: "png" });
    const canvasFrame = PNG.sync.read(canvasScreenshot);
    const points = [
      [0.03, 0.03], [0.25, 0.08], [0.5, 0.08], [0.75, 0.08], [0.97, 0.03],
      [0.08, 0.4], [0.33, 0.4], [0.5, 0.5], [0.67, 0.4], [0.92, 0.4],
      [0.08, 0.72], [0.33, 0.72], [0.5, 0.72], [0.67, 0.72], [0.92, 0.72],
    ];
    const samples = points.map(([x, y]) => {
      const pixelX = Math.min(canvasFrame.width - 1, Math.floor(canvasFrame.width * x));
      const pixelY = Math.min(canvasFrame.height - 1, Math.floor(canvasFrame.height * y));
      const offset = (pixelY * canvasFrame.width + pixelX) * 4;
      return [...canvasFrame.data.subarray(offset, offset + 4)];
    });
    const canvasPixels = {
      width: canvasFrame.width,
      height: canvasFrame.height,
      samples,
      distinctSamples: new Set(samples.map((sample) => sample.join(","))).size,
      upperBrightRatio: (() => {
        let bright = 0;
        let total = 0;
        const upperLimit = Math.max(1, Math.floor(canvasFrame.height * 0.3));
        for (let y = 0; y < upperLimit; y += 12) {
          for (let x = 0; x < canvasFrame.width; x += 12) {
            const offset = (y * canvasFrame.width + x) * 4;
            total += 1;
            if (
              canvasFrame.data[offset] >= 245
              && canvasFrame.data[offset + 1] >= 245
              && canvasFrame.data[offset + 2] >= 245
            ) bright += 1;
          }
        }
        return total > 0 ? bright / total : 0;
      })(),
    };
    assert(canvasPixels.width > 100 && canvasPixels.height > 100);
    assert(canvasPixels.distinctSamples >= 6, `${testCase.id}: 3D canvas appears blank`);
    if (testCase.appearance === "light") {
      assert(canvasPixels.upperBrightRatio >= 0.6,
        `${testCase.id}: light scene is not predominantly white: ${canvasPixels.upperBrightRatio}`);
    }
    if (testCase.scenario === "ready") {
      assert.equal(
        dimensions.calls.filter((command) => command === "start_runtime").length,
        1,
        `${testCase.id}: an installed Runtime must auto-start exactly once`,
      );
      assert.equal(
        dimensions.readinessTransitions.at(-1)?.percent,
        100,
        `${testCase.id}: an already-ready Runtime did not render 100% readiness`,
      );
      assert.equal(
        dimensions.readinessTransitions.some((transition) => transition.percent === 99),
        false,
        `${testCase.id}: the prohibited 99% action point was rendered`,
      );
      for (let index = 1; index < dimensions.readinessTransitions.length; index += 1) {
        assert(
          dimensions.readinessTransitions[index].percent
            >= dimensions.readinessTransitions[index - 1].percent,
          `${testCase.id}: evidence-driven readiness must never move backwards`,
        );
      }
      assert(
        dimensions.readinessTransitions.every((transition) =>
          transition.percent === 0 ||
          (transition.percent >= 20 && transition.percent <= 100)),
        `${testCase.id}: readiness rendered a value without completed native evidence`,
      );
      assert(
        dimensions.primaryActionAppearances.length >= 1,
        `${testCase.id}: sign-in action never appeared`,
      );
      assert(
        dimensions.primaryActionAppearances.every((appearance) => appearance.percent === 100),
        `${testCase.id}: a primary action appeared before 100% readiness`,
      );
    } else {
      assert.equal(dimensions.calls.includes("start_runtime"), false);
      assert.equal(
        dimensions.readinessTransitions.some((transition) => transition.percent === 100),
        false,
      );
      assert(
        dimensions.primaryActionAppearances.every((appearance) => appearance.percent === 0),
        `${testCase.id}: the Runtime install action must remain at 0%`,
      );
    }
    assert.equal(pageErrors.length, 0);

    return {
      case: testCase,
      status: "pass",
      expectedPercent: expectedPercent === null ? null : Number(expectedPercent),
      dimensions,
      canvasPixels,
      image: {
        path: path.relative(repoRoot, imagePath).replaceAll("\\", "/"),
        sha256: await sha256File(imagePath),
      },
    };
  } finally {
    await context.close();
  }
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  root: frontendRoot,
  server: { host, port, strictPort: true },
  logLevel: "error",
});
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];
let failure;

try {
  for (const testCase of cases) {
    try {
      results.push(await verifyCase(browser, testCase));
    } catch (error) {
      results.push({ case: testCase, status: "fail", error: String(error?.stack ?? error) });
      failure = error;
      break;
    }
  }
} finally {
  await browser.close();
  await server.close();
}

const receipt = {
  schema_version: 1,
  edition,
  subject_commit: git("rev-parse", "HEAD"),
  subject_dirty: Boolean(git("status", "--short")),
  branch: git("branch", "--show-current"),
  browser: "Microsoft Edge (Playwright msedge channel)",
  api_mode: "offline fixtures only; native Runtime and backend not started",
  generated_at: new Date().toISOString(),
  cases: results,
  status: failure ? "fail" : "pass",
};
const receiptPath = path.join(outputRoot, "sim-startup-layout-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
const receiptSha256 = await sha256File(receiptPath);
console.log(JSON.stringify({
  status: receipt.status,
  receipt: path.relative(repoRoot, receiptPath).replaceAll("\\", "/"),
  receipt_sha256: receiptSha256,
  completed_cases: results.length,
}, null, 2));
if (failure) throw failure;
