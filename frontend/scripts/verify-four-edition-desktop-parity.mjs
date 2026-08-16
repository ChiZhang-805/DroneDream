import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.join(
  frontendRoot,
  "node_modules",
  ".cache",
  "four-edition-desktop-parity",
);
const viewport = { width: 1440, height: 900 };

const editions = [
  {
    id: "universal",
    routes: [
      ["assistant", "/assistant"],
      ["vehicle-studio", "/vehicle-studio"],
      ["autonomy-overview", "/autonomy"],
      ["autonomy-aircraft", "/autonomy/aircraft"],
      ["autonomy-maps", "/autonomy/maps"],
      ["autonomy-live", "/autonomy/live"],
      ["dashboard", "/dashboard"],
      ["history", "/history"],
      ["scenarios", "/scenarios"],
    ],
  },
  {
    id: "sim",
    routes: [
      ["assistant", "/assistant"],
      ["experiment", "/jobs/new"],
      ["autonomy-overview", "/autonomy"],
      ["dashboard", "/dashboard"],
      ["history", "/history"],
      ["scenarios", "/scenarios"],
    ],
  },
  {
    id: "lab",
    routes: [
      ["assistant", "/assistant"],
      ["experiment", "/jobs/new"],
      ["autonomy-overview", "/autonomy"],
      ["workspace", "/lab"],
      ["hardware", "/lab/hardware"],
      ["validation", "/lab/validation"],
      ["history", "/history"],
    ],
  },
  {
    id: "field",
    routes: [
      ["assistant", "/assistant"],
      ["autonomy-overview", "/autonomy"],
      ["device", "/field/device"],
      ["tuning", "/field/tuning"],
      ["operations", "/field/operations"],
      ["history", "/history"],
    ],
  },
];

await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const manifest = [];

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
      for (const [surface, route] of edition.routes) {
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
        await page.waitForTimeout(surface.includes("vehicle") || surface.includes("live") ? 1400 : 350);

        const screenshot = path.join(outputRoot, `${edition.id}-${surface}-1440x900.png`);
        await page.screenshot({ path: screenshot, fullPage: false });

        const metrics = await page.evaluate(() => {
          const root = document.documentElement;
          const body = document.body;
          const sidebar = document.querySelector(".app-sidebar");
          const main = document.querySelector(".app-main");
          const lockup = document.querySelector(".app-title img, .universal-mode-switch-trigger img");
          const title = document.querySelector("h1, .assistant-hero-question, .vehicle-studio-title");
          const adapterScroller = document.querySelector(".field-adapter-center .field-table-scroll");
          const adapterTable = document.querySelector(".field-adapter-table");
          const adapterAction = document.querySelector(".field-adapter-table td:last-child button");
          const adapterScrollerRect = adapterScroller?.getBoundingClientRect();
          const adapterActionRect = adapterAction?.getBoundingClientRect();
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
            errorBoundary: Boolean(document.querySelector(".error-page, [data-error-boundary]")),
            adapterTableFits: !adapterScroller || !adapterTable
              ? true
              : adapterTable.scrollWidth <= adapterScroller.clientWidth + 1,
            adapterActionVisible: !adapterScrollerRect || !adapterActionRect
              ? true
              : adapterActionRect.right <= adapterScrollerRect.right + 1,
          };
        });

        assert.equal(metrics.edition, edition.id, `${edition.id}/${surface}: wrong edition theme`);
        assert.equal(metrics.viewportWidth, viewport.width);
        assert.equal(metrics.viewportHeight, viewport.height);
        assert(metrics.sidebarWidth >= 200, `${edition.id}/${surface}: sidebar collapsed unexpectedly`);
        assert(metrics.mainWidth >= 1000, `${edition.id}/${surface}: main workspace is too narrow`);
        assert(metrics.lockupWidth >= 100, `${edition.id}/${surface}: brand lockup is missing or too small`);
        assert(metrics.lockupHeight >= 20, `${edition.id}/${surface}: brand lockup is missing or too short`);
        assert(metrics.documentWidth <= viewport.width + 1, `${edition.id}/${surface}: horizontal overflow ${metrics.documentWidth}px`);
        assert(metrics.documentHeight <= viewport.height + 1, `${edition.id}/${surface}: page-level vertical overflow ${metrics.documentHeight}px`);
        assert(!metrics.errorBoundary, `${edition.id}/${surface}: error boundary rendered`);
        assert(metrics.title.length > 0, `${edition.id}/${surface}: primary page title is missing`);
        assert(metrics.adapterTableFits, `${edition.id}/${surface}: adapter table is wider than its visible panel`);
        assert(metrics.adapterActionVisible, `${edition.id}/${surface}: adapter action column is clipped`);

        manifest.push({ edition: edition.id, surface, route, screenshot, metrics });
      }
    } finally {
      await context.close();
      await server.close();
    }
  }
} finally {
  await browser.close();
}

await writeFile(
  path.join(outputRoot, "manifest.json"),
  `${JSON.stringify({ viewport, cases: manifest }, null, 2)}\n`,
  "utf8",
);
process.stdout.write(`${JSON.stringify({ viewport, count: manifest.length, outputRoot }, null, 2)}\n`);
