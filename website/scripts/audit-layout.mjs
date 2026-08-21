import { createRequire } from "node:module";
import { launchSiteBrowser } from "./playwright-browser.mjs";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [url, widthRaw = "1440", heightRaw = "900", locale = "en", selector = "body"] = process.argv.slice(2);
if (!url) {
  console.error("Usage: node audit-layout.mjs <url> [width] [height] [en|zh-CN] [selector]");
  process.exit(2);
}

const width = Number.parseInt(widthRaw, 10);
const height = Number.parseInt(heightRaw, 10);
const browser = await launchSiteBrowser(chromium, { disableGpu: true });

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
    const isContainedHorizontalOverflow = (element) => {
      let ancestor = element.parentElement;
      while (ancestor && ancestor !== scope.parentElement) {
        const style = getComputedStyle(ancestor);
        const rect = ancestor.getBoundingClientRect();
        if (
          ["auto", "scroll", "hidden", "clip"].includes(style.overflowX) &&
          rect.left >= -1 &&
          rect.right <= document.documentElement.clientWidth + 1
        ) {
          return true;
        }
        ancestor = ancestor.parentElement;
      }
      return false;
    };
    const horizontalOverflowElements = [...scope.querySelectorAll("*")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 1 &&
          (rect.left < -1 || rect.right > document.documentElement.clientWidth + 1) &&
          !isContainedHorizontalOverflow(element)
        );
      })
      .slice(0, 20)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          element: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${
            element.classList.length > 0
              ? `.${[...element.classList].join(".")}`
              : ""
          }`,
          text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 120) ?? "",
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          scrollWidth: element.scrollWidth,
        };
      });

    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
        horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      },
      horizontalOverflowElements,
      headings,
      paragraphs,
      paragraphViolations: paragraphs.filter((paragraph) => paragraph.lines > 1 && paragraph.lastLineRatio < 0.8),
    };
  }, selector);

  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
