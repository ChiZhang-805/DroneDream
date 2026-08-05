import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { createServer } from "node:http";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium, firefox } = frontendRequire("playwright");

const [
  baseUrlRaw,
  outputRaw = "work/product-page-audit.json",
  browserListRaw = "edge,chrome,firefox",
  siteDirectoryRaw = "",
] =
  process.argv.slice(2);
if (!baseUrlRaw) {
  console.error(
    "Usage: node audit-product-page.mjs <base-url> [output.json] "
    + "[edge,chrome,firefox] [site-dist-directory]",
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
  productNav: locale === "zh-CN" ? "产品" : "Product",
  priceNav: locale === "zh-CN" ? "价格" : "Price",
  universalDisabled: locale === "zh-CN"
    ? "DroneDream Universal 正在准备"
    : "DroneDream Universal is coming soon",
  currentPreview: locale === "zh-CN" ? "下载当前预览版" : "Download current preview",
  windowsPreview: locale === "zh-CN" ? "下载 Windows 预览版" : "Download Windows preview",
  comingSoon: locale === "zh-CN" ? "即将推出" : "Coming soon",
  headings: locale === "zh-CN"
    ? ["DroneDream 仿真版", "DroneDream 实验室版", "DroneDream 真机版"]
    : ["DroneDream Sim", "DroneDream Lab", "DroneDream Field"],
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
  const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth ?? 0);
  const violations = [];
  if (documentWidth > viewportWidth + tolerance) {
    violations.push(`document horizontal overflow ${documentWidth - viewportWidth}px`);
  }
  if (document.querySelector('[role="dialog"]')) violations.push("legacy dialog is present");
  const header = document.querySelector(".site-header");
  const title = document.querySelector(".site-product-page-header h1");
  if (visible(header) && visible(title)) {
    const headerRect = header.getBoundingClientRect();
    const titleRect = title.getBoundingClientRect();
    if (headerRect.bottom > titleRect.top + tolerance) {
      violations.push(`fixed header overlaps product heading by ${Math.round(headerRect.bottom - titleRect.top)}px`);
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
  const disabledActions = cards.flatMap((card) => (
    [...card.querySelectorAll("button.site-product-edition-action")].filter(visible)
  ));
  if (disabledActions.length !== 3) {
    violations.push(`expected 3 disabled product actions, found ${disabledActions.length}`);
  }
  for (const action of disabledActions) {
    if (!action.disabled || nameOf(action) !== expected.comingSoon) {
      violations.push("product action is not the expected disabled coming-soon button");
    }
  }
  const inventedDownloads = [...document.querySelectorAll(".site-product-edition a[href]")]
    .filter((node) => /DroneDream-(Sim|Lab|Field|Universal)-1\.0\.0\.exe/u.test(node.getAttribute("href") ?? ""));
  if (inventedDownloads.length > 0) violations.push("planned product package has a live download link");

  const currentPreview = [...document.querySelectorAll(".site-product-current a[href]")]
    .find((node) => nameOf(node) === expected.currentPreview);
  if (!currentPreview) violations.push("current 1.0.0 preview entry is missing from Product page");
  else if (!/DroneDream_1\.0\.0_x64-setup\.exe/u.test(currentPreview.href)) {
    violations.push("current preview entry does not point to the 1.0.0 installer");
  }
  if ([...document.querySelectorAll("a[href]")].some((node) => nameOf(node) === expected.windowsPreview)) {
    violations.push("home Windows preview CTA leaked onto Product page");
  }

  const critical = [...document.querySelectorAll(
    ".site-header,.site-nav,.site-product-page-shell,.site-product-page-header,"
    + ".site-product-page-grid,.site-product-edition,.site-product-current,h1,h2",
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
  const actionTops = cards.map((card) => {
    const action = card.querySelector(".site-product-edition-action");
    return action ? Math.round(action.getBoundingClientRect().top) : 0;
  }).filter(Boolean);
  if (viewportWidth >= 1000 && heights.length === 3) {
    const heightSpread = Math.max(...heights) - Math.min(...heights);
    const actionSpread = Math.max(...actionTops) - Math.min(...actionTops);
    if (heightSpread > tolerance) violations.push(`product card height spread ${heightSpread}px`);
    if (actionSpread > tolerance) violations.push(`product action baseline spread ${actionSpread}px`);
  }

  return {
    documentWidth,
    viewportWidth,
    nav,
    headings,
    productCardHeights: heights,
    productActionTops: actionTops,
    disabledProductActions: disabledActions.length,
    universalDisabledPresent: Boolean(universalButton),
    currentPreviewHref: currentPreview?.getAttribute("href") ?? null,
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
  const browser = await definition.engine.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
    ...(definition.engine === chromium
      ? { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"] }
      : {}),
  });
  try {
    for (const profile of (browserName === "edge" ? profiles.edge : profiles.standard)) {
      for (const locale of locales) {
        const context = await browser.newContext({
          viewport: profile.viewport,
          deviceScaleFactor: 1,
          locale,
          colorScheme: "dark",
          reducedMotion: "reduce",
        });
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
          if (response.status() >= 400 && new URL(response.url()).origin === baseUrl.origin) {
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
          browserVersion: browser.version(),
          locale,
          profile: profile.name,
          viewport: profile.viewport,
          screenshot,
          screenshotSha256: await sha256File(screenshot),
          state,
          errors: [...new Set(errors)],
        });
        await context.close();
      }
    }
  } finally {
    await browser.close();
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
