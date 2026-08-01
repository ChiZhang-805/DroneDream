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
  String(args.get("--output") || path.join(
    "frontend",
    "node_modules",
    ".cache",
    "admin-console-layout",
    label,
  )),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5201);
const origin = `http://${host}:${port}`;
const cases = [
  { id: "desktop-en", locale: "en", viewport: { width: 1440, height: 1000 } },
  { id: "desktop-zh", locale: "zh-CN", viewport: { width: 1440, height: 1000 } },
  { id: "mobile-en", locale: "en", viewport: { width: 390, height: 844 } },
  { id: "mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
];

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

function git(...gitArgs) {
  return execFileSync("git", gitArgs, {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function screenshot(page, testCase, tab) {
  const target = path.join(outputRoot, `${testCase.id}-${tab}.png`);
  await page.screenshot({ path: target, fullPage: false });
  return {
    path: path.relative(repoRoot, target).replaceAll("\\", "/"),
    sha256: await sha256File(target),
  };
}

async function geometry(page) {
  return page.evaluate(() => {
    const root = document.querySelector(".admin-page");
    const tabs = Array.from(document.querySelectorAll(".admin-tabs button"));
    const panels = Array.from(document.querySelectorAll(".admin-panel"));
    const bounds = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
      };
    };
    if (!(root instanceof HTMLElement)) {
      throw new Error("Admin page root is missing");
    }
    return {
      root: bounds(root),
      tabs: tabs.map((tab) => ({
        ...bounds(tab),
        label: tab.textContent?.trim() ?? "",
        labelFits: tab.scrollWidth <= tab.clientWidth + 1,
      })),
      panels: panels.map((panel) => ({
        ...bounds(panel),
        contentFits: panel.scrollWidth <= panel.clientWidth + 1,
      })),
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      passwordInputs: document.querySelectorAll('input[type="password"]').length,
    };
  });
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
let failure = null;

try {
  for (const testCase of cases) {
    const context = await browser.newContext({ viewport: testCase.viewport });
    await context.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
    }, testCase.locale);
    await context.route("**/api/v1/**", (route) => route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Offline admin layout fixture" }),
    }));
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const entry = { case: testCase };
    try {
      await page.goto(
        `${origin}/admin?docsPreview=1&adminPreview=1`,
        { waitUntil: "networkidle" },
      );
      await page.locator(".admin-page").waitFor();
      assert.equal(await page.locator('.app-nav a[href="/admin"]').count(), 1);
      assert(await page.locator('.app-nav a[href="/admin"]').evaluate(
        (element) => element.classList.contains("active"),
      ));
      assert.equal(await page.locator(".admin-kpi-grid > article").count(), 8);
      const overviewGeometry = await geometry(page);
      assert.equal(overviewGeometry.documentScrollWidth, overviewGeometry.documentWidth);
      assert.equal(overviewGeometry.tabs.length, 4);
      assert(overviewGeometry.tabs.every((tab) => tab.labelFits));
      assert(overviewGeometry.root.left >= 0);
      assert(overviewGeometry.root.right <= overviewGeometry.documentWidth + 1);
      entry.overview = {
        ...overviewGeometry,
        image: await screenshot(page, testCase, "overview"),
      };
      await page.locator(".admin-overview-grid").scrollIntoViewIfNeeded();
      entry.overview.detailImage = await screenshot(page, testCase, "overview-detail");

      await page.getByRole("button", { name: testCase.locale === "en"
        ? "Model availability"
        : "模型开放状态" }).click();
      assert.equal(await page.locator(".admin-model-list > article").count(), 3);
      assert.equal(await page.locator('.admin-model-list input[type="checkbox"]').count(), 9);
      const modelCardsFit = await page.locator(".admin-model-list > article").evaluateAll(
        (cards) => cards.every((card) => card.scrollWidth <= card.clientWidth + 1),
      );
      assert(modelCardsFit);
      await page.locator(".admin-model-list").scrollIntoViewIfNeeded();
      entry.models = {
        ...(await geometry(page)),
        image: await screenshot(page, testCase, "models"),
      };

      await page.getByRole("button", { name: testCase.locale === "en"
        ? "Users & usage"
        : "用户与用量" }).click();
      await page.locator(".admin-users-panel tbody tr").first().waitFor();
      const userGeometry = await geometry(page);
      assert.equal(userGeometry.passwordInputs, 0);
      assert.equal(userGeometry.documentScrollWidth, userGeometry.documentWidth);
      const userTableScroll = page.locator(".admin-users-panel .admin-table-scroll");
      await userTableScroll.scrollIntoViewIfNeeded();
      entry.users = {
        ...userGeometry,
        image: await screenshot(page, testCase, "users"),
      };
      entry.users.horizontalScroll = await userTableScroll.evaluate((element) => {
        element.scrollLeft = element.scrollWidth;
        return {
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          scrollLeft: element.scrollLeft,
        };
      });
      if (entry.users.horizontalScroll.scrollWidth > entry.users.horizontalScroll.clientWidth + 1) {
        assert(entry.users.horizontalScroll.scrollLeft > 0);
      }
      entry.users.usageImage = await screenshot(page, testCase, "users-usage");

      await page.getByRole("button", { name: testCase.locale === "en"
        ? "Community & audit"
        : "社区与审计" }).click();
      await page.locator(".admin-community-grid section").first()
        .locator("tbody tr").first().waitFor();
      const communityGeometry = await geometry(page);
      assert.equal(communityGeometry.documentScrollWidth, communityGeometry.documentWidth);
      entry.community = {
        ...communityGeometry,
        image: await screenshot(page, testCase, "community"),
      };
      const removeButton = page.locator(".admin-community-grid section").first()
        .locator(".btn-danger").first();
      await removeButton.scrollIntoViewIfNeeded();
      entry.community.actionImage = await screenshot(page, testCase, "community-actions");
      await removeButton.focus();
      assert(await removeButton.evaluate((element) => element === document.activeElement));
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      const confirm = dialog.locator(".btn-danger");
      assert(await confirm.isDisabled());
      await dialog.locator("textarea").fill(
        testCase.locale === "en"
          ? "Confirmed policy violation"
          : "已确认违反社区管理规则",
      );
      assert(await confirm.isEnabled());
      entry.moderationDialog = {
        ...(await geometry(page)),
        moderationReasonRequired: true,
        image: await screenshot(page, testCase, "moderation-dialog"),
      };
      assert.deepEqual(pageErrors, []);
      entry.pageErrors = pageErrors;
      entry.status = "pass";
    } catch (error) {
      entry.pageErrors = pageErrors;
      entry.status = "fail";
      entry.error = error instanceof Error ? error.stack : String(error);
      failure ??= error;
    }
    results.push(entry);
    await context.close();
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
  browser: "Microsoft Edge via Playwright",
  api_mode: "development-only synthetic preview; no API key, backend write, or real user data",
  generated_at: new Date().toISOString(),
  cases: results,
  status: failure ? "fail" : "pass",
};
const receiptPath = path.join(outputRoot, "admin-console-layout-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({
  status: receipt.status,
  receipt: path.relative(repoRoot, receiptPath).replaceAll("\\", "/"),
  receipt_sha256: await sha256File(receiptPath),
  completed_cases: results.length,
}, null, 2)}\n`);
if (failure) throw failure;
