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
const edition = String(args.get("--edition") || "sim");
assert(
  ["universal", "sim", "lab", "autonomy", "field"].includes(edition),
  `Unsupported shared desktop launcher edition: ${edition}`,
);
const desktopOnly = Boolean(args.get("--desktop-only"));
const progressOnly = Boolean(args.get("--progress-only"));
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

const viewports = desktopOnly
  ? [
      { id: "desktop-default", width: 1455, height: 937 },
      { id: "desktop-maximized", width: 1707, height: 1019 },
    ]
  : [
      { id: "desktop", width: 1440, height: 900 },
      { id: "tablet", width: 760, height: 900 },
      { id: "mobile", width: 390, height: 700 },
    ];
const cases = ["en", "zh-CN"].flatMap((locale) =>
  viewports.flatMap((viewport) =>
    ["missing", "ready"].map((scenario) => ({
      id: `${viewport.id}-${locale === "en" ? "en" : "zh"}-${scenario}`,
      locale,
      scenario,
      viewport,
    })),
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
  await context.addInitScript(({ locale, fixture }) => {
    window.localStorage.setItem("drone-dream:locale", locale);
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
            return fixture.scenario === "starting" ? { ...fixture.ready, running: false, ready: false } : fixture.scenario === "missing" ? fixture.missing : fixture.ready;
          }
          if (command === "start_runtime") return fixture.scenario === "starting" ? new Promise(() => {}) : fixture.ready;
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
    fixture: desktopFixture(progressOnly ? "starting" : testCase.scenario),
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
    await page.goto(`${origin}/${edition === "field" ? "field.html" : ""}#/desktop/setup`, { waitUntil: "networkidle" });
    if (progressOnly) {
      await page.goto(origin + '/?docsPreview=1#/desktop/setup', { waitUntil: 'networkidle' });
      await page.locator('.launcher-stage-list').waitFor();
      assert.equal(await page.locator('.launcher-stage-list li').count(), 4);
      const marker = page.locator('.launcher-stage-list li[aria-current="step"] > span');
      assert.equal(await marker.count(), 1);
      const before = await marker.evaluate(el => getComputedStyle(el, '::before').transform);
      await page.waitForTimeout(160);
      const after = await marker.evaluate(el => getComputedStyle(el, '::before').transform);
      assert.notEqual(before, after, 'The active checkpoint must visibly rotate');
      const heading = await page.locator('.launcher-status-card-heading h2').evaluate(el => ({ height: el.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(el).lineHeight), width:el.clientWidth, scrollWidth:el.scrollWidth }));
      assert(heading.height <= heading.lineHeight + 1 && heading.scrollWidth <= heading.width + 1, 'Startup title must fit one line');
      const panel = await page.locator('.launcher-progress-panel').evaluate(el=>({height:el.clientHeight,scrollHeight:el.scrollHeight}));
      assert(panel.scrollHeight <= panel.height + 1, 'All four checkpoints must fit the card');
      await page.screenshot({path:path.join(outputRoot, testCase.id + '-progress.png')});
      return { case: testCase, status:'pass', heading, panel, animated:true };
    }
    const form = page.locator(".launcher-account-form");
    await form.waitFor();
    const before = await page.locator(".launcher-progress-panel").boundingBox();
    assert.equal(await page.getByRole("progressbar").count(), 0);
    const email = form.locator('input[type="email"]');
    const password = form.locator('input[type="password"]');
    await email.fill("launcher-fixture@example.test");
    await password.fill("fixture-password");
    await context.route("https://visual-fixture.supabase.co/**", route => route.fulfill({
      status: 400, contentType: "application/json", body: JSON.stringify({ error: "invalid_grant", error_description: "Invalid login credentials" }),
    }));
    await form.locator('button[type="submit"]').click();
    await form.getByRole("alert").waitFor();
    const after = await page.locator(".launcher-progress-panel").boundingBox();
    assert.deepEqual(after, before, "Authentication errors must not move or resize the card");
    await form.getByRole("tab", { name: testCase.locale === "en" ? "Create account" : "注册", exact: true }).click();
    const registrationBounds = await page.locator(".launcher-progress-panel").boundingBox();
    assert(registrationBounds.height > before.height, "Registration expands for all four fields");
    assert.equal(await form.locator('input:visible').count(), 4);
    assert.equal(await password.first().getAttribute("autocomplete"), "new-password");
    assert.equal(await form.locator('button[type="submit"]').textContent(), testCase.locale === "en" ? "Create account" : "完成注册");
    const registrationSubmit = await form.locator('button[type="submit"]').boundingBox();
    const codeBounds = await form.locator('input[autocomplete="one-time-code"]').boundingBox();
    assert(registrationSubmit.y - codeBounds.y - codeBounds.height <= 16);
    assert(registrationSubmit.y + registrationSubmit.height < registrationBounds.y + registrationBounds.height);
    await page.screenshot({ path: path.join(outputRoot, `${testCase.id}-registration.png`), fullPage: false });
    await form.getByRole("tab", { name: testCase.locale === "en" ? "Sign in" : "登录", exact: true }).click();
    assert.equal(await form.getByRole("button", { name: /browser|浏览器/i }).count(), 0);
    await form.getByRole("button", { name: testCase.locale === "en" ? "Forgot password?" : "忘记密码？" }).click();
    await form.getByRole("heading", { name: testCase.locale === "en" ? "Reset your password" : "找回密码" }).waitFor();
    assert.deepEqual(await page.locator(".launcher-progress-panel").boundingBox(), before);
    await form.getByRole("button", { name: testCase.locale === "en" ? "Back to sign in" : "返回登录" }).click();
    const expectedPercent = null;
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
      launcher: (() => {
        const illustration = document.querySelector(".launcher-flight-illustration");
        const heading = illustration?.querySelector(".launcher-flight-copy h1");
        const bounds = illustration?.getBoundingClientRect();
        const headingBounds = heading?.getBoundingClientRect();
        return {
          illustrationCount: document.querySelectorAll(".launcher-flight-illustration").length,
          imageLoaded: Boolean(illustration?.querySelector("img.launcher-flight-image")?.naturalWidth),
          svgCount: illustration?.querySelectorAll("svg").length ?? 0,
          chromeBackground: getComputedStyle(document.querySelector(".launcher-chrome")).backgroundColor,
          scrollbar: getComputedStyle(document.documentElement).scrollbarWidth,
          canvasCount: document.querySelectorAll(".desktop-launcher canvas").length,
          width: bounds?.width ?? 0,
          height: bounds?.height ?? 0,
          headingLeft: headingBounds?.left ?? -1,
          headingRight: headingBounds?.right ?? -1,
        };
      })(),
    }));
    assert.equal(dimensions.scrollWidth, dimensions.documentWidth);
    assert(dimensions.scrollHeight <= dimensions.documentHeight + 1);
    assert.equal(dimensions.appearance, "light");
    assert.equal(dimensions.brandEdition, edition);
    assert.equal(dimensions.grantsHardwareAuthority, "false");
    assert.equal(dimensions.launcher.illustrationCount, 1);
    assert.equal(dimensions.launcher.svgCount, 0);
    assert.equal(dimensions.launcher.imageLoaded, true);
    assert.equal(dimensions.launcher.chromeBackground, "rgba(0, 0, 0, 0)");
    assert.equal(dimensions.launcher.scrollbar, "none");
    assert.equal(dimensions.launcher.canvasCount, 0,
      `${testCase.id}: desktop startup must not create a WebGL canvas`);
    if (testCase.viewport.width > 850) assert(dimensions.launcher.width > 100 && dimensions.launcher.height > 100,
      `${testCase.id}: lightweight launcher illustration has no visible area`);
    assert.equal(await page.locator(".launcher-flight-copy, .launcher-runtime-indicator").count(), 0);
    const inputBounds = await password.boundingBox();
    const submitBounds = await form.locator('button[type="submit"]').boundingBox();
    assert(submitBounds.y - inputBounds.y - inputBounds.height <= 16, "No blank error row below password");
    const imagePath = path.join(outputRoot, `${testCase.id}.png`);
    await page.screenshot({ path: imagePath, fullPage: false });
    assert.equal(pageErrors.length, 0);

    return {
      case: testCase,
      status: "pass",
      expectedPercent: expectedPercent === null ? null : Number(expectedPercent),
      dimensions,
      launcherRenderer: "approved-raster",
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
  for (const testCase of (progressOnly ? cases.filter(item => item.scenario === "ready") : cases)) {
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
