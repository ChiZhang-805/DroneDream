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
function parseArguments(argv) {
  const valueOptions = new Set(["--label", "--output", "--port"]);
  const booleanOptions = new Set([
    "--expect-overflow",
    "--expect-job-id-collision",
  ]);
  const parsed = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const separator = argument.indexOf("=");
    const key = separator >= 0 ? argument.slice(0, separator) : argument;
    if (!valueOptions.has(key) && !booleanOptions.has(key)) {
      throw new Error(`Unknown history layout option: ${argument}`);
    }
    if (parsed.has(key)) {
      throw new Error(`Duplicate history layout option: ${key}`);
    }
    if (booleanOptions.has(key)) {
      if (separator >= 0) {
        throw new Error(`Boolean history layout option cannot have a value: ${key}`);
      }
      parsed.set(key, true);
      continue;
    }
    const inlineValue = separator >= 0 ? argument.slice(separator + 1) : null;
    const value = inlineValue ?? argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`History layout option requires a value: ${key}`);
    }
    parsed.set(key, value);
    if (inlineValue === null) index += 1;
  }
  return parsed;
}

const args = parseArguments(process.argv.slice(2));
const expectOverflow = args.has("--expect-overflow");
const expectJobIdCollision = args.has("--expect-job-id-collision");
const label = String(
  args.get("--label")
    || (expectOverflow || expectJobIdCollision ? "before" : "after"),
);
const outputRoot = path.resolve(
  repoRoot,
  String(
    args.get("--output")
      || path.join("artifacts", "test-runs", "history-responsive-overflow", label),
  ),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5189);
const origin = `http://${host}:${port}`;

process.env.VITE_API_BASE_URL = origin;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const cases = [
  { id: "desktop-en", locale: "en", viewport: { width: 1440, height: 1000 } },
  { id: "desktop-zh", locale: "zh-CN", viewport: { width: 1440, height: 1000 } },
  { id: "mobile-en", locale: "en", viewport: { width: 390, height: 844 } },
  { id: "mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
];

const jobs = [
  {
    id: "job_history_alpha_20260728_reflection_causal_intervention_online_evaluation_subject_65a33bbd70f999962afd1bea1e374dcd5e9de460",
    control_version: 4,
    display_name: "Aurora constrained MOBO validation",
    track_type: "circle",
    objective_profile: "robust",
    simulator_backend_requested: "real_cli",
    optimizer_strategy: "constrained_mobo",
    status: "COMPLETED",
    created_at: "2026-07-28T07:00:00Z",
    updated_at: "2026-07-28T07:12:00Z",
  },
  {
    id: "job_history_beta_20260728",
    control_version: 2,
    display_name: "Long-horizon recovery evaluation",
    track_type: "lemniscate",
    objective_profile: "smooth",
    simulator_backend_requested: "mock",
    optimizer_strategy: "optimizer_portfolio",
    status: "FAILED",
    created_at: "2026-07-28T07:20:00Z",
    updated_at: "2026-07-28T07:41:00Z",
  },
  {
    id: "job_history_gamma_20260728",
    control_version: 1,
    display_name: "Cross-scenario robustness sweep",
    track_type: "u_turn",
    objective_profile: "stable",
    simulator_backend_requested: "real_cli",
    optimizer_strategy: "turbo",
    status: "CANCELLED",
    created_at: "2026-07-28T08:00:00Z",
    updated_at: "2026-07-28T08:18:00Z",
  },
];

function git(...gitArgs) {
  return execFileSync("git", gitArgs, {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

async function sha256(relativePath) {
  return sha256File(path.join(repoRoot, relativePath));
}

async function measure(page) {
  return page.evaluate(() => {
    const rect = (element) => {
      if (!(element instanceof Element)) return null;
      const bounds = element.getBoundingClientRect();
      return {
        top: Number(bounds.top.toFixed(2)),
        bottom: Number(bounds.bottom.toFixed(2)),
        left: Number(bounds.left.toFixed(2)),
        right: Number(bounds.right.toFixed(2)),
        width: Number(bounds.width.toFixed(2)),
        height: Number(bounds.height.toFixed(2)),
      };
    };
    const box = (selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        left: Number(bounds.left.toFixed(2)),
        right: Number(bounds.right.toFixed(2)),
        width: Number(bounds.width.toFixed(2)),
        minWidth: style.minWidth,
        overflowX: style.overflowX,
      };
    };
    const action = (name, selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) {
        return { name, selector, exists: false, horizontallyReachable: false };
      }
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        name,
        selector,
        exists: true,
        disabled: element instanceof HTMLButtonElement ? element.disabled : false,
        display: style.display,
        visibility: style.visibility,
        left: Number(rect.left.toFixed(2)),
        right: Number(rect.right.toFixed(2)),
        width: Number(rect.width.toFixed(2)),
        horizontallyReachable:
          rect.width > 0
          && rect.right > 0
          && rect.left < document.documentElement.clientWidth
          && rect.left >= -1
          && rect.right <= document.documentElement.clientWidth + 1,
      };
    };

    const firstRow = document.querySelector(
      ".history-results tbody tr:first-child",
    );
    const jobIdCell = firstRow?.querySelector("td:nth-child(3)");
    const jobIdLink = jobIdCell?.querySelector(".history-job-id-link");
    const jobIdCode = jobIdLink?.querySelector("code");
    const trackTypeCell = firstRow?.querySelector("td:nth-child(4)");
    const jobIdCellRect = rect(jobIdCell);
    const jobIdLinkRect = rect(jobIdLink);
    const jobIdCodeRect = rect(jobIdCode);
    const trackTypeCellRect = rect(trackTypeCell);
    const verticalOverlap =
      jobIdCodeRect
      && trackTypeCellRect
      && jobIdCodeRect.bottom > trackTypeCellRect.top
      && jobIdCodeRect.top < trackTypeCellRect.bottom;
    const jobIdCollision = {
      fullText: jobIdCode?.textContent ?? null,
      cell: jobIdCellRect,
      link: jobIdLinkRect,
      code: jobIdCodeRect,
      trackTypeCell: trackTypeCellRect,
      codeDisplay:
        jobIdCode instanceof HTMLElement
          ? getComputedStyle(jobIdCode).display
          : null,
      codeOverflowX:
        jobIdCode instanceof HTMLElement
          ? getComputedStyle(jobIdCode).overflowX
          : null,
      codeTextOverflow:
        jobIdCode instanceof HTMLElement
          ? getComputedStyle(jobIdCode).textOverflow
          : null,
      codeWhiteSpace:
        jobIdCode instanceof HTMLElement
          ? getComputedStyle(jobIdCode).whiteSpace
          : null,
      containedInJobIdCell:
        Boolean(jobIdCellRect && jobIdCodeRect)
        && jobIdCodeRect.left >= jobIdCellRect.left - 1
        && jobIdCodeRect.right <= jobIdCellRect.right + 1,
      overlapsTrackTypeCell:
        Boolean(jobIdCodeRect && trackTypeCellRect && verticalOverlap)
        && jobIdCodeRect.right > trackTypeCellRect.left + 1,
    };

    const documentWidth = {
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
    return {
      language: document.documentElement.lang,
      document: documentWidth,
      body: box("body"),
      appShell: box(".app-shell"),
      sidebar: box(".app-sidebar"),
      appHeader: box(".app-header"),
      appMain: box(".app-main"),
      historyPage: box(".history-page"),
      historyBody: box(".history-body"),
      resultCard: box(".history-body > .section-card:last-child"),
      resultCardBody: box(
        ".history-body > .section-card:last-child > .section-card-body",
      ),
      historyResults: box(".history-results"),
      historyTable: box(".history-results > table"),
      jobIdCollision,
      actions: [
        action("history navigation", '.app-nav a[href$="/history"]'),
        action("application settings", ".app-header .launcher-settings-button"),
        action("new job", ".history-header .btn-primary"),
        action("clear filters", ".history-clear-filters"),
        action("compare selected", ".history-compare-button"),
      ],
    };
  });
}

function containmentViolations(metrics) {
  const violations = [];
  const exceeds = (entry) =>
    entry && entry.scrollWidth > entry.clientWidth + 1;
  if (metrics.document.scrollWidth !== metrics.document.clientWidth) {
    violations.push(
      `document ${metrics.document.clientWidth}/${metrics.document.scrollWidth}`,
    );
  }
  for (const [name, entry] of [
    ["appMain", metrics.appMain],
    ["historyPage", metrics.historyPage],
    ["historyBody", metrics.historyBody],
    ["resultCard", metrics.resultCard],
    ["resultCardBody", metrics.resultCardBody],
  ]) {
    if (exceeds(entry)) {
      violations.push(`${name} ${entry.clientWidth}/${entry.scrollWidth}`);
    }
  }
  return violations;
}

async function verifyMobileNavigation(page, viewportWidth) {
  const trigger = page.locator(".app-mobile-menu-button");
  const panel = page.locator("#app-mobile-navigation");
  const wasClosed =
    await trigger.isVisible()
    && await trigger.getAttribute("aria-expanded") === "false"
    && await panel.isHidden();
  await trigger.click();
  await panel.waitFor({ state: "visible" });

  const actions = [];
  for (const [name, selector] of [
    ["history navigation", '.app-mobile-menu-panel .app-nav a[href$="/history"]'],
    ["account", ".app-mobile-menu-panel .app-account-button"],
    ["settings", ".app-mobile-menu-panel .app-mobile-settings-entry"],
  ]) {
    const locator = page.locator(selector);
    const bounds = await locator.boundingBox();
    actions.push({
      name,
      selector,
      visible: await locator.isVisible(),
      enabled: await locator.isEnabled(),
      left: bounds ? Number(bounds.x.toFixed(2)) : null,
      right: bounds ? Number((bounds.x + bounds.width).toFixed(2)) : null,
      horizontallyReachable: Boolean(
        bounds
        && bounds.width > 0
        && bounds.x >= -1
        && bounds.x + bounds.width <= viewportWidth + 1,
      ),
    });
  }

  await page.locator(".app-mobile-menu-panel .app-mobile-settings-entry").focus();
  await page.keyboard.press("Escape");
  await panel.waitFor({ state: "hidden" });
  await page.waitForFunction(
    () => document.activeElement?.classList.contains("app-mobile-menu-button"),
    null,
    { timeout: 1_000 },
  ).catch(() => undefined);
  const focusReturned = await trigger.evaluate(
    (element) => document.activeElement === element,
  );
  const closedAfterEscape =
    await trigger.getAttribute("aria-expanded") === "false"
    && await panel.isHidden();
  return {
    wasClosed,
    opened: actions.every(
      (entry) => entry.visible && entry.enabled && entry.horizontallyReachable,
    ),
    actions,
    closedAfterEscape,
    focusReturned,
    passed:
      wasClosed
      && actions.every(
        (entry) => entry.visible && entry.enabled && entry.horizontallyReachable,
      )
      && closedAfterEscape
      && focusReturned,
  };
}

await mkdir(path.dirname(outputRoot), { recursive: true });
try {
  await mkdir(outputRoot);
} catch (error) {
  if (error && typeof error === "object" && error.code === "EEXIST") {
    throw new Error(
      `History layout evidence output already exists; use a new --label: ${outputRoot}`,
      { cause: error },
    );
  }
  throw error;
}
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
});
let browser;
const startedAt = new Date().toISOString();
const results = [];

try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });

  for (const testCase of cases) {
    const apiRequests = [];
    const consoleErrors = [];
    const pageErrors = [];
    const context = await browser.newContext({
      viewport: testCase.viewport,
      deviceScaleFactor: 1,
      colorScheme: "light",
    });
    await context.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
    }, testCase.locale);
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/api/v1/jobs**", async (route) => {
      const request = route.request();
      apiRequests.push({ method: request.method(), url: request.url() });
      if (request.method() !== "GET") {
        await route.fulfill({
          status: 405,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            error: { code: "READ_ONLY_FIXTURE", message: "Writes are forbidden." },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            items: jobs,
            page: 1,
            page_size: 200,
            total: jobs.length,
          },
        }),
      });
    });

    await page.goto(`${origin}/console/history?docsPreview=1`, {
      waitUntil: "networkidle",
    });
    await page.locator(".history-results tbody tr").first().waitFor();
    await page.evaluate(() => {
      const checkboxes = document.querySelectorAll(
        ".history-results tbody input[type=checkbox]",
      );
      for (const checkbox of Array.from(checkboxes).slice(0, 2)) {
        if (checkbox instanceof HTMLInputElement) checkbox.click();
      }
      window.scrollTo(0, 0);
    });
    const initial = await measure(page);
    const violations = containmentViolations(initial);
    const mobileNavigation = testCase.viewport.width <= 520
      ? await verifyMobileNavigation(page, testCase.viewport.width)
      : null;
    await page.screenshot({
      path: path.join(outputRoot, `${testCase.id}-initial.png`),
      fullPage: false,
    });

    const rightEdge = await page.evaluate(() => {
      const resultsElement = document.querySelector(".history-results");
      const lastHeader = document.querySelector(
        ".history-results thead th:last-child",
      );
      const lastDeleteButton = document.querySelector(
        ".history-results tbody tr:first-child td:last-child button",
      );
      if (
        !(resultsElement instanceof HTMLElement)
        || !(lastHeader instanceof HTMLElement)
        || !(lastDeleteButton instanceof HTMLElement)
      ) {
        return null;
      }
      resultsElement.scrollIntoView({ block: "center", inline: "nearest" });
      resultsElement.scrollLeft = resultsElement.scrollWidth;
      const resultRect = resultsElement.getBoundingClientRect();
      const headerRect = lastHeader.getBoundingClientRect();
      const deleteRect = lastDeleteButton.getBoundingClientRect();
      const maxScrollLeft =
        resultsElement.scrollWidth - resultsElement.clientWidth;
      lastDeleteButton.focus();
      return {
        clientWidth: resultsElement.clientWidth,
        scrollWidth: resultsElement.scrollWidth,
        maxScrollLeft,
        scrollLeft: resultsElement.scrollLeft,
        reachedEnd:
          Math.abs(resultsElement.scrollLeft - maxScrollLeft) <= 1,
        lastHeaderVisible:
          headerRect.left >= Math.max(0, resultRect.left) - 1
          && headerRect.right <= Math.min(innerWidth, resultRect.right) + 1,
        lastDeleteVisible:
          deleteRect.left >= Math.max(0, resultRect.left) - 1
          && deleteRect.right <= Math.min(innerWidth, resultRect.right) + 1,
        deleteFocused: document.activeElement === lastDeleteButton,
      };
    });
    await page.screenshot({
      path: path.join(outputRoot, `${testCase.id}-table-right.png`),
      fullPage: false,
    });
    const screenshots = await Promise.all(
      ["initial", "table-right"].map(async (view) => {
        const filename = `${testCase.id}-${view}.png`;
        return {
          filename,
          sha256: await sha256File(path.join(outputRoot, filename)),
        };
      }),
    );

    const unsafeRequests = apiRequests.filter(({ method }) => method !== "GET");
    const expectedLanguage = initial.language === testCase.locale;
    const resultsOwnOverflow =
      initial.historyResults
      && initial.historyResults.scrollWidth > initial.historyResults.clientWidth
      && ["auto", "scroll"].includes(initial.historyResults.overflowX);
    const actionsReachable = mobileNavigation
      ? mobileNavigation.passed
      : initial.actions.every(
        (entry) => entry.exists && entry.horizontallyReachable,
      );
    const commonChecksPassed =
      expectedLanguage
      && unsafeRequests.length === 0
      && consoleErrors.length === 0
      && pageErrors.length === 0;
    const jobIdCollisionReproduced =
      initial.jobIdCollision.fullText === jobs[0].id
      && initial.jobIdCollision.overlapsTrackTypeCell
      && !initial.jobIdCollision.containedInJobIdCell;
    const jobIdContained =
      initial.jobIdCollision.fullText === jobs[0].id
      && initial.jobIdCollision.containedInJobIdCell
      && !initial.jobIdCollision.overlapsTrackTypeCell;
    const overflowReproduced =
      violations.length > 0
      && !resultsOwnOverflow
      && rightEdge?.lastHeaderVisible === false;
    const overflowContained =
      violations.length === 0
      && resultsOwnOverflow
      && actionsReachable
      && rightEdge?.reachedEnd === true
      && rightEdge.lastHeaderVisible
      && rightEdge.lastDeleteVisible
      && rightEdge.deleteFocused;
    const passed =
      commonChecksPassed
      && (
        expectOverflow
          ? overflowReproduced
          : expectJobIdCollision
            ? overflowContained && jobIdCollisionReproduced
            : overflowContained && jobIdContained
      );

    results.push({
      ...testCase,
      expected:
        expectOverflow
          ? "overflow reproduced"
          : expectJobIdCollision
            ? "history overflow contained; long Job ID collision reproduced"
            : "history overflow and long Job ID contained",
      passed,
      containmentViolations: violations,
      initial,
      mobileNavigation,
      rightEdge,
      apiRequests,
      unsafeRequests,
      consoleErrors,
      pageErrors,
      screenshots,
    });
    await context.close();
  }
} finally {
  await browser?.close();
  await server.close();
}

const finishedAt = new Date().toISOString();
const evidence = {
  schemaVersion: 1,
  label,
  expected:
    expectOverflow
      ? "overflow reproduced"
      : expectJobIdCollision
        ? "history overflow contained; long Job ID collision reproduced"
        : "history overflow and long Job ID contained",
  sourceCommit: git("rev-parse", "HEAD"),
  sourceDirty: git("status", "--short") !== "",
  sourceChanges: git("status", "--short").split(/\r?\n/).filter(Boolean),
  stylesheetSha256: await sha256(path.join("frontend", "src", "styles.css")),
  verifierSha256: await sha256(
    path.join("frontend", "scripts", "verify-history-layout.mjs"),
  ),
  command: `npm run test:history-layout -- --label=${label}${
    expectOverflow ? " --expect-overflow" : ""
  }${expectJobIdCollision ? " --expect-job-id-collision" : ""}`,
  browser: {
    name: "Microsoft Edge",
    version: browser?.version() ?? null,
  },
  startedAt,
  finishedAt,
  durationMs: Date.parse(finishedAt) - Date.parse(startedAt),
  passed: results.every((result) => result.passed),
  cases: results,
};
await writeFile(
  path.join(outputRoot, "measurements.json"),
  `${JSON.stringify(evidence, null, 2)}\n`,
  "utf8",
);

for (const result of results) {
  const widths = result.initial;
  process.stdout.write(
    `${result.id}: ${result.passed ? "PASS" : "FAIL"} `
      + `document=${widths.document.clientWidth}/${widths.document.scrollWidth} `
      + `appMain=${widths.appMain?.clientWidth}/${widths.appMain?.scrollWidth} `
      + `history=${widths.historyPage?.clientWidth}/${widths.historyPage?.scrollWidth} `
      + `results=${widths.historyResults?.clientWidth}/${widths.historyResults?.scrollWidth} `
      + `violations=${result.containmentViolations.join(",") || "none"}\n`,
  );
}
process.stdout.write(`Evidence: ${path.join(outputRoot, "measurements.json")}\n`);
if (!evidence.passed) process.exitCode = 1;
