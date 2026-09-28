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
  const schoolMap = page.locator(".autonomy-repository-grid article").filter({ hasText: "School Map" });
  if (await schoolMap.count() !== 1) throw new Error("Map repository must expose exactly one School Map card.");
  if (await schoolMap.getAttribute("data-selected") !== "true") throw new Error("School Map must be the default selected map.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Map repository must not expose an in-product map creator.");
  if (await page.getByRole("button", { name: "Import map", exact: true }).count() !== 1) throw new Error("Map repository is missing its external import action.");
  const mapScreenshot = path.join(outputRoot, `${screenshotPrefix}school-map-repository-1600x1000.png`);
  await page.screenshot({ path: mapScreenshot, fullPage: false });

  await openProductPage(page, "/console/autonomy/aircraft", ".autonomy-repository-page");
  const myDrone = page.locator(".autonomy-repository-grid article").filter({ hasText: "My Drone" });
  if (await myDrone.count() !== 1) throw new Error("Aircraft repository must expose exactly one My Drone card.");
  if (await myDrone.getAttribute("data-selected") !== "true") throw new Error("My Drone must be the default selected aircraft.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Aircraft repository must not expose an in-product model creator.");
  if (await page.getByRole("button", { name: "Import aircraft", exact: true }).count() !== 1) throw new Error("Aircraft repository is missing its external import action.");
  const aircraftScreenshot = path.join(outputRoot, `${screenshotPrefix}my-drone-repository-1600x1000.png`);
  await page.screenshot({ path: aircraftScreenshot, fullPage: false });

  await openProductPage(page, "/console/autonomy", ".autonomy-command-page");
  await page.locator(".assistant-add-button").click();
  const contextPopover = page.locator(".autonomy-context-popover");
  await contextPopover.waitFor({ state: "visible" });
  if (await contextPopover.getByText("My Drone", { exact: true }).count() !== 1) throw new Error("Mission Context must expose exactly one My Drone entry.");
  if (await contextPopover.getByText("School Map", { exact: true }).count() !== 1) throw new Error("Mission Context must expose exactly one School Map entry.");
  const contextScreenshot = path.join(outputRoot, `${screenshotPrefix}autonomy-mission-context-1600x1000.png`);
  await page.screenshot({ path: contextScreenshot, fullPage: false });

  process.stdout.write(`${JSON.stringify({
    status: "pass",
    screenshots: [mapScreenshot, aircraftScreenshot, contextScreenshot],
  }, null, 2)}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server?.close();
}
