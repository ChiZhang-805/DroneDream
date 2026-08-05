import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [baseUrlRaw, outputRaw = "edition-chooser-audit"] = process.argv.slice(2);
if (!baseUrlRaw) {
  console.error("Usage: node audit-edition-chooser.mjs <base-url> [output-directory]");
  process.exit(2);
}

const baseUrl = new URL(baseUrlRaw);
if (!["http:", "https:"].includes(baseUrl.protocol)) {
  throw new Error("The audit base URL must use HTTP or HTTPS.");
}

const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const executablePath = edgeCandidates.find(existsSync);
if (!executablePath) throw new Error("Microsoft Edge was not found.");

const outputDirectory = resolve(outputRaw);
mkdirSync(outputDirectory, { recursive: true });

const profiles = [
  { name: "desktop", viewport: { width: 1440, height: 1000 } },
  { name: "mobile", viewport: { width: 390, height: 844 } },
];
const locales = ["en", "zh-CN"];
const results = [];
const failures = [];

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

try {
  for (const locale of locales) {
    for (const profile of profiles) {
      const pageErrors = [];
      const page = await browser.newPage({ viewport: profile.viewport });
      page.on("pageerror", (error) => pageErrors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error") pageErrors.push(message.text());
      });

      await page.goto(baseUrl.href, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.evaluate((nextLocale) => {
        localStorage.setItem("drone-dream:locale", nextLocale);
      }, locale);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.evaluate(() => document.fonts.ready);

      const triggerName = locale === "en" ? "Download" : "下载";
      const dialogName = locale === "en" ? "Choose your edition" : "选择使用版本";
      if (profile.name === "mobile") {
        const navigationName = locale === "en" ? "Open navigation" : "打开导航";
        await page.getByRole("button", { name: navigationName }).click();
      }
      const trigger = page.locator("button:visible").filter({
        hasText: new RegExp(`^${triggerName}`),
      }).first();
      await trigger.focus();
      await trigger.click();
      const dialog = page.getByRole("dialog", { name: dialogName });
      await dialog.waitFor({ state: "visible" });
      await page.waitForTimeout(200);

      const metrics = await page.evaluate(({ profileName }) => {
        const query = (selector) => [...document.querySelectorAll(selector)];
        const rects = (selector) => query(selector).map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            left: rect.left,
            width: rect.width,
            height: rect.height,
          };
        });
        const lineCount = (node) => {
          const range = document.createRange();
          range.selectNodeContents(node);
          const tops = [...range.getClientRects()]
            .filter((rect) => rect.width > 1 && rect.height > 1)
            .map((rect) => Math.round(rect.top));
          return new Set(tops).size;
        };
        const dialogNode = document.querySelector(".site-edition-dialog");
        if (!(dialogNode instanceof HTMLElement)) throw new Error("Edition dialog missing.");
        const dialogRect = dialogNode.getBoundingClientRect();
        const cardRects = rects(".site-edition-card");
        const actionRects = rects(".site-edition-action");
        const audienceLines = query(".site-edition-audience").map(lineCount);
        const editionLinks = query("a").filter((node) =>
          /DroneDream-(Sim|Lab|Field|Universal)-1\.0\.0\.exe/u.test(node.getAttribute("href") ?? "")
        ).length;
        const currentPreviewLinks = query(".site-edition-current a").length;
        const documentWidth = Math.max(
          document.documentElement.scrollWidth,
          document.body?.scrollWidth ?? 0,
        );
        const cardHeightSpread = cardRects.length
          ? Math.max(...cardRects.map(({ height }) => height))
            - Math.min(...cardRects.map(({ height }) => height))
          : Number.POSITIVE_INFINITY;
        const actionBottomSpread = actionRects.length
          ? Math.max(...actionRects.map(({ bottom }) => bottom))
            - Math.min(...actionRects.map(({ bottom }) => bottom))
          : Number.POSITIVE_INFINITY;
        const gridColumns = getComputedStyle(document.querySelector(".site-edition-grid")).gridTemplateColumns;
        return {
          profileName,
          viewportWidth: document.documentElement.clientWidth,
          documentWidth,
          dialog: {
            top: dialogRect.top,
            bottom: dialogRect.bottom,
            width: dialogRect.width,
            clientHeight: dialogNode.clientHeight,
            scrollHeight: dialogNode.scrollHeight,
            overflowY: getComputedStyle(dialogNode).overflowY,
          },
          gridColumns,
          cardCount: cardRects.length,
          cardHeightSpread,
          actionBottomSpread,
          audienceLines,
          editionLinks,
          currentPreviewLinks,
          disabledPrimaryActions: query(".site-edition-action:disabled").length,
          universalRows: query(".site-edition-universal").length,
          disabledUniversalActions: query(".site-edition-universal button:disabled").length,
        };
      }, { profileName: profile.name });

      const prefix = `${locale}-${profile.name}`;
      const screenshotPath = join(outputDirectory, `${prefix}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: false, animations: "disabled" });

      const checks = {
        noDocumentOverflow: metrics.documentWidth <= metrics.viewportWidth + 1,
        threeCards: metrics.cardCount === 3,
        noPlannedDownloadLinks: metrics.editionLinks === 0,
        currentPreviewDiscoverable: metrics.currentPreviewLinks === 1,
        plannedPrimaryActionsDisabled: metrics.disabledPrimaryActions === 3,
        oneUniversalRow: metrics.universalRows === 1,
        plannedUniversalActionDisabled: metrics.disabledUniversalActions === 1,
        audienceSingleLine: metrics.audienceLines.every((count) => count === 1),
        desktopWidth: profile.name !== "desktop"
          || (metrics.dialog.width >= 760 && metrics.dialog.width <= 860),
        desktopEqualCards: profile.name !== "desktop" || metrics.cardHeightSpread <= 1,
        desktopAlignedActions: profile.name !== "desktop" || metrics.actionBottomSpread <= 1,
        desktopThreeColumns: profile.name !== "desktop"
          || metrics.gridColumns.trim().split(/\s+/u).length === 3,
        mobileOneColumn: profile.name !== "mobile"
          || metrics.gridColumns.trim().split(/\s+/u).length === 1,
        mobileBottomSheet: profile.name !== "mobile"
          || Math.abs(metrics.dialog.bottom - profile.viewport.height) <= 1,
        mobileScrollable: profile.name !== "mobile"
          || (metrics.dialog.overflowY === "auto" && metrics.dialog.scrollHeight > metrics.dialog.clientHeight),
        noPageErrors: pageErrors.length === 0,
      };

      for (const [name, passed] of Object.entries(checks)) {
        if (!passed) failures.push(`${prefix}: ${name}`);
      }
      results.push({ locale, profile: profile.name, screenshotPath, metrics, checks, pageErrors });

      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      const focusRestored = await trigger.evaluate((node) => node === document.activeElement);
      if (!focusRestored) failures.push(`${prefix}: focusRestore`);
      results.at(-1).checks.focusRestore = focusRestored;
      await page.close();
    }
  }
} finally {
  await browser.close();
}

const report = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  baseUrl: baseUrl.href,
  passed: failures.length === 0,
  failures,
  results,
};
const reportPath = join(outputDirectory, "edition-chooser-audit.json");
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(reportPath);
if (failures.length > 0) {
  throw new Error(`Edition chooser audit failed:\n${failures.join("\n")}`);
}
