import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.resolve(
  frontendRoot,
  "..",
  "artifacts",
  "test-runs",
  "school-map-visual-current",
);
const host = "127.0.0.1";
const port = 5198;
const externalOrigin = process.env.SCHOOL_MAP_VERIFY_ORIGIN?.replace(/\/$/u, "");
const origin = externalOrigin ?? `http://${host}:${port}`;
const screenshotPrefix = externalOrigin ? "online-" : "";

if (!externalOrigin) {
  process.env.VITE_API_BASE_URL = origin;
  process.env.VITE_PUBLIC_DEMO_CONSOLE = "true";
  process.env.VITE_SUPABASE_URL = "https://local-build.invalid";
  process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "local-build-placeholder";
}

await mkdir(outputRoot, { recursive: true });
const server = externalOrigin ? null : await createServer({
  configFile: path.join(frontendRoot, "vite.console.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
});
let browser;

async function clearBlockingDialog(page) {
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
  });
}

async function openProductPage(page, pathname, selector) {
  await page.goto(`${origin}${pathname}`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  await page.locator(selector).waitFor({ state: "visible" });
}

try {
  await server?.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    colorScheme: "light",
    deviceScaleFactor: 1,
  });
  await context.addInitScript(() => {
    window.localStorage.setItem("dronedream:universal-workspace:v2", "universal");
    window.localStorage.setItem("drone-dream:locale", "en");
  });
  const page = await context.newPage();

  // The production Live route is now the real camera surface. Validate the
  // current, reachable map repository here; geometric scene contracts remain
  // covered by the school-map unit and mission-validation suites.
  await openProductPage(page, "/console/autonomy/maps", ".autonomy-repository-page");
  const schoolMap = page.locator(".autonomy-repository-grid article").filter({ hasText: "Kumpula Campus" });
  if (await schoolMap.count() !== 1) throw new Error("Map repository must expose exactly one Kumpula Campus card.");
  if (await schoolMap.getAttribute("data-selected") !== "false") throw new Error("Map repository must begin without a selected map.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Map repository must not expose an in-product map creator.");
  if (await page.getByRole("button", { name: "Import map", exact: true }).count() !== 0) throw new Error("The sole-map repository must not expose an import action.");
  if (await page.getByRole("region", { name: "3D UAV Corridor" }).count() !== 0) throw new Error("The 3D corridor must remain inside the map detail dialog.");
  const mapScreenshot = path.join(outputRoot, `${screenshotPrefix}school-map-repository-1600x1000.png`);
  await page.screenshot({ path: mapScreenshot, fullPage: false });
  await schoolMap.locator(".autonomy-repository-card-surface").dblclick();
  const mapDialog = page.getByRole("dialog", { name: "Kumpula Campus" });
  await mapDialog.waitFor({ state: "visible" });
  const mapCanvas = mapDialog.locator(".autonomy-repository-3d-view canvas");
  await mapCanvas.waitFor({ state: "visible" });
  await page.waitForTimeout(500);
  if (await mapDialog.getByText("No verified 3D geometry is available", { exact: false }).count()) {
    throw new Error("Kumpula Campus failed to load its verified 3D geometry.");
  }
  const mapDetailScreenshot = path.join(outputRoot, `${screenshotPrefix}kumpula-campus-3d-detail-1600x1000.png`);
  await page.screenshot({ path: mapDetailScreenshot, fullPage: false });
  await mapDialog.getByRole("button", { name: "Close" }).click();

  await openProductPage(page, "/console/autonomy/aircraft", ".autonomy-repository-page");
  if (await page.locator(".autonomy-repository-grid article").count() !== 13) {
    throw new Error("Aircraft repository must expose all thirteen reviewed PX4 models.");
  }
  const myDrone = page.locator(".autonomy-repository-grid article").filter({ hasText: "X500 Depth" });
  if (await myDrone.count() !== 1) throw new Error("Aircraft repository must expose exactly one X500 Depth card.");
  if (await myDrone.getAttribute("data-selected") !== "false") throw new Error("Aircraft repository must begin without a selected aircraft.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Aircraft repository must not expose an in-product model creator.");
  if (await page.getByRole("button", { name: "Import aircraft", exact: true }).count() !== 1) throw new Error("Aircraft repository is missing its external import action.");
  const aircraftScreenshot = path.join(outputRoot, `${screenshotPrefix}my-drone-repository-1600x1000.png`);
  await page.screenshot({ path: aircraftScreenshot, fullPage: false });

  await openProductPage(page, "/console/autonomy", ".autonomy-command-page");
  await page.locator(".assistant-add-button").click();
  const contextPopover = page.locator(".autonomy-context-popover");
  await contextPopover.waitFor({ state: "visible" });
  if (await contextPopover.getByText("Select aircraft", { exact: true }).count() !== 1) throw new Error("Mission Context must begin without a selected aircraft.");
  if (await contextPopover.getByText("Select map", { exact: true }).count() !== 1) throw new Error("Mission Context must begin without a selected map.");
  const selectMap = contextPopover.getByRole("menuitem", { name: "Select map", exact: true });
  await selectMap.hover();
  const mapSubmenu = contextPopover.locator(".autonomy-context-submenu");
  await mapSubmenu.waitFor({ state: "visible" });
  if (await mapSubmenu.getByRole("menuitemradio", { name: "Kumpula Campus", exact: true }).count() !== 1) {
    throw new Error("Map submenu must expose the sole Kumpula Campus selection.");
  }
  const [mapRowBox, submenuBox] = await Promise.all([selectMap.boundingBox(), mapSubmenu.boundingBox()]);
  if (!mapRowBox || !submenuBox) throw new Error("Map submenu geometry could not be measured.");
  if (submenuBox.y >= mapRowBox.y) throw new Error("Map submenu must expand upward when the composer is near the viewport bottom.");
  if (submenuBox.y < 0 || submenuBox.y + submenuBox.height > 1000) throw new Error("Map submenu must stay inside the viewport.");
  const submenuMetrics = await mapSubmenu.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      scrollbarWidth: style.scrollbarWidth,
    };
  });
  if (submenuMetrics.scrollHeight > submenuMetrics.clientHeight) throw new Error("A one-map submenu must not create unnecessary scrolling.");
  if (submenuMetrics.scrollbarWidth !== "none") throw new Error("Map submenu scrollbar must remain visually hidden.");
  const contextScreenshot = path.join(outputRoot, `${screenshotPrefix}autonomy-mission-context-1600x1000.png`);
  await page.screenshot({ path: contextScreenshot, fullPage: false });

  process.stdout.write(`${JSON.stringify({
    status: "pass",
    screenshots: [mapScreenshot, mapDetailScreenshot, aircraftScreenshot, contextScreenshot],
  }, null, 2)}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server?.close();
}
