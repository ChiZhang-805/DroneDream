import { existsSync } from "node:fs";
import { createRequire } from "node:module";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [url, widthRaw = "1440", heightRaw = "900", locale = "en", selector = "body"] = process.argv.slice(2);
if (!url) {
  console.error("Usage: node audit-layout.mjs <url> [width] [height] [en|zh-CN] [selector]");
  process.exit(2);
}

const width = Number.parseInt(widthRaw, 10);
const height = Number.parseInt(heightRaw, 10);
const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const executablePath = edgeCandidates.find(existsSync);
if (!executablePath) throw new Error("Microsoft Edge was not found.");

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

try {
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  if (locale === "en" || locale === "zh-CN") {
    await page.evaluate((nextLocale) => localStorage.setItem("drone-dream:locale", nextLocale), locale);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
  }
  await page.waitForSelector(selector, { state: "visible", timeout: 60_000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(750);

  const report = await page.evaluate((scopeSelector) => {
    const scope = document.querySelector(scopeSelector);
    if (!(scope instanceof HTMLElement)) throw new Error(`Selector not found: ${scopeSelector}`);

    const lineFragments = (element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const fragments = [...range.getClientRects()]
        .filter((rect) => rect.width > 1 && rect.height > 1)
        .sort((left, right) => (left.top - right.top) || (left.left - right.left));
      const lines = [];
      for (const fragment of fragments) {
        const line = lines.find((candidate) => Math.abs(candidate.top - fragment.top) < 2);
        if (line) {
          line.left = Math.min(line.left, fragment.left);
          line.right = Math.max(line.right, fragment.right);
        } else {
          lines.push({ top: fragment.top, left: fragment.left, right: fragment.right });
        }
      }
      return lines;
    };

    const paragraphs = [...scope.querySelectorAll("p")]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        const isCompositeMetric = element.querySelector("strong") !== null;
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width >= 120 &&
          element.textContent?.trim() &&
          !isCompositeMetric
        );
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const lines = lineFragments(element);
        const last = lines.at(-1);
        return {
          text: element.textContent.trim().replace(/\s+/g, " ").slice(0, 180),
          lines: lines.length,
          lastLineRatio: last ? Number(((last.right - last.left) / rect.width).toFixed(3)) : 0,
          width: Math.round(rect.width),
        };
      });

    const headings = [...scope.querySelectorAll("h1, h2")]
      .filter((element) => element.getBoundingClientRect().width > 0)
      .map((element) => ({
        text: element.textContent.trim().replace(/\s+/g, " "),
        lines: lineFragments(element).length,
      }));

    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
        horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      },
      headings,
      paragraphs,
      paragraphViolations: paragraphs.filter((paragraph) => paragraph.lines > 1 && paragraph.lastLineRatio < 0.8),
    };
  }, selector);

  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
