import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium, firefox } = frontendRequire("playwright");

const [
  baseUrlRaw,
  outputRaw = "",
  browserListRaw = "edge,chrome,lenovo,firefox",
  consolePreviewUrlRaw = "",
] = process.argv.slice(2);
if (!baseUrlRaw) {
  console.error(
    "Usage: node audit-browser-matrix.mjs <base-url> [output.json] "
      + "[edge,chrome,lenovo,firefox] [console-preview-url]",
  );
  process.exit(2);
}

const baseUrl = new URL(baseUrlRaw.endsWith("/") ? baseUrlRaw : `${baseUrlRaw}/`);
if (!["http:", "https:"].includes(baseUrl.protocol)) {
  throw new Error("The matrix base URL must use HTTP or HTTPS.");
}
const consolePreviewUrl = consolePreviewUrlRaw
  ? new URL(
    consolePreviewUrlRaw.endsWith("/") ? consolePreviewUrlRaw : `${consolePreviewUrlRaw}/`,
  )
  : null;
if (
  consolePreviewUrl
  && !["http:", "https:"].includes(consolePreviewUrl.protocol)
) {
  throw new Error("The console preview URL must use HTTP or HTTPS.");
}

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
  firefox: {
    engine: firefox,
    paths: [],
  },
};

const requestedBrowsers = [...new Set(
  browserListRaw.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean),
)];
if (requestedBrowsers.length === 0) throw new Error("Select at least one browser.");
for (const browserName of requestedBrowsers) {
  if (!browserCandidates[browserName]) throw new Error(`Unsupported browser: ${browserName}`);
}

const routes = [
  { name: "home", path: "/", root: "#home" },
  { name: "pricing", path: "/pricing/", root: "#site-root > .dd-site" },
  { name: "manual", path: "/manual/", root: "#site-root > .dd-site" },
  { name: "community", path: "/community/", root: "#site-root > .dd-site" },
  { name: "console", path: "/console/", root: "#root > .app-shell" },
];
if (consolePreviewUrl) {
  routes.push(
    {
      name: "console-assistant-preview",
      path: "assistant?docsPreview=1",
      expectedPath: "/console/assistant",
      root: "#root > .app-shell",
      baseUrl: consolePreviewUrl,
      consolePreview: true,
    },
    {
      name: "console-history-preview",
      path: "history?docsPreview=1",
      expectedPath: "/console/history",
      root: ".history-page",
      baseUrl: consolePreviewUrl,
      consolePreview: true,
    },
  );
}
const locales = ["en", "zh-CN"];
const standardProfiles = [
  {
    name: "desktop-100",
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    physicalViewport: "1440x1000",
  },
  {
    name: "mobile-100",
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    physicalViewport: "390x844",
  },
];
const edgeProfiles = [
  standardProfiles[0],
  {
    name: "wide-100",
    viewport: { width: 2048, height: 1280 },
    deviceScaleFactor: 1,
    physicalViewport: "2048x1280",
  },
  {
    name: "desktop-125",
    viewport: { width: 1152, height: 800 },
    deviceScaleFactor: 1.25,
    physicalViewport: "1440x1000",
  },
  standardProfiles[1],
];

const outputPath = outputRaw ? resolve(outputRaw) : "";
const screenshotDirectory = outputPath
  ? join(dirname(outputPath), "browser-matrix-screenshots")
  : "";
if (screenshotDirectory) mkdirSync(screenshotDirectory, { recursive: true });

const sameOrigin = (value, routeBaseUrl) => {
  try {
    return new URL(value).origin === routeBaseUrl.origin;
  } catch {
    return false;
  }
};

const collectLayout = async (page, routeName) => page.evaluate((activeRoute) => {
  const tolerance = 2;
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && Number.parseFloat(style.opacity || "1") > 0.001
      && rect.width > 0
      && rect.height > 0;
  };
  const hasHorizontalScroller = (node) => {
    let ancestor = node.parentElement;
    while (ancestor && ancestor !== document.body) {
      const style = getComputedStyle(ancestor);
      if (
        (style.overflowX === "auto" || style.overflowX === "scroll")
        && ancestor.scrollWidth > ancestor.clientWidth + tolerance
      ) return true;
      ancestor = ancestor.parentElement;
    }
    return false;
  };
  const lineCount = (node) => {
    const tops = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let textNode = walker.nextNode(); textNode; textNode = walker.nextNode()) {
      if (!textNode.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(textNode);
      for (const rect of range.getClientRects()) {
        if (rect.width < 1 || rect.height < 1) continue;
        if (!tops.some((top) => Math.abs(top - rect.top) <= 2)) tops.push(rect.top);
      }
    }
    return tops.length;
  };
  const labelFor = (node, index) => node.getAttribute("aria-label")
    || node.id
    || node.classList[0]
    || `${node.tagName.toLowerCase()}-${index}`;

  const viewportWidth = document.documentElement.clientWidth;
  const documentWidth = Math.max(
    document.documentElement.scrollWidth,
    document.body?.scrollWidth ?? 0,
  );
  const activeModal = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')]
    .find(visible);
  const inActiveSurface = (node) => (
    !activeModal || node === activeModal || activeModal.contains(node)
  );
  const violations = [];
  if (documentWidth > viewportWidth + tolerance) {
    violations.push(`document horizontal overflow ${documentWidth - viewportWidth}px`);
  }

  const criticalSelector = [
    ".site-header",
    ".site-shell",
    ".portal-page-heading",
    ".pricing-grid",
    ".pricing-card",
    ".manual-shell",
    ".manual-layout",
    ".community-shell",
    ".community-topic-card",
    ".app-shell",
    ".app-sidebar",
    ".app-main",
    "[role=dialog]",
    "h1",
    "h2",
    "h3",
    "[data-copy-block]",
  ].join(",");
  const critical = [...document.querySelectorAll(criticalSelector)]
    .filter((node) => visible(node) && inActiveSurface(node));
  critical.forEach((node, index) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    const label = labelFor(node, index);
    if (
      !hasHorizontalScroller(node)
      && (rect.left < -tolerance || rect.right > viewportWidth + tolerance)
    ) {
      violations.push(
        `${label} outside viewport horizontally (${Math.round(rect.left)}..${Math.round(rect.right)})`,
      );
    }
    if (
      (style.overflowX === "hidden" || style.overflowX === "clip")
      && node.scrollWidth > node.clientWidth + tolerance
      && node.textContent?.trim()
    ) {
      violations.push(`${label} clips ${node.scrollWidth - node.clientWidth}px horizontally`);
    }
  });

  const noWrapSelectors = [
    ".site-nav a",
    ".site-header-download",
    ".site-account-button",
    ".site-language button",
    ".site-nav.is-open a",
  ];
  for (const selector of noWrapSelectors) {
    [...document.querySelectorAll(selector)]
      .filter((node) => visible(node) && inActiveSurface(node))
      .forEach((node, index) => {
      const lines = lineCount(node);
      if (lines > 1) violations.push(`${selector}[${index}] wraps to ${lines} lines`);
      });
  }

  const pricingCards = [...document.querySelectorAll(".pricing-card")]
    .filter((node) => visible(node) && inActiveSurface(node));
  const pricingHeights = pricingCards.map((node) => Math.round(node.getBoundingClientRect().height));
  if (activeRoute === "pricing" && viewportWidth >= 900 && pricingHeights.length >= 3) {
    const spread = Math.max(...pricingHeights) - Math.min(...pricingHeights);
    if (spread > tolerance) violations.push(`pricing card height spread ${spread}px`);
  }

  const headingRoot = activeModal ?? document;
  const headings = [...headingRoot.querySelectorAll("h1, h2, [role=heading]")].filter(visible);
  if (headings.length === 0) {
    violations.push("primary heading is not visible");
  }

  return {
    path: location.pathname,
    lang: document.documentElement.lang,
    viewportWidth,
    documentWidth,
    pricingHeights,
    violations,
  };
}, routeName);

const collectAccessibility = async (page) => page.evaluate(() => {
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    if (node.closest("[hidden]")) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && Number.parseFloat(style.opacity || "1") > 0.001
      && rect.width > 0
      && rect.height > 0;
  };
  const textFromIds = (value) => (value ?? "")
    .split(/\s+/u)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
    .filter(Boolean)
    .join(" ");
  const accessibleName = (node) => {
    const labelledBy = textFromIds(node.getAttribute("aria-labelledby"));
    if (labelledBy) return labelledBy;
    const ariaLabel = node.getAttribute("aria-label")?.trim();
    if (ariaLabel) return ariaLabel;
    if (node instanceof HTMLInputElement && node.labels?.length) {
      return [...node.labels].map((label) => label.textContent?.trim() ?? "").join(" ").trim();
    }
    if (node instanceof HTMLImageElement) return node.getAttribute("alt")?.trim() ?? "";
    return node.textContent?.trim()
      || node.getAttribute("title")?.trim()
      || node.getAttribute("placeholder")?.trim()
      || "";
  };
  const labelFor = (node, index) => node.id
    || node.getAttribute("name")
    || node.classList[0]
    || `${node.tagName.toLowerCase()}-${index}`;
  const violations = [];

  if (!document.title.trim()) violations.push("document title is empty");
  if (!document.documentElement.lang.trim()) violations.push("html lang is empty");
  if (document.querySelectorAll("main").length !== 1) {
    violations.push(`expected one main landmark; found ${document.querySelectorAll("main").length}`);
  }
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    violations.push("reduced-motion browser preference was not applied");
  }

  [...document.querySelectorAll("img")].forEach((image, index) => {
    if (!image.hasAttribute("alt")) {
      violations.push(`${labelFor(image, index)} image has no alt attribute`);
    }
  });

  const interactiveSelector = [
    "a[href]",
    "button",
    "input",
    "select",
    "textarea",
    "[role=button]",
    "[role=link]",
    "[role=tab]",
  ].join(",");
  [...document.querySelectorAll(interactiveSelector)]
    .filter((node) => visible(node) && !node.closest('[aria-hidden="true"]'))
    .forEach((node, index) => {
      if (!accessibleName(node)) {
        violations.push(`${labelFor(node, index)} has no accessible name`);
      }
    });

  [...document.querySelectorAll('[aria-hidden="true"]')].forEach((hiddenRoot, rootIndex) => {
    const focusable = [...hiddenRoot.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
      + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].find((node) => visible(node) && node.getAttribute("tabindex") !== "-1");
    if (focusable) {
      violations.push(
        `${labelFor(hiddenRoot, rootIndex)} aria-hidden subtree contains focusable ${labelFor(focusable, 0)}`,
      );
    }
  });

  return violations;
});

const checkDialog = async (page) => {
  const button = page.locator(".site-account-button").first();
  if (await button.count() === 0 || !await button.isVisible()) return [];
  await button.click();
  const dialog = page.locator('[role="dialog"]').last();
  await dialog.waitFor({ state: "visible", timeout: 10_000 });
  const issues = await dialog.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const tolerance = 2;
    const output = [];
    if (rect.left < -tolerance || rect.right > innerWidth + tolerance) {
      output.push(`account dialog outside viewport (${Math.round(rect.left)}..${Math.round(rect.right)})`);
    }
    if (node.scrollWidth > node.clientWidth + tolerance) {
      output.push(`account dialog horizontal overflow ${node.scrollWidth - node.clientWidth}px`);
    }
    if (node.getAttribute("aria-modal") !== "true") {
      output.push("account dialog does not declare aria-modal=true");
    }
    const labelledBy = node.getAttribute("aria-labelledby");
    if (
      !node.getAttribute("aria-label")?.trim()
      && (!labelledBy || !document.getElementById(labelledBy)?.textContent?.trim())
    ) {
      output.push("account dialog has no accessible name");
    }
    return output;
  });
  const dialogHandle = await dialog.elementHandle();
  try {
    await page.waitForFunction(
      (node) => node instanceof Element && node.contains(document.activeElement),
      dialogHandle,
      { timeout: 2_000 },
    );
  } catch {
    issues.push("focus did not enter the account dialog");
  }
  await page.keyboard.press("Tab");
  if (!await dialog.evaluate((node) => node.contains(document.activeElement))) {
    issues.push("Tab moved focus outside the account dialog");
  }
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden", timeout: 10_000 });
  const buttonHandle = await button.elementHandle();
  try {
    await page.waitForFunction(
      (node) => node === document.activeElement,
      buttonHandle,
      { timeout: 2_000 },
    );
  } catch {
    issues.push("focus did not return to the account button");
  }
  return issues;
};

const checkMobileMenu = async (page) => {
  const button = page.locator(".site-menu-button").first();
  if (await button.count() === 0 || !await button.isVisible()) return [];
  await button.click();
  if (await button.getAttribute("aria-expanded") !== "true") {
    return ["mobile menu did not enter expanded state"];
  }
  const panel = page.locator(".site-nav.is-open");
  if (await panel.count() === 0 || !await panel.isVisible()) {
    return ["mobile menu panel is not visible"];
  }
  await page.keyboard.press("Escape");
  const issues = [];
  if (await button.getAttribute("aria-expanded") !== "false") {
    issues.push("mobile menu did not collapse on Escape");
  }
  if (!await button.evaluate((node) => node === document.activeElement)) {
    issues.push("focus did not return to the mobile menu button");
  }
  return issues;
};

const checkHomeKeyboard = async (page) => {
  const issues = [];
  const tabs = page.locator(".site-phase-tabs [role=tab]");
  if (await tabs.count() >= 2 && await tabs.first().isVisible()) {
    await tabs.first().focus();
    await page.keyboard.press("ArrowRight");
    const nextTab = tabs.nth(1);
    const nextTabHandle = await nextTab.elementHandle();
    try {
      await page.waitForFunction(
        (node) => node?.getAttribute("aria-selected") === "true",
        nextTabHandle,
        { timeout: 2_000 },
      );
    } catch {
      issues.push("ArrowRight did not select the next product phase");
    }
    try {
      await page.waitForFunction(
        (node) => node === document.activeElement,
        nextTabHandle,
        { timeout: 2_000 },
      );
    } catch {
      issues.push("ArrowRight did not move focus to the next product phase");
    }
  }

  const capability = page.locator(".site-capability-front").first();
  if (await capability.count() > 0 && await capability.isVisible()) {
    await capability.focus();
    await page.keyboard.press("Enter");
    const back = page.locator(".site-capability-flip-back").first();
    const capabilityHandle = await capability.elementHandle();
    const backHandle = await back.elementHandle();
    try {
      await page.waitForFunction(
        (node) => node?.getAttribute("aria-expanded") === "true",
        capabilityHandle,
        { timeout: 2_000 },
      );
    } catch {
      issues.push("Enter did not open the capability detail");
    }
    try {
      await page.waitForFunction(
        (node) => node === document.activeElement,
        backHandle,
        { timeout: 2_000 },
      );
    } catch {
      issues.push("capability detail did not receive focus");
    }
    await back.click();
    try {
      await page.waitForFunction(
        (node) => (
          node === document.activeElement
          && !node.closest(".site-capability-card")?.classList.contains("is-flipped")
        ),
        capabilityHandle,
        { timeout: 2_000 },
      );
    } catch {
      issues.push("capability overview did not restore focus");
    }
    await page.evaluate(async () => {
      await new Promise((resolveFrame) => {
        requestAnimationFrame(() => requestAnimationFrame(resolveFrame));
      });
    });
    await page.waitForTimeout(50);
  }
  return issues;
};

const checkConsolePreview = async (page, routeName) => page.evaluate((activeRoute) => {
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0;
  };
  const issues = [];
  const accountName = document.querySelector(".app-account-copy strong")?.textContent?.trim();
  if (accountName !== "DroneDream Pilot") {
    issues.push(`docs preview account is not active (${accountName || "missing"})`);
  }
  const sidebar = document.querySelector(".app-sidebar");
  if (!visible(sidebar)) issues.push("application sidebar is not visible");
  const nav = document.querySelector(".app-nav");
  if (!visible(nav) || nav.querySelectorAll("a").length < 4) {
    issues.push("application navigation is incomplete");
  }
  const activeNav = nav?.querySelector("a.active");
  if (!visible(activeNav)) issues.push("active application navigation item is missing");
  const blockingDialog = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')]
    .find(visible);
  if (blockingDialog) issues.push("authenticated preview is blocked by a modal dialog");

  if (activeRoute === "console-history-preview") {
    const history = document.querySelector(".history-page");
    const scroller = document.querySelector(".history-results");
    const table = scroller?.querySelector("table");
    const rightmostHeader = table?.querySelector("th:last-child");
    if (!visible(history)) issues.push("history page is not visible");
    if (!visible(scroller)) issues.push("history results scroller is not visible");
    if (!visible(table)) issues.push("history table is not visible");
    if (
      scroller
      && table
      && table.scrollWidth > scroller.clientWidth + 2
      && !["auto", "scroll"].includes(getComputedStyle(scroller).overflowX)
    ) {
      issues.push("wide history table is not owned by a horizontal scroll container");
    }
    if (scroller && table && rightmostHeader) {
      const previousScrollLeft = scroller.scrollLeft;
      const maxScrollLeft = scroller.scrollWidth - scroller.clientWidth;
      const tableNeedsScrolling = table.scrollWidth > scroller.clientWidth + 2;
      if (tableNeedsScrolling) scroller.scrollLeft = scroller.scrollWidth;
      const scrollerRect = scroller.getBoundingClientRect();
      const headerRect = rightmostHeader.getBoundingClientRect();
      if (
        headerRect.left < scrollerRect.left - 2
        || headerRect.right > scrollerRect.right + 2
      ) {
        issues.push("rightmost history header is not visible at the scroll boundary");
      }
      if (tableNeedsScrolling) {
        if (maxScrollLeft <= 0 || scroller.scrollLeft !== maxScrollLeft) {
          issues.push(
            `history results did not reach its right edge (${scroller.scrollLeft}/${maxScrollLeft})`,
          );
        }
        scroller.focus({ preventScroll: true });
        if (document.activeElement !== scroller) {
          issues.push("history results scroller cannot receive keyboard focus");
        }
      }
      scroller.scrollLeft = previousScrollLeft;
    }

    const reachableActions = [
      [".app-nav a.active", "active History navigation"],
      [".launcher-settings-button", "Settings"],
      [".page-header-actions a", "New experiment"],
      [".history-clear-filters", "Clear filters"],
      [".history-compare-button", "Compare selected"],
    ];
    for (const [selector, label] of reachableActions) {
      const action = document.querySelector(selector);
      if (!visible(action)) issues.push(`${label} action is not visible`);
    }
  }
  return issues;
}, routeName);

const results = [];
const unavailable = [];
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
  const browser = await definition.engine.launch(launchOptions);
  try {
    const profiles = browserName === "edge" ? edgeProfiles : standardProfiles;
    for (const profile of profiles) {
      for (const locale of locales) {
        const context = await browser.newContext({
          viewport: profile.viewport,
          screen: {
            width: Math.round(profile.viewport.width * profile.deviceScaleFactor),
            height: Math.round(profile.viewport.height * profile.deviceScaleFactor),
          },
          deviceScaleFactor: profile.deviceScaleFactor,
          locale: locale === "zh-CN" ? "zh-CN" : "en-US",
          reducedMotion: "reduce",
        });
        await context.addInitScript((nextLocale) => {
          localStorage.setItem("drone-dream:locale", nextLocale);
        }, locale);
        try {
          for (const route of routes) {
            const page = await context.newPage();
            const errors = [];
            const externalWarnings = [];
            const routeBaseUrl = route.baseUrl ?? baseUrl;
            page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
            page.on("requestfailed", (request) => {
              const message = `${request.method()} ${request.url()}: ${
                request.failure()?.errorText ?? "request failed"
              }`;
              if (request.failure()?.errorText === "net::ERR_ABORTED") return;
              if (sameOrigin(request.url(), routeBaseUrl)) errors.push(message);
              else externalWarnings.push(message);
            });
            page.on("response", (response) => {
              if (response.status() < 400) return;
              const message = `${response.status()} ${response.request().method()} ${response.url()}`;
              if (sameOrigin(response.url(), routeBaseUrl)) errors.push(message);
              else externalWarnings.push(message);
            });

            const url = new URL(route.path, routeBaseUrl).href;
            await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
            await page.waitForSelector(route.root, { state: "visible", timeout: 60_000 });
            await page.evaluate(async () => {
              await document.fonts.ready;
              await new Promise((resolveFrame) => {
                requestAnimationFrame(() => requestAnimationFrame(resolveFrame));
              });
            });
            await page.waitForTimeout(250);

            const layout = await collectLayout(page, route.name);
            const expectedPath = route.expectedPath
              ?? (route.name === "console" ? "/console/" : route.path);
            if (
              route.name === "console"
                ? !layout.path.startsWith(expectedPath)
                : layout.path !== expectedPath
            ) errors.push(`unexpected route ${layout.path}; expected ${expectedPath}`);
            if (layout.lang !== locale) errors.push(`html lang ${layout.lang}; expected ${locale}`);
            errors.push(...layout.violations);
            errors.push(...await collectAccessibility(page));
            if (route.name !== "console") {
              errors.push(...await checkDialog(page));
              if (profile.viewport.width <= 1050) errors.push(...await checkMobileMenu(page));
            }
            if (route.name === "home") errors.push(...await checkHomeKeyboard(page));
            if (route.consolePreview) {
              errors.push(...await checkConsolePreview(page, route.name));
            }

            const shouldCapture = browserName === "edge" || route.name === "home";
            let screenshot = "";
            if (screenshotDirectory && shouldCapture) {
              await page.evaluate(async () => {
                window.scrollTo(0, 0);
                await new Promise((resolveFrame) => {
                  requestAnimationFrame(() => requestAnimationFrame(resolveFrame));
                });
              });
              screenshot = join(
                screenshotDirectory,
                `${browserName}-${profile.name}-${locale}-${route.name}.png`,
              );
              await page.screenshot({ path: screenshot, fullPage: false });
            }

            results.push({
              browser: browserName,
              browserVersion: browser.version(),
              profile: profile.name,
              physicalViewport: profile.physicalViewport,
              viewport: profile.viewport,
              deviceScaleFactor: profile.deviceScaleFactor,
              locale,
              route: route.name,
              url,
              finalPath: layout.path,
              documentWidth: layout.documentWidth,
              viewportWidth: layout.viewportWidth,
              pricingHeights: layout.pricingHeights,
              screenshot,
              errors: [...new Set(errors)],
              externalWarnings: [...new Set(externalWarnings)],
            });
            await page.close();
          }
        } finally {
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
}

const failures = results.filter((result) => result.errors.length > 0);
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: baseUrl.href,
  consolePreviewUrl: consolePreviewUrl?.href ?? null,
  requestedBrowsers,
  unavailable,
  summary: {
    checks: results.length,
    passed: results.length - failures.length,
    failed: failures.length,
    externalWarnings: results.reduce(
      (sum, result) => sum + result.externalWarnings.length,
      0,
    ),
  },
  failures,
  results,
};

if (outputPath) {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}
console.log(JSON.stringify({
  output: outputPath || null,
  unavailable,
  summary: report.summary,
  failures: failures.map((result) => ({
    browser: result.browser,
    profile: result.profile,
    locale: result.locale,
    route: result.route,
    errors: result.errors,
  })),
}, null, 2));
if (unavailable.length > 0 || failures.length > 0) process.exitCode = 1;
