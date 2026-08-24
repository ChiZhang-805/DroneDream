import assert from "node:assert/strict";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.join(
  frontendRoot,
  "node_modules",
  ".cache",
  "five-edition-desktop-parity",
);
// These are the two real desktop client sizes measured on the supported
// Windows QA machine. The native-window acceptance script independently
// verifies the actual DWM frame and monitor work area; this browser matrix is
// the fast, deterministic pass that catches layout drift before rebuilding all
// five installers.
const viewports = [
  { id: "default", width: 1455, height: 937 },
  { id: "maximized", width: 1707, height: 1019 },
];

const autonomyRoutes = [
  ["autonomy-overview", "/autonomy"],
  ["autonomy-aircraft", "/autonomy/aircraft"],
  ["autonomy-maps", "/autonomy/maps"],
  ["autonomy-plugins", "/autonomy/plugins"],
  ["autonomy-harness", "/autonomy/plugins/harness"],
  ["autonomy-live", "/autonomy/live"],
  ["autonomy-evidence", "/autonomy/evidence"],
];

const shellStateRoutes = [
  ["quick-settings", "/assistant", "quick-settings"],
  ["settings-general", "/assistant", "settings-general"],
  ["settings-memory", "/assistant", "settings-memory"],
  ["settings-model", "/assistant", "settings-model"],
  ["settings-course", "/assistant", "settings-course"],
  ["account-menu", "/assistant", "account-menu"],
];

const sharedWorkspaceRoutes = [
  ["assistant", "/assistant"],
  ["experiment", "/jobs/new"],
  ["dashboard", "/dashboard"],
  ["history", "/history"],
  ["scenarios", "/scenarios"],
  ["compare", "/compare"],
];

const editions = [
  {
    id: "universal",
    routes: [
      ...sharedWorkspaceRoutes,
      ["lab-workspace", "/lab"],
      ["lab-hardware", "/lab/hardware"],
      ["lab-validation", "/lab/validation"],
      ["field-device", "/field/device"],
      ["field-tuning", "/field/tuning"],
      ["field-operations", "/field/operations"],
      ...autonomyRoutes,
      ...shellStateRoutes,
    ],
  },
  {
    id: "sim",
    routes: [
      ...sharedWorkspaceRoutes,
      ...autonomyRoutes,
      ...shellStateRoutes,
    ],
  },
  {
    id: "lab",
    routes: [
      ...sharedWorkspaceRoutes,
      ["workspace", "/lab"],
      ["hardware", "/lab/hardware"],
      ["validation", "/lab/validation"],
      ...autonomyRoutes,
      ...shellStateRoutes,
    ],
  },
  {
    id: "field",
    routes: [
      ...sharedWorkspaceRoutes,
      ["device", "/field/device"],
      ["tuning", "/field/tuning"],
      ["operations", "/field/operations"],
      ...autonomyRoutes,
      ...shellStateRoutes,
    ],
  },
  {
    id: "autonomy",
    routes: [
      ...sharedWorkspaceRoutes,
      ...autonomyRoutes,
      ...shellStateRoutes,
    ],
  },
];

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const manifest = [];
const pairs = new Map();

try {
  for (let editionIndex = 0; editionIndex < editions.length; editionIndex += 1) {
    const edition = editions[editionIndex];
    const port = 5210 + editionIndex;
    const origin = `http://127.0.0.1:${port}`;
    process.env.VITE_DRONEDREAM_EDITION = edition.id;
    process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
    process.env.VITE_PUBLIC_DEMO_CONSOLE = "true";
    process.env.VITE_SUPABASE_URL = "https://local-build.invalid";
    process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "local-build-placeholder";

    const server = await createServer({
      configFile: path.join(frontendRoot, "vite.config.ts"),
      root: frontendRoot,
      logLevel: "warn",
      server: { host: "127.0.0.1", port, strictPort: true },
    });
    await server.listen();

    try {
      for (const viewport of viewports) {
        const context = await browser.newContext({
          viewport,
          colorScheme: "light",
          deviceScaleFactor: 1,
        });
        await context.addInitScript(({ selectedEdition }) => {
          window.localStorage.setItem("drone-dream:locale", "en");
          window.localStorage.setItem("dronedream:universal-workspace:v2", selectedEdition);
        }, { selectedEdition: edition.id });
        const page = await context.newPage();

        try {
          for (const [surface, route, shellState] of edition.routes) {
            await page.goto(`${origin}${route}?docsPreview=1`, { waitUntil: "networkidle" });
            await page.evaluate(() => {
              document.querySelector(".account-dialog-backdrop")?.remove();
              document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
            });
            if (surface === "experiment") {
              const nameDialog = page.getByRole("dialog", { name: "New Tuning Experiment" });
              if (await nameDialog.isVisible()) {
                await nameDialog.getByLabel("Experiment name").fill(`${edition.id} desktop parity`);
                await nameDialog.getByRole("button", { name: "Continue" }).click();
                await page.locator("h1").waitFor({ state: "visible" });
              }
            }
            if (shellState === "quick-settings" || shellState?.startsWith("settings-")) {
              await page.locator(".app-header .launcher-settings-button").click();
              await page.locator(".quick-settings-dialog").waitFor({ state: "visible" });
              if (shellState?.startsWith("settings-")) {
                await page.getByRole("button", { name: "All settings" }).click();
                await page.locator(".settings-workspace-host").waitFor({ state: "visible" });
                const tab = shellState.replace(/^settings-/u, "");
                await page.locator(`#settings-tab-${tab}`).click();
                await page.locator(`#settings-panel-${tab}`).waitFor({ state: "visible" });
              }
            } else if (shellState === "account-menu") {
              await page.locator(".app-account-button").click();
              await page.locator(".account-menu-popover").waitFor({ state: "visible" });
            }
            await page.waitForTimeout(surface.includes("live") ? 1400 : 350);

            const screenshot = path.join(
              outputRoot,
              `${edition.id}-${surface}-${viewport.id}-${viewport.width}x${viewport.height}.png`,
            );
            await page.screenshot({ path: screenshot, fullPage: false });

            const metrics = await page.evaluate(() => {
              const root = document.documentElement;
              const body = document.body;
              const sidebar = document.querySelector(".app-sidebar");
              const main = document.querySelector(".app-main, .launcher-main");
              const lockup = document.querySelector(".app-title img, .universal-mode-switch-trigger img, .launcher-brand img");
              const title = document.querySelector(
                "#main-content h1, #main-content h2, main h1, main h2, .assistant-hero-question, .state-title",
              );
              const adapterScroller = document.querySelector(".field-adapter-center .field-table-scroll");
              const adapterTable = document.querySelector(".field-adapter-table");
              const adapterAction = document.querySelector(".field-adapter-table td:last-child button");
              const adapterScrollerRect = adapterScroller?.getBoundingClientRect();
              const adapterActionRect = adapterAction?.getBoundingClientRect();
              const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== "none"
                  && style.visibility !== "hidden"
                  && Number(style.opacity) !== 0
                  && rect.width > 0
                  && rect.height > 0;
              };
              const normalizedText = (element) => (
                element.getAttribute("aria-label")
                || element.textContent
                || element.getAttribute("title")
                || element.id
                || element.tagName
              ).replace(/\s+/g, " ").trim().slice(0, 160);
              const visibleHeadings = [...document.querySelectorAll("main h1, main h2, main h3")]
                .filter(isVisible)
                .map(normalizedText);
              const navigationOrder = [...document.querySelectorAll(".app-sidebar a, .app-sidebar button")]
                .filter(isVisible)
                .map(normalizedText)
                .filter(Boolean);
              const controlOrder = [...document.querySelectorAll("main button, main input, main select, main textarea, main a[href]")]
                .filter(isVisible)
                .map(normalizedText)
                .filter(Boolean);
              const horizontalClipping = [
                ...document.querySelectorAll("main h1, main h2, main h3, main button, main input, main select, main textarea, main a[href]"),
              ]
                .filter(isVisible)
                .map((element) => ({ label: normalizedText(element), rect: element.getBoundingClientRect() }))
                .filter(({ rect }) => rect.left < -1 || rect.right > window.innerWidth + 1)
                .map(({ label, rect }) => ({ label, left: rect.left, right: rect.right }));
              const titleRect = title?.getBoundingClientRect();
              const titleLineHeight = title
                ? Number.parseFloat(window.getComputedStyle(title).lineHeight)
                : 0;
              const titleLineCount = titleRect && titleLineHeight > 0
                ? Math.max(1, Math.round(titleRect.height / titleLineHeight))
                : 0;
              const overlay = document.querySelector(
                ".quick-settings-dialog, .settings-workspace-host, .account-menu-popover",
              );
              const overlayRect = overlay?.getBoundingClientRect();
              return {
                edition: root.dataset.brandEdition,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                documentWidth: Math.max(root.scrollWidth, body.scrollWidth),
                documentHeight: Math.max(root.scrollHeight, body.scrollHeight),
                sidebarWidth: sidebar?.getBoundingClientRect().width ?? 0,
                mainWidth: main?.getBoundingClientRect().width ?? 0,
                lockupWidth: lockup?.getBoundingClientRect().width ?? 0,
                lockupHeight: lockup?.getBoundingClientRect().height ?? 0,
                title: title?.textContent?.trim() ?? "",
                titleLineCount,
                visibleHeadings,
                navigationOrder,
                controlOrder,
                horizontalClipping,
                overlayPresent: Boolean(overlay && isVisible(overlay)),
                overlayFits: !overlayRect
                  || (overlayRect.left >= -1
                    && overlayRect.top >= -1
                    && overlayRect.right <= window.innerWidth + 1
                    && overlayRect.bottom <= window.innerHeight + 1),
                overlayHeadings: overlay
                  ? [...overlay.querySelectorAll("h1, h2, h3")].filter(isVisible).map(normalizedText)
                  : [],
                overlayControlOrder: overlay
                  ? [...overlay.querySelectorAll("button, input, select, textarea, a[href]")]
                    .filter(isVisible)
                    .map(normalizedText)
                    .filter(Boolean)
                  : [],
                mobileNavigationVisible: [...document.querySelectorAll(".mobile-menu-button, .app-mobile-menu")]
                  .some(isVisible),
                errorBoundary: Boolean(document.querySelector(".error-page, [data-error-boundary]")),
                adapterTableFits: !adapterScroller || !adapterTable
                  ? true
                  : adapterTable.scrollWidth <= adapterScroller.clientWidth + 1,
                adapterActionVisible: !adapterScrollerRect || !adapterActionRect
                  ? true
                  : adapterActionRect.right <= adapterScrollerRect.right + 1,
              };
            });

            const caseLabel = `${edition.id}/${surface}/${viewport.id}`;
            assert.equal(metrics.edition, edition.id, `${caseLabel}: wrong edition theme`);
            assert.equal(metrics.viewportWidth, viewport.width);
            assert.equal(metrics.viewportHeight, viewport.height);
            assert(metrics.sidebarWidth >= 200, `${caseLabel}: sidebar collapsed unexpectedly`);
            const expectedMainWidth = Math.min(1200, viewport.width - metrics.sidebarWidth - 32);
            assert(
              metrics.mainWidth >= expectedMainWidth,
              `${caseLabel}: main workspace is too narrow (${metrics.mainWidth}px < ${expectedMainWidth}px)`,
            );
            assert(metrics.lockupWidth >= 100, `${caseLabel}: brand lockup is missing or too small`);
            assert(metrics.lockupHeight >= 20, `${caseLabel}: brand lockup is missing or too short`);
            assert(metrics.documentWidth <= viewport.width + 1, `${caseLabel}: horizontal overflow ${metrics.documentWidth}px`);
            assert(metrics.documentHeight <= viewport.height + 1, `${caseLabel}: page-level vertical overflow ${metrics.documentHeight}px`);
            assert(!metrics.mobileNavigationVisible, `${caseLabel}: mobile navigation rendered in desktop mode`);
            assert(!metrics.errorBoundary, `${caseLabel}: error boundary rendered`);
            assert(metrics.title.length > 0, `${caseLabel}: primary page title is missing`);
            assert.equal(metrics.horizontalClipping.length, 0, `${caseLabel}: horizontally clipped controls ${JSON.stringify(metrics.horizontalClipping)}`);
            assert.equal(metrics.overlayPresent, Boolean(shellState), `${caseLabel}: shell overlay state did not match the case`);
            assert(metrics.overlayFits, `${caseLabel}: shell overlay is clipped by the window`);
            assert(metrics.adapterTableFits, `${caseLabel}: adapter table is wider than its visible panel`);
            assert(metrics.adapterActionVisible, `${caseLabel}: adapter action column is clipped`);

            const pairKey = `${edition.id}/${surface}`;
            const previous = pairs.get(pairKey);
            if (previous) {
              assert.equal(metrics.title, previous.metrics.title, `${pairKey}: title changed between window states`);
              assert.equal(metrics.titleLineCount, previous.metrics.titleLineCount, `${pairKey}: title wrapping changed between window states`);
              assert.deepEqual(metrics.visibleHeadings, previous.metrics.visibleHeadings, `${pairKey}: module heading order changed between window states`);
              assert.deepEqual(metrics.navigationOrder, previous.metrics.navigationOrder, `${pairKey}: navigation order changed between window states`);
              assert.deepEqual(metrics.controlOrder, previous.metrics.controlOrder, `${pairKey}: visible control order changed between window states`);
              assert.deepEqual(metrics.overlayHeadings, previous.metrics.overlayHeadings, `${pairKey}: overlay heading order changed between window states`);
              assert.deepEqual(metrics.overlayControlOrder, previous.metrics.overlayControlOrder, `${pairKey}: overlay control order changed between window states`);
            } else {
              pairs.set(pairKey, { viewport: viewport.id, metrics });
            }

            manifest.push({ edition: edition.id, surface, route, viewport, screenshot, metrics });
          }
        } finally {
          await context.close();
        }
      }
    } finally {
      await server.close();
    }
  }
} finally {
  await browser.close();
}

await writeFile(
  path.join(outputRoot, "manifest.json"),
  `${JSON.stringify({ viewports, cases: manifest }, null, 2)}\n`,
  "utf8",
);
process.stdout.write(`${JSON.stringify({ viewports, count: manifest.length, outputRoot }, null, 2)}\n`);
