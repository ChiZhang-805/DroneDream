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
  title: locale === "zh-CN" ? "选择你的 DroneDream 版本" : "Choose Your DroneDream Edition",
  subtitle: locale === "zh-CN"
    ? "三个版本分别覆盖仿真搜索、实验验证和受控真机现场调参。"
    : "Three focused editions cover simulation search, lab validation, and controlled field tuning.",
  productNav: locale === "zh-CN" ? "产品" : "Product",
  priceNav: locale === "zh-CN" ? "价格" : "Pricing",
  universalDisabled: locale === "zh-CN"
    ? "DroneDream Universal 下载"
    : "DroneDream Universal Download",
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
  const subtitle = document.querySelector(".site-product-page-header p");
  if (!subtitle || nameOf(subtitle) !== expected.subtitle) {
    violations.push("Product page subtitle is missing or incorrect");
  } else if (viewportWidth > 900) {
    const subtitleRange = document.createRange();
    subtitleRange.selectNodeContents(subtitle);
    if (subtitleRange.getClientRects().length !== 1) {
      violations.push("Product page subtitle wraps on desktop");
    }
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
    if (priceNav?.href !== "/pricing/") violations.push("Pricing nav does not target /pricing/");
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
  const expectedBrandDimensions = {
    sim: { mark: [1024, 1024], lockup: [2337, 218] },
    lab: { mark: [1024, 1024], lockup: [2386, 218] },
    field: { mark: [1024, 1024], lockup: [2581, 218] },
  };
  const desktopLockup = window.innerWidth >= 1161;
  const editionImages = cards.map((card) => ({
    edition: card.dataset.edition,
    image: card.querySelector("picture.site-product-edition-picture img.site-product-edition-icon"),
    picture: card.querySelector("picture.site-product-edition-picture"),
  }));
  if (editionImages.some(({ image, picture }) => !image || !picture)) {
    violations.push("approved responsive edition brand is missing");
  }
  for (const { edition, image, picture } of editionImages) {
    if (!edition || !image || !picture) continue;
    if (picture.dataset.brandHandoff !== "universal-canonical-brand-donor-v1.1.0") {
      violations.push(`${edition} brand does not declare the approved handoff`);
    }
    if (picture.dataset.brandSurface !== "product-card") {
      violations.push(`${edition} brand is bound to the wrong surface`);
    }
    if (image.getAttribute("alt") !== "" || image.getAttribute("aria-hidden") !== "true") {
      violations.push(`${edition} decorative brand image has an invalid accessible name`);
    }
    const variant = desktopLockup ? "lockup" : "mark";
    const dimensions = expectedBrandDimensions[edition]?.[variant];
    if (
      !image.complete ||
      !dimensions ||
      image.naturalWidth !== dimensions[0] ||
      image.naturalHeight !== dimensions[1]
    ) {
      violations.push(`${edition} ${variant} source dimensions are invalid`);
      continue;
    }
    if (!image.currentSrc.includes(`${edition}-${variant === "lockup" ? "lockup-primary" : "mark"}`)) {
      violations.push(`${edition} selected the wrong responsive brand asset`);
    }
    const rect = image.getBoundingClientRect();
    const naturalRatio = image.naturalWidth / image.naturalHeight;
    const renderedRatio = rect.width / rect.height;
    if (
      Math.abs(renderedRatio - naturalRatio) / naturalRatio > 0.02 ||
      rect.width > picture.getBoundingClientRect().width + tolerance
    ) {
      violations.push(`${edition} ${variant} is stretched or cropped`);
    }
  }
  if (document.querySelector('[data-icon-donor="pending"]')) violations.push("icon donor remains pending");
  if (document.querySelector(".site-product-edition-visual")) {
    violations.push("legacy rounded product visual remains");
  }
  if (document.querySelector(".site-product-edition-heading span")) {
    violations.push("legacy preparation status badge remains");
  }
  const editionActions = cards.map((card) => card.querySelector(".site-product-edition-action"));
  if (editionActions.length !== 3 || editionActions.some((action) => !action)) {
    violations.push("edition download buttons are missing");
  }
  for (const [index, action] of editionActions.entries()) {
    if (!action) continue;
    const card = cards[index];
    const edition = card?.dataset.edition ?? `edition-${index}`;
    if (action.tagName.toLowerCase() !== "button" || !action.disabled) {
      violations.push(`${edition} planned download button is not disabled`);
    }
    if (action.querySelector("img")) {
      violations.push(`${edition} download action uses a brand image instead of a download icon`);
    }
  }
  const inventedDownloads = [...document.querySelectorAll(".site-product-edition a[href]")]
    .filter((node) => /DroneDream-(Sim|Lab|Field|Universal)-1\.0\.0\.exe/u.test(node.getAttribute("href") ?? ""));
  if (inventedDownloads.length > 0) violations.push("planned product package has a live download link");

  for (const card of cards) {
    const edition = card.dataset.edition ?? "edition";
    const items = [...card.querySelectorAll("li")].filter(visible);
    if (items.length !== 6) violations.push(`${edition} feature list should contain 6 items, found ${items.length}`);
    const topline = card.querySelector(".site-product-edition-topline");
    const action = card.querySelector(".site-product-edition-action");
    const picture = card.querySelector(".site-product-edition-picture");
    if (topline && action && picture) {
      const actionRect = action.getBoundingClientRect();
      const pictureRect = picture.getBoundingClientRect();
      const actionCenter = actionRect.top + actionRect.height / 2;
      const pictureCenter = pictureRect.top + pictureRect.height / 2;
      if (Math.abs(actionCenter - pictureCenter) > 8) {
        violations.push(`${edition} brand and download action are vertically misaligned`);
      }
    }

    const list = card.querySelector("ul");
    const screenshotFrame = card.querySelector(".site-product-screenshots");
    const screenshot = screenshotFrame?.querySelector("img");
    const buttons = screenshotFrame ? [...screenshotFrame.querySelectorAll("button")] : [];
    if (!list || !screenshotFrame || !screenshot || buttons.length !== 2) {
      violations.push(`${edition} screenshot carousel is incomplete`);
      continue;
    }
    const listRect = list.getBoundingClientRect();
    const frameRect = screenshotFrame.getBoundingClientRect();
    const screenshotBelowList = frameRect.top >= listRect.bottom - tolerance;
    if (
      screenshotBelowList &&
      (
        Math.abs(listRect.left - frameRect.left) > tolerance ||
        Math.abs(listRect.right - frameRect.right) > tolerance
      )
    ) {
      violations.push(`${edition} screenshot frame is not aligned with the feature rules`);
    }
    const frameRatio = frameRect.width / frameRect.height;
    if (Math.abs(frameRatio - 1.6) > 0.08) {
      violations.push(`${edition} screenshot frame is not sized like the app viewport`);
    }
    const screenshotStyle = getComputedStyle(screenshot);
    if (screenshotStyle.objectFit !== "contain") {
      violations.push(`${edition} screenshot image is not configured for full-frame display`);
    }
    if (!screenshot.complete || screenshot.naturalWidth <= 0 || screenshot.naturalHeight <= 0) {
      violations.push(`${edition} screenshot image did not load`);
    } else {
      const naturalRatio = screenshot.naturalWidth / screenshot.naturalHeight;
      if (Math.abs(naturalRatio - 1.6) > 0.04) {
        violations.push(`${edition} screenshot source is not a complete 16:10 app capture`);
      }
    }
    const imageRect = screenshot.getBoundingClientRect();
    for (const [buttonIndex, button] of buttons.entries()) {
      const buttonRect = button.getBoundingClientRect();
      const buttonStyle = getComputedStyle(button);
      if (buttonStyle.position !== "absolute") {
        violations.push(`${edition} screenshot button ${buttonIndex + 1} is not overlayed`);
      }
      if (Number.parseInt(buttonStyle.zIndex || "0", 10) < 1) {
        violations.push(`${edition} screenshot button ${buttonIndex + 1} is below the image layer`);
      }
      const opacity = Number.parseFloat(buttonStyle.opacity || "1");
      if (opacity < 0.45 || opacity > 0.75) {
        violations.push(`${edition} screenshot button ${buttonIndex + 1} resting opacity is outside the expected range`);
      }
      if (
        buttonRect.left < imageRect.left - tolerance ||
        buttonRect.right > imageRect.right + tolerance ||
        buttonRect.top < imageRect.top - tolerance ||
        buttonRect.bottom > imageRect.bottom + tolerance
      ) {
        violations.push(`${edition} screenshot button ${buttonIndex + 1} is not placed on the image`);
      }
    }
  }

  if (document.querySelector(".site-product-current")) {
    violations.push("current preview panel remains on Product page");
  }

  const themeTokens = cards.map((card) => {
    const style = getComputedStyle(card);
    return ["--edition-accent-a", "--edition-accent-b", "--edition-accent-c", "--edition-surface"]
      .map((property) => style.getPropertyValue(property).trim()).join("|");
  });
  if (new Set(themeTokens).size !== 3) violations.push("edition cards do not expose three unique themes");

  const desktopBrandHeadings = cards.map((card) => (
    card.querySelector("h2")
  ));
  if (desktopLockup) {
    for (const heading of desktopBrandHeadings) {
      if (!heading) {
        violations.push("desktop lockup is missing its accessible heading");
        continue;
      }
      const style = getComputedStyle(heading);
      const rect = heading.getBoundingClientRect();
      if (
        heading.hidden ||
        heading.getAttribute("aria-hidden") === "true" ||
        style.display === "none" ||
        style.visibility === "hidden"
      ) {
        violations.push("desktop lockup heading is absent from the accessibility tree");
      }
      if (
        style.position !== "absolute" ||
        !["hidden", "clip"].includes(style.overflowX) ||
        rect.width > 1 + tolerance ||
        rect.height > 1 + tolerance
      ) {
        violations.push("desktop lockup heading is not visually hidden");
      }
    }
  }

  const critical = [...document.querySelectorAll(
    ".site-header,.site-nav,.site-product-page-shell,.site-product-page-header,"
    + ".site-product-page-grid,.site-product-edition,h1,h2",
  )].filter((node) => (
    visible(node) && !desktopBrandHeadings.includes(node)
  ));
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
    iconHandoff: editionImages.map(({ image }) => ({
      source: image?.currentSrc ?? null,
      width: image ? Math.round(image.getBoundingClientRect().width) : 0,
      naturalWidth: image?.naturalWidth ?? 0,
      naturalHeight: image?.naturalHeight ?? 0,
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
    ['.site-nav a[href="/pricing/"]', "Pricing nav link"],
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
  else {
    if (await universal.isEnabled()) issues.push("Universal button is keyboard-enabled while planned");
    const iconKind = await universal.evaluate((node) => ({
      hasDownloadIcon: Boolean(node.querySelector("svg")),
      hasBrandImage: Boolean(node.querySelector("img")),
    }));
    if (!iconKind.hasDownloadIcon) issues.push("Universal button is missing the download icon");
    if (iconKind.hasBrandImage) issues.push("Universal button uses a brand mark instead of the download icon");
  }
  const disabledConsole = page.locator(".site-nav button", { hasText: /^(Console|控制台)$/u }).first();
  if (await disabledConsole.count() === 0) issues.push("disabled Console nav item is missing");
  else if (await disabledConsole.isEnabled()) issues.push("Console nav item is enabled");
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
