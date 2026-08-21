import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { launchSiteBrowser } from "./playwright-browser.mjs";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [url, widthRaw = "1440", heightRaw = "1000", minimumFillRaw = "0.80", output = "", modeRaw = "full"] = process.argv.slice(2);
if (!url) {
  console.error("Usage: node audit-site-typography.mjs <url> [width] [height] [minimum-fill] [output.json] [full|layout-only]");
  process.exit(2);
}

const strictPositiveInteger = (value) => /^\d+$/u.test(value) && Number(value) > 0;
const strictFraction = (value) => /^(?:0(?:\.\d+)?|1(?:\.0+)?)$/u.test(value);
if (!strictPositiveInteger(widthRaw) || !strictPositiveInteger(heightRaw) || !strictFraction(minimumFillRaw)) {
  throw new Error("Width and height must be positive integers; minimum-fill must be a number from 0 to 1.");
}
if (modeRaw !== "full" && modeRaw !== "layout-only") throw new Error("Audit mode must be full or layout-only.");

const width = Number(widthRaw);
const height = Number(heightRaw);
const minimumFill = Number(minimumFillRaw);
const checkTypography = modeRaw === "full";
const browser = await launchSiteBrowser(chromium);
const diagnostics = [];

const waitForStableLayout = async (page) => {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolveFrame) => requestAnimationFrame(() => requestAnimationFrame(resolveFrame)));
  });
};

const collectVisibleCopy = async (page) => page.evaluate(() => {
  const round = (value) => Math.round(value * 1000) / 1000;
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    if (node.closest('[aria-hidden="true"], [hidden]')) return false;
    const capabilityFace = node.closest(".site-capability-face");
    if (capabilityFace) {
      const flipped = capabilityFace.closest(".site-capability-card")?.classList.contains("is-flipped");
      if (capabilityFace.classList.contains("site-capability-front") && flipped) return false;
      if (capabilityFace.classList.contains("site-capability-back") && !flipped) return false;
    }
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && Number.parseFloat(style.opacity || "1") > 0.001
      && rect.width > 0
      && rect.height > 0;
  };
  const textFragments = (node) => {
    const fragments = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let textNode = walker.nextNode(); textNode; textNode = walker.nextNode()) {
      if (!textNode.textContent?.trim() || !isVisible(textNode.parentElement)) continue;
      const range = document.createRange();
      range.selectNodeContents(textNode);
      fragments.push(...Array.from(range.getClientRects())
        .filter((rect) => rect.width > 0.5 && rect.height > 0.5));
    }
    return fragments.sort((a, b) => a.top - b.top || a.left - b.left);
  };
  const metrics = {};
  for (const node of document.querySelectorAll("[data-copy-block][data-copy-id]")) {
    if (!isVisible(node)) continue;
    const fragments = textFragments(node);
    const lines = [];
    for (const fragment of fragments) {
      let line = lines.find((candidate) => Math.abs(candidate.top - fragment.top) <= 2);
      if (!line) {
        line = { top: fragment.top, left: fragment.left, right: fragment.right };
        lines.push(line);
      } else {
        line.left = Math.min(line.left, fragment.left);
        line.right = Math.max(line.right, fragment.right);
      }
    }
    const widths = lines.map((line) => line.right - line.left);
    const style = getComputedStyle(node);
    const horizontalInsets = Number.parseFloat(style.borderLeftWidth || "0")
      + Number.parseFloat(style.borderRightWidth || "0")
      + Number.parseFloat(style.paddingLeft || "0")
      + Number.parseFloat(style.paddingRight || "0");
    // Use the paragraph's actual CSS content box, not its longest rendered line.
    // This enforces the product rule that the final line leaves no more than the
    // configured fraction of the available paragraph width empty.
    const contentWidth = Math.max(1, node.getBoundingClientRect().width - horizontalInsets);
    const longestWidth = Math.max(0, ...widths);
    const lastWidth = widths.at(-1) ?? 0;
    metrics[node.dataset.copyId] = {
      text: (node.textContent || "").replace(/\s+/g, " ").trim(),
      lines: lines.length,
      fill: round(lastWidth / contentWidth),
      contentWidth: round(contentWidth),
      longestWidth: round(longestWidth),
      lastWidth: round(lastWidth),
    };
  }
  return metrics;
});

const collectLayout = async (page, locale, state) => page.evaluate(({ activeLocale, activeState }) => {
  const tolerance = 2;
  const round = (value) => Math.round(value * 10) / 10;
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    if (node.closest('[aria-hidden="true"], [hidden]')) return false;
    const capabilityFace = node.closest(".site-capability-face");
    if (capabilityFace) {
      const flipped = capabilityFace.closest(".site-capability-card")?.classList.contains("is-flipped");
      if (capabilityFace.classList.contains("site-capability-front") && flipped) return false;
      if (capabilityFace.classList.contains("site-capability-back") && !flipped) return false;
    }
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && Number.parseFloat(style.opacity || "1") > 0.001
      && rect.width > 0
      && rect.height > 0;
  };
  const labelFor = (node, index) => node.dataset.copyId
    || node.id
    || node.getAttribute("aria-label")
    || node.classList[0]
    || `${node.tagName.toLowerCase()}-${index}`;
  const overflowClips = (value) => value === "hidden" || value === "clip";
  const allowsHorizontalScroll = (node) => {
    const style = getComputedStyle(node);
    return (style.overflowX === "auto" || style.overflowX === "scroll")
      && node.scrollWidth > node.clientWidth + tolerance;
  };
  const hasHorizontalScrollAncestor = (node) => {
    let ancestor = node.parentElement;
    while (ancestor && ancestor !== document.body) {
      if (allowsHorizontalScroll(ancestor)) return true;
      ancestor = ancestor.parentElement;
    }
    return false;
  };
  const violations = [];
  const regions = [];
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
  const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
  if (documentWidth > viewportWidth + tolerance) {
    violations.push(`document: horizontal overflow ${round(documentWidth - viewportWidth)}px`);
  }

  const criticalSelectors = [
    ".site-header",
    ".site-hero-copy",
    ".site-section",
    ".site-product-demo",
    ".site-workflow-visual",
    ".site-capability-grid",
    ".site-capability-card",
    ".site-manual-layout",
    ".site-download-card",
    ".site-download-copy",
    ".site-release-card",
    ".site-footer > .site-shell",
    ".site-manual-dialog",
    ".site-manual-dialog-body",
  ];
  const criticalNodes = Array.from(document.querySelectorAll(criticalSelectors.join(",")))
    .filter(isVisible);
  criticalNodes.forEach((node, index) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const overflowX = node.scrollWidth - node.clientWidth;
    const overflowY = node.scrollHeight - node.clientHeight;
    const name = labelFor(node, index);
    regions.push({
      name,
      width: round(rect.width),
      height: round(rect.height),
      overflowX: round(Math.max(0, overflowX)),
      overflowY: round(Math.max(0, overflowY)),
      cssOverflowX: style.overflowX,
      cssOverflowY: style.overflowY,
    });
    // The download card deliberately clips a large, absolutely positioned
    // radial glow. Audit its two content columns instead so decoration cannot
    // masquerade as a customer-visible horizontal overflow.
    const hasDecorativeOverflow = node.matches(".site-download-card");
    const isHorizontalScroller = allowsHorizontalScroll(node);
    const isInsideHorizontalScroller = hasHorizontalScrollAncestor(node);
    if (!hasDecorativeOverflow && !isHorizontalScroller && overflowX > tolerance) {
      violations.push(`${name}: horizontal content overflow ${round(overflowX)}px`);
    }
    if (overflowClips(style.overflowY) && overflowY > tolerance) {
      violations.push(`${name}: vertically clipped content ${round(overflowY)}px`);
    }
    if (!isInsideHorizontalScroller
      && (rect.left < -tolerance || rect.right > viewportWidth + tolerance)) {
      violations.push(`${name}: extends outside viewport horizontally (${round(rect.left)}..${round(rect.right)}px)`);
    }
    if (node.matches(".site-section") && overflowClips(style.overflowY)) {
      const shell = node.querySelector(":scope > .site-shell");
      if (shell && isVisible(shell)) {
        const shellRect = shell.getBoundingClientRect();
        if (shellRect.top < rect.top - tolerance || shellRect.bottom > rect.bottom + tolerance) {
          violations.push(`${name}: main shell is clipped by section bounds`);
        }
      }
    }
  });

  const requiredHeaderSelectors = [
    ".site-header",
    ".site-brand",
    ".site-account-button",
    ".site-language",
    viewportWidth <= 1050 ? ".site-menu-button" : ".site-header-download",
  ];
  for (const selector of requiredHeaderSelectors) {
    const node = document.querySelector(selector);
    if (!(node instanceof HTMLElement) || !isVisible(node)) {
      violations.push(`${selector}: required header control is not visible`);
      continue;
    }
    const rect = node.getBoundingClientRect();
    if (rect.left < -tolerance || rect.right > viewportWidth + tolerance) {
      violations.push(
        `${selector}: required header control is outside the viewport (${round(rect.left)}..${round(rect.right)}px)`,
      );
    }
    const header = document.querySelector(".site-header");
    if (header instanceof HTMLElement) {
      const headerRect = header.getBoundingClientRect();
      if (rect.top < headerRect.top - tolerance || rect.bottom > headerRect.bottom + tolerance) {
        violations.push(`${selector}: required header control is clipped by the header`);
      }
    }
  }

  const copyAndHeadings = Array.from(document.querySelectorAll(
    "[data-copy-block], h1, h2, h3, [role=heading]",
  )).filter(isVisible);
  copyAndHeadings.forEach((node, index) => {
    const name = labelFor(node, index);
    const rect = node.getBoundingClientRect();
    if (node.scrollWidth > node.clientWidth + tolerance) {
      violations.push(`${name}: text overflows its own box by ${round(node.scrollWidth - node.clientWidth)}px`);
    }
    let ancestor = node.parentElement;
    let hasHorizontalScrollContainer = false;
    let hasVerticalScrollContainer = false;
    while (ancestor && ancestor !== document.body) {
      if (!isVisible(ancestor)) break;
      const ancestorStyle = getComputedStyle(ancestor);
      const ancestorRect = ancestor.getBoundingClientRect();
      const clippedX = !hasHorizontalScrollContainer
        && overflowClips(ancestorStyle.overflowX)
        && (rect.left < ancestorRect.left - tolerance || rect.right > ancestorRect.right + tolerance);
      const clippedY = !hasVerticalScrollContainer
        && overflowClips(ancestorStyle.overflowY)
        && (rect.top < ancestorRect.top - tolerance || rect.bottom > ancestorRect.bottom + tolerance);
      if (clippedX || clippedY) {
        violations.push(`${name}: clipped by ${labelFor(ancestor, index)}${clippedX ? " horizontally" : " vertically"}`);
        break;
      }
      if ((ancestorStyle.overflowX === "auto" || ancestorStyle.overflowX === "scroll")
        && ancestor.scrollWidth > ancestor.clientWidth + tolerance) hasHorizontalScrollContainer = true;
      if ((ancestorStyle.overflowY === "auto" || ancestorStyle.overflowY === "scroll")
        && ancestor.scrollHeight > ancestor.clientHeight + tolerance) hasVerticalScrollContainer = true;
      ancestor = ancestor.parentElement;
    }
    // A critical scroll container reports one actionable overflow finding of
    // its own. Avoid flooding the report with every descendant that is merely
    // outside the container's current horizontal scroll position.
    if (!hasHorizontalScrollContainer
      && (rect.left < -tolerance || rect.right > viewportWidth + tolerance)) {
      violations.push(`${name}: text extends outside viewport horizontally`);
    }
  });

  return { locale: activeLocale, state: activeState, viewportWidth, documentWidth, regions, violations };
}, { activeLocale: locale, activeState: state });

async function mergeVisibleCopy(page, target) {
  Object.assign(target, await collectVisibleCopy(page));
}

async function addLayoutSnapshot(page, snapshots, locale, state) {
  await waitForStableLayout(page);
  snapshots.push(await collectLayout(page, locale, state));
}

async function collectLocale(page, locale) {
  await page.evaluate((nextLocale) => localStorage.setItem("drone-dream:locale", nextLocale), locale);
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForSelector("#home", { state: "visible", timeout: 60_000 });
  await waitForStableLayout(page);
  const copy = {};
  const layout = [];
  await mergeVisibleCopy(page, copy);
  await addLayoutSnapshot(page, layout, locale, "initial");

  const tabs = page.locator(".site-phase-tabs [role=tab]");
  for (let index = 0; index < await tabs.count(); index += 1) {
    const tab = tabs.nth(index);
    await tab.click();
    await tab.waitFor({ state: "visible" });
    await page.waitForFunction((tabId) => document.getElementById(tabId)?.getAttribute("aria-selected") === "true", await tab.getAttribute("id"));
    await waitForStableLayout(page);
    await mergeVisibleCopy(page, copy);
    await addLayoutSnapshot(page, layout, locale, `phase-${index}`);
  }

  const cards = page.locator(".site-capability-card");
  for (let cardIndex = 0; cardIndex < await cards.count(); cardIndex += 1) {
    const card = cards.nth(cardIndex);
    const front = card.locator(".site-capability-front");
    await front.click();
    await page.waitForFunction((cardNumber) => {
      const candidate = document.querySelectorAll(".site-capability-card")[cardNumber];
      return candidate?.classList.contains("is-flipped")
        && candidate.querySelector(".site-capability-back")?.getAttribute("aria-hidden") === "false";
    }, cardIndex);
    await waitForStableLayout(page);
    const counter = await card.locator(".site-capability-back nav > span").textContent();
    const detailCount = Number(counter?.split("/")[1]?.trim() || 0);
    for (let detailIndex = 0; detailIndex < detailCount; detailIndex += 1) {
      await mergeVisibleCopy(page, copy);
      await addLayoutSnapshot(page, layout, locale, `capability-${cardIndex}-detail-${detailIndex}`);
      if (detailIndex + 1 < detailCount) {
        await card.locator(".site-capability-back nav button:last-child").click();
        await waitForStableLayout(page);
      }
    }
    await card.locator(".site-capability-flip-back").click();
    await page.waitForFunction((cardNumber) => !document.querySelectorAll(".site-capability-card")[cardNumber]?.classList.contains("is-flipped"), cardIndex);
  }

  const menuButton = page.locator(".site-menu-button");
  if (await menuButton.isVisible()) {
    await menuButton.click();
    await page.waitForFunction(() => document.querySelector(".site-menu-button")?.getAttribute("aria-expanded") === "true");
    await addLayoutSnapshot(page, layout, locale, "mobile-menu");
    await page.keyboard.press("Escape");
  }

  const manualLink = page.locator('.site-manual-links a[href="/manual/"]');
  await manualLink.waitFor({ state: "visible" });
  await addLayoutSnapshot(page, layout, locale, "manual-links");
  return { copy, layout };
}

try {
  const page = await browser.newPage({ viewport: { width, height } });
  await page.emulateMedia({ reducedMotion: "reduce" });
  page.on("pageerror", (error) => diagnostics.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) diagnostics.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText ?? "request failed";
    // Locale switches and route changes can cancel an in-flight favicon request.
    // Chromium reports that expected navigation cleanup as ERR_ABORTED.
    if (failure === "net::ERR_ABORTED") return;
    if (!request.url().endsWith("/downloads/latest.json")) {
      diagnostics.push(`${request.url()}: ${failure}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400 && !response.url().endsWith("/downloads/latest.json")) {
      diagnostics.push(`${response.url()}: HTTP ${response.status()}`);
    }
  });
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  const results = {
    en: await collectLocale(page, "en"),
    "zh-CN": await collectLocale(page, "zh-CN"),
  };
  const locales = {
    en: results.en.copy,
    "zh-CN": results["zh-CN"].copy,
  };
  const ids = [...new Set([...Object.keys(locales.en), ...Object.keys(locales["zh-CN"])])].sort();
  const violations = [];
  const rows = ids.map((id) => {
    const en = locales.en[id];
    const zh = locales["zh-CN"][id];
    if (checkTypography && (!en || !zh)) violations.push(`${id}: missing in ${en ? "zh-CN" : "en"}`);
    if (checkTypography && en?.lines >= 2 && en.fill + Number.EPSILON < minimumFill) violations.push(`${id}: en final line ${Math.round(en.fill * 100)}% of available width`);
    if (checkTypography && zh?.lines >= 2 && zh.fill + Number.EPSILON < minimumFill) violations.push(`${id}: zh-CN final line ${Math.round(zh.fill * 100)}% of available width`);
    if (checkTypography && en && zh && en.lines !== zh.lines) violations.push(`${id}: line mismatch en=${en.lines}, zh-CN=${zh.lines}`);
    return {
      id,
      en: en ? `${en.lines} lines / ${Math.round(en.fill * 100)}%` : "missing",
      zh: zh ? `${zh.lines} lines / ${Math.round(zh.fill * 100)}%` : "missing",
    };
  });

  const layoutSnapshots = [...results.en.layout, ...results["zh-CN"].layout];
  const layoutViolationStates = new Map();
  for (const snapshot of layoutSnapshots) {
    for (const message of snapshot.violations) {
      const key = `${snapshot.locale}: ${message}`;
      const states = layoutViolationStates.get(key) ?? [];
      states.push(snapshot.state);
      layoutViolationStates.set(key, states);
    }
  }
  const layoutViolations = [...layoutViolationStates.entries()].map(([message, states]) => {
    const uniqueStates = [...new Set(states)];
    const suffix = uniqueStates.length > 1 ? ` (seen in ${uniqueStates.length} states; first: ${uniqueStates[0]})` : ` (${uniqueStates[0]})`;
    return `${message}${suffix}`;
  });
  violations.push(...layoutViolations);
  if (diagnostics.length > 0) violations.push(...diagnostics.map((message) => `page: ${message}`));
  const report = {
    url,
    viewport: { width, height },
    minimumFill,
    mode: modeRaw,
    rows,
    violations,
    locales,
    layout: layoutSnapshots,
    layoutViolations,
  };
  console.table(rows);
  if (output) {
    const outputPath = resolve(output);
    mkdirSync(dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  if (violations.length > 0) {
    console.error(`Website audit failed (${violations.length}):\n- ${violations.join("\n- ")}`);
    process.exitCode = 1;
  } else {
    console.log(checkTypography
      ? `Website audit passed at ${width}x${height}; final-line threshold ${Math.round(minimumFill * 100)}% plus overflow and clipping checks.`
      : `Website layout audit passed at ${width}x${height}; overflow and clipping checks only.`);
  }
} finally {
  await browser.close();
}
