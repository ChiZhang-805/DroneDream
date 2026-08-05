import {
  createReadStream,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { tmpdir } from "node:os";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium, firefox } = frontendRequire("playwright");

const [
  baseUrlRaw,
  outputRaw = "work/product-page-audit.json",
  browserListRaw = "edge,chrome,lenovo,firefox",
  siteDirectoryRaw = "",
] =
  process.argv.slice(2);
if (!baseUrlRaw) {
  console.error(
    "Usage: node audit-product-page.mjs <base-url> [output.json] "
    + "[edge,chrome,lenovo,firefox] [site-dist-directory]",
  );
  process.exit(2);
}

const baseUrl = new URL(baseUrlRaw.endsWith("/") ? baseUrlRaw : `${baseUrlRaw}/`);
const outputPath = resolve(outputRaw);
const screenshotDirectory = join(dirname(outputPath), "product-page-screenshots");
mkdirSync(screenshotDirectory, { recursive: true });

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};
const extname = (path) => {
  const index = path.lastIndexOf(".");
  return index >= 0 ? path.slice(index).toLowerCase() : "";
};
const startStaticServer = async () => {
  if (!siteDirectoryRaw) return null;
  if (!["127.0.0.1", "localhost"].includes(baseUrl.hostname)) {
    throw new Error("The embedded audit server may only bind localhost.");
  }
  const siteRoot = resolve(siteDirectoryRaw);
  const sitePrefix = `${siteRoot.replace(/[\\/]+$/u, "")}\\`;
  const server = createServer((request, response) => {
    const requestUrl = new URL(request.url ?? "/", baseUrl);
    let relativePath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/u, "");
    if (!relativePath || relativePath.endsWith("/")) relativePath += "index.html";
    let candidate = resolve(siteRoot, relativePath.replace(/\//gu, "\\"));
    if (!candidate.startsWith(sitePrefix) && candidate !== siteRoot) {
      response.writeHead(403);
      response.end("Forbidden");
      return;
    }
    if (!existsSync(candidate)) {
      candidate = resolve(siteRoot, "index.html");
    }
    try {
      if (statSync(candidate).isDirectory()) candidate = resolve(candidate, "index.html");
      response.writeHead(200, {
        "Content-Type": mimeTypes[extname(candidate)] ?? "application/octet-stream",
        "Cache-Control": "no-store",
      });
      createReadStream(candidate).pipe(response);
    } catch {
      response.writeHead(404);
      response.end("Not found");
    }
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(Number(baseUrl.port || 80), baseUrl.hostname, resolveListen);
  });
  return server;
};

const browserCandidates = {
  edge: {
    engine: chromium,
    paths: [
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ],
  },
  chrome: {
    engine: chromium,
    paths: [
      "E:\\Google Chrome\\48\\chrome.exe",
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      join(process.env.LOCALAPPDATA ?? "", "Google", "Chrome", "Application", "chrome.exe"),
    ],
  },
  lenovo: {
    engine: chromium,
    paths: [
      "C:\\Program Files (x86)\\Lenovo\\SLBrowser\\SLBrowser.exe",
      "C:\\Program Files\\Lenovo\\SLBrowser\\SLBrowser.exe",
      join(process.env.LOCALAPPDATA ?? "", "Lenovo", "SLBrowser", "SLBrowser.exe"),
    ],
  },
  firefox: { engine: firefox, paths: [] },
};

const requestedBrowsers = [...new Set(
  browserListRaw.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean),
)];
for (const browserName of requestedBrowsers) {
  if (!browserCandidates[browserName]) throw new Error(`Unsupported browser: ${browserName}`);
}

const locales = ["en", "zh-CN"];
const profiles = {
  standard: [
    { name: "desktop-1440", viewport: { width: 1440, height: 1000 } },
    { name: "mobile-390", viewport: { width: 390, height: 844 } },
  ],
  edge: [
    { name: "desktop-1440", viewport: { width: 1440, height: 1000 } },
    { name: "wide-2048", viewport: { width: 2048, height: 1280 } },
    { name: "tablet-760", viewport: { width: 760, height: 1000 } },
    { name: "mobile-390", viewport: { width: 390, height: 844 } },
  ],
};

const copy = (locale) => ({
  title: locale === "zh-CN" ? "DroneDream 专业版本" : "DroneDream Editions",
  productNav: locale === "zh-CN" ? "产品" : "Product",
  priceNav: locale === "zh-CN" ? "价格" : "Price",
  universalDisabled: locale === "zh-CN"
    ? "DroneDream Universal 正在准备"
    : "DroneDream Universal is coming soon",
  headings: ["DroneDream · SIM", "DroneDream · LAB", "DroneDream · FIELD"],
});

const sha256File = async (path) => createHash("sha256").update(await readFile(path)).digest("hex");

const collectState = async (page, locale) => page.evaluate((expected) => {
  const tolerance = 2;
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number.parseFloat(style.opacity || "1") > 0.001 &&
      rect.width > 0 &&
      rect.height > 0;
  };
  const nameOf = (node) => (
    node.getAttribute("aria-label") || node.textContent || ""
  ).replace(/\s+/gu, " ").trim();
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;
  const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth ?? 0);
  const documentHeight = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0);
  const violations = [];
  if (documentWidth > viewportWidth + tolerance) {
    violations.push(`document horizontal overflow ${documentWidth - viewportWidth}px`);
  }
  if (documentHeight > viewportHeight + tolerance) {
    violations.push(`Product page exceeds one viewport by ${documentHeight - viewportHeight}px`);
  }
  if (document.querySelector('[role="dialog"]')) violations.push("legacy dialog is present");
  const header = document.querySelector(".site-header");
  const shell = document.querySelector(".site-product-page-shell");
  const title = document.querySelector(".site-product-page-header h1");
  if (visible(header) && visible(title)) {
    const headerRect = header.getBoundingClientRect();
    const titleRect = title.getBoundingClientRect();
    if (headerRect.bottom > titleRect.top + tolerance) {
      violations.push(`fixed header overlaps product heading by ${Math.round(headerRect.bottom - titleRect.top)}px`);
    }
  }
  if (!title || nameOf(title) !== expected.title) violations.push("Product page title is incorrect");
  if (title) {
    const titleRange = document.createRange();
    titleRange.selectNodeContents(title);
    if (titleRange.getClientRects().length !== 1) violations.push("Product page title wraps to multiple lines");
  }
  if (document.querySelector(".site-product-page-header p")) {
    violations.push("Product page explanatory copy remains under the title");
  }
  if (visible(header) && visible(shell) && viewportWidth > 900) {
    const shellRect = shell.getBoundingClientRect();
    const brandRect = document.querySelector(".site-brand")?.getBoundingClientRect();
    const actionsRect = document.querySelector(".site-header-actions")?.getBoundingClientRect();
    if (!brandRect || Math.abs(brandRect.left - shellRect.left) > tolerance) {
      violations.push("header brand is not aligned with Product content");
    }
    if (!actionsRect || Math.abs(actionsRect.right - shellRect.right) > tolerance) {
      violations.push("header actions are not aligned with Product content");
    }
  }

  const nav = [...document.querySelectorAll(".site-nav a")].filter(visible).map((node) => ({
    text: nameOf(node),
    href: node.getAttribute("href"),
    active: node.classList.contains("active") || node.getAttribute("aria-current") === "page",
  }));
  if (viewportWidth > 1050) {
    const productNav = nav.find((item) => item.text === expected.productNav);
    const priceNav = nav.find((item) => item.text === expected.priceNav);
    if (productNav?.href !== "/product/") violations.push("Product nav does not target /product/");
    if (priceNav?.href !== "/pricing/") violations.push("Price nav does not target /pricing/");
    if (!productNav?.active) violations.push("Product nav is not active on /product/");
  }

  const universalButton = [...document.querySelectorAll("button.site-header-download")]
    .find((node) => nameOf(node) === expected.universalDisabled);
  if (!universalButton) violations.push("Universal disabled header button is missing");
  else if (!universalButton.disabled) violations.push("Universal header button is not disabled");
  if ([...document.querySelectorAll("a.site-header-download")].some((node) => nameOf(node).includes("Universal"))) {
    violations.push("Universal has a live download link while metadata is planned");
  }

  const cards = [...document.querySelectorAll(".site-product-edition")].filter(visible);
  const headings = cards.map((card) => card.querySelector("h2")?.textContent?.trim() ?? "");
  if (cards.length !== 3) violations.push(`expected 3 product cards, found ${cards.length}`);
  for (const heading of expected.headings) {
    if (!headings.includes(heading)) violations.push(`missing product heading: ${heading}`);
  }
  const editionMarks = cards.map((card) => card.querySelector("img.site-product-edition-icon"));
  if (editionMarks.some((mark) => !mark)) violations.push("approved edition mark is missing");
  if (editionMarks.some((mark) => !visible(mark))) violations.push("approved edition mark is not visible");
  if (editionMarks.some((mark) => mark?.dataset.brandHandoff !== "commander-approved-brand-handoff-v2")) {
    violations.push("edition mark does not declare the approved brand handoff");
  }
  if (editionMarks.some((mark) => !mark?.complete || mark.naturalWidth !== 1024 || mark.naturalHeight !== 1024)) {
    violations.push("edition mark source dimensions are not 1024x1024");
  }
  if (editionMarks.some((mark) => {
    if (!mark) return true;
    const rect = mark.getBoundingClientRect();
    return Math.abs(rect.width - rect.height) > tolerance || mark.naturalWidth / rect.width < 4;
  })) {
    violations.push("edition mark is cropped or undersampled at the rendered size");
  }
  if (document.querySelector('[data-icon-donor="pending"]')) violations.push("icon donor remains pending");
  if (document.querySelector(".site-product-edition-visual")) {
    violations.push("legacy rounded product visual remains");
  }
  if (document.querySelector(".site-product-edition-heading span")) {
    violations.push("legacy preparation status badge remains");
  }
  if (cards.some((card) => card.querySelector("button.site-product-edition-action"))) {
    violations.push("planned editions still render disabled action buttons");
  }
  const inventedDownloads = [...document.querySelectorAll(".site-product-edition a[href]")]
    .filter((node) => /DroneDream-(Sim|Lab|Field|Universal)-1\.0\.0\.exe/u.test(node.getAttribute("href") ?? ""));
  if (inventedDownloads.length > 0) violations.push("planned product package has a live download link");

  if (document.querySelector(".site-product-current")) {
    violations.push("current preview panel remains on Product page");
  }

  const themeTokens = cards.map((card) => {
    const style = getComputedStyle(card);
    return ["--edition-accent-a", "--edition-accent-b", "--edition-accent-c", "--edition-surface"]
      .map((property) => style.getPropertyValue(property).trim()).join("|");
  });
  if (new Set(themeTokens).size !== 3) violations.push("edition cards do not expose three unique themes");

  const critical = [...document.querySelectorAll(
    ".site-header,.site-nav,.site-product-page-shell,.site-product-page-header,"
    + ".site-product-page-grid,.site-product-edition,h1,h2",
  )].filter(visible);
  for (const [index, node] of critical.entries()) {
    const rect = node.getBoundingClientRect();
    const label = node.getAttribute("class") || node.tagName.toLowerCase() || `node-${index}`;
    if (rect.left < -tolerance || rect.right > viewportWidth + tolerance) {
      violations.push(`${label} outside viewport horizontally (${Math.round(rect.left)}..${Math.round(rect.right)})`);
    }
    if (
      ["hidden", "clip"].includes(getComputedStyle(node).overflowX) &&
      node.scrollWidth > node.clientWidth + tolerance &&
      node.textContent?.trim()
    ) {
      violations.push(`${label} clips content horizontally`);
    }
  }

  const heights = cards.map((card) => Math.round(card.getBoundingClientRect().height));
  if (viewportWidth >= 1000 && heights.length === 3) {
    const heightSpread = Math.max(...heights) - Math.min(...heights);
    if (heightSpread > tolerance) violations.push(`product card height spread ${heightSpread}px`);
  }

  return {
    documentHeight,
    documentWidth,
    viewportHeight,
    viewportWidth,
    nav,
    headings,
    productCardHeights: heights,
    iconHandoff: editionMarks.map((mark) => ({
      source: mark?.getAttribute("src") ?? null,
      width: mark ? Math.round(mark.getBoundingClientRect().width) : 0,
      naturalWidth: mark?.naturalWidth ?? 0,
    })),
    uniqueThemeCount: new Set(themeTokens).size,
    universalDisabledPresent: Boolean(universalButton),
    currentPreviewPresent: Boolean(document.querySelector(".site-product-current")),
    dialogs: document.querySelectorAll('[role="dialog"]').length,
    violations,
  };
}, copy(locale));

const checkNavigation = async (page, viewportWidth) => {
  const issues = [];
  if (viewportWidth <= 1050) {
    const menuButton = page.locator(".site-menu-button").first();
    if (await menuButton.count() === 0) {
      issues.push("mobile menu button is missing");
      return issues;
    }
    await menuButton.click();
    await page.waitForFunction(() => (
      document.querySelector(".site-menu-button")?.getAttribute("aria-expanded") === "true"
    ), null, { timeout: 5_000 }).catch(() => issues.push("mobile menu did not open"));
  }
  for (const [selector, label] of [
    ['.site-nav a[href="/product/"]', "Product nav link"],
    ['.site-nav a[href="/pricing/"]', "Price nav link"],
  ]) {
    const target = page.locator(selector).first();
    if (await target.count() === 0) {
      issues.push(`${label} is missing`);
      continue;
    }
    await target.focus();
    if (!await target.evaluate((node) => node === document.activeElement)) {
      issues.push(`${label} cannot receive focus`);
    }
  }
  const product = page.locator('.site-nav a[href="/product/"]').first();
  if (await product.count() > 0) {
    const active = await product.evaluate((node) =>
      node.classList.contains("active") || node.getAttribute("aria-current") === "page",
    );
    if (!active) issues.push("Product nav is not active on /product/");
  }
  if (viewportWidth <= 1050) {
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => (
      document.querySelector(".site-menu-button")?.getAttribute("aria-expanded") === "false"
    ), null, { timeout: 5_000 }).catch(() => issues.push("mobile menu did not close with Escape"));
  }
  const universal = page.locator("button.site-header-download").first();
  if (await universal.count() === 0) issues.push("disabled Universal button is missing");
  else if (await universal.isEnabled()) issues.push("Universal button is keyboard-enabled while planned");
  return issues;
};

const unavailable = [];
const results = [];
const embeddedServer = await startStaticServer();
for (const browserName of requestedBrowsers) {
  const definition = browserCandidates[browserName];
  const executablePath = definition.paths.find((candidate) => candidate && existsSync(candidate));
  if (definition.paths.length > 0 && !executablePath) {
    unavailable.push({ browser: browserName, reason: "browser executable not found" });
    continue;
  }
  const launchOptions = {
    headless: true,
    ...(executablePath ? { executablePath } : {}),
    ...(definition.engine === chromium
      ? { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"] }
      : {}),
  };
  const browser = browserName === "lenovo"
    ? null
    : await definition.engine.launch(launchOptions);
  try {
    for (const profile of (browserName === "edge" ? profiles.edge : profiles.standard)) {
      for (const locale of locales) {
        const contextOptions = {
          viewport: profile.viewport,
          deviceScaleFactor: 1,
          locale,
          colorScheme: "dark",
          reducedMotion: "reduce",
        };
        const lenovoProfile = browserName === "lenovo"
          ? mkdtempSync(join(tmpdir(), "dronedream-lenovo-product-"))
          : "";
        const context = browserName === "lenovo"
          ? await definition.engine.launchPersistentContext(
            lenovoProfile,
            { ...launchOptions, ...contextOptions },
          )
          : await browser.newContext(contextOptions);
        await context.addInitScript((nextLocale) => {
          window.localStorage.setItem("drone-dream:locale", nextLocale);
        }, locale);
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
        page.on("requestfailed", (request) => {
          if (request.failure()?.errorText !== "net::ERR_ABORTED") {
            errors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText ?? "request failed"}`);
          }
        });
        page.on("response", (response) => {
          if (
            response.status() >= 400 &&
            new URL(response.url()).origin === baseUrl.origin &&
            !response.url().endsWith("/downloads/latest.json")
          ) {
            errors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
          }
        });
        await page.goto(new URL("/product/", baseUrl).href, {
          waitUntil: "domcontentloaded",
          timeout: 60_000,
        });
        await page.waitForSelector(".site-product-page", { state: "visible", timeout: 20_000 });
        await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
        errors.push(...await checkNavigation(page, profile.viewport.width));
        const state = await collectState(page, locale);
        errors.push(...state.violations);
        await page.evaluate(() => {
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
        });
        const screenshot = join(screenshotDirectory, `${browserName}-${profile.name}-${locale}.png`);
        await page.screenshot({ path: screenshot, fullPage: true });
        results.push({
          browser: browserName,
          browserVersion: context.browser()?.version() ?? browser?.version() ?? "unknown",
          locale,
          profile: profile.name,
          viewport: profile.viewport,
          screenshot,
          screenshotSha256: await sha256File(screenshot),
          state,
          errors: [...new Set(errors)],
        });
        await context.close();
        if (lenovoProfile) rmSync(lenovoProfile, { recursive: true, force: true });
      }
    }
  } finally {
    await browser?.close();
  }
}

const failures = results.filter((result) => result.errors.length > 0);
const summary = {
  generatedAt: new Date().toISOString(),
  baseUrl: baseUrl.href,
  browsersRequested: requestedBrowsers,
  unavailable,
  checks: results.length,
  passed: results.length - failures.length,
  failed: failures.length,
  profiles: [...new Set(results.map((result) => result.profile))],
  locales,
};
const report = { summary, failures, results };
writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(summary, null, 2));
if (embeddedServer) {
  await new Promise((resolveClose) => embeddedServer.close(resolveClose));
}
if (unavailable.length > 0 || failures.length > 0) process.exitCode = 1;
