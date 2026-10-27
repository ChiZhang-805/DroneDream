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
  if (await page.locator(".autonomy-repository-grid article").count() !== 6) throw new Error("Map repository must expose exactly six qualified maps.");
  const pendingMaps = page.locator(".autonomy-repository-grid article.autonomy-repository-pending");
  if (await pendingMaps.count() !== 0) throw new Error("Qualified maps must replace every pending map card.");
  if (await page.locator(".autonomy-repository-grid article[data-catalog-resource='true']").count() !== 6) {
    throw new Error("Every visible map card must resolve to a real catalog resource.");
  }
  if (await schoolMap.getAttribute("data-selected") !== "false") throw new Error("Map repository must begin without a selected map.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Map repository must not expose an in-product map creator.");
  if (await page.getByRole("button", { name: "Import map", exact: true }).count() !== 1) throw new Error("The map repository must expose the upload checklist.");
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
  const geometryResponse = await page.request.get(`${origin}/console/asset-geometry/maps/kumpula-campus.json`);
  const geometry = await geometryResponse.json();
  if (geometry.building_footprints?.length !== 42) throw new Error("Kumpula Campus must expose all 42 verified building footprints.");
  for (const building of geometry.building_footprints) {
    for (const field of ["name", "name_zh", "function", "function_zh"]) {
      if (typeof building[field] !== "string" || !building[field].trim()) {
        throw new Error(`Building ${building.building_id} is missing ${field}.`);
      }
    }
  }
  const buildingCard = mapDialog.locator(".autonomy-repository-building-card");
  await buildingCard.waitFor({ state: "visible" });
  if (await buildingCard.locator("dt").allTextContents().then((labels) => labels.join("|") !== "No.|Name|Function")) {
    throw new Error("A selected building must show its number, name, and function.");
  }
  if (await buildingCard.getAttribute("data-building-number") !== "001") throw new Error("Building 001 must be selected by default.");
  if (await buildingCard.getByRole("button").count()) throw new Error("The persistent building card must not expose a separate close button.");
  const canvasBox = await mapCanvas.boundingBox();
  if (!canvasBox) throw new Error("Kumpula Campus canvas geometry could not be measured.");
  let changedBuilding = false;
  for (const [xRatio, yRatio] of [[0.43, 0.49], [0.55, 0.54], [0.62, 0.47], [0.49, 0.43], [0.68, 0.52]]) {
    await mapCanvas.click({ position: { x: canvasBox.width * xRatio, y: canvasBox.height * yRatio } });
    if (await buildingCard.getAttribute("data-building-number") !== "001") {
      changedBuilding = true;
      break;
    }
  }
  if (!changedBuilding) throw new Error("Clicking another building must update the persistent building card.");
  const mapDetailScreenshot = path.join(outputRoot, `${screenshotPrefix}kumpula-campus-3d-detail-1600x1000.png`);
  await page.screenshot({ path: mapDetailScreenshot, fullPage: false });
  await mapDialog.getByRole("button", { name: "Close", exact: true }).click();

  const generatedMaps = [
    ["Meilahti Hospital Campus", "meilahti-hospital-campus", 87],
    ["Kalasatama Waterfront", "kalasatama-waterfront", 105],
    ["Vuosaari Harbour", "vuosaari-harbour", 62],
    ["Suomenlinna Sea Fortress", "suomenlinna-sea-fortress", 135],
    ["Uutela Coastal Forest", "uutela-coastal-forest", 22],
  ];
  for (const [mapName, geometryKey, buildingCount] of generatedMaps) {
    const card = page.locator(".autonomy-repository-grid article").filter({ hasText: mapName });
    await card.locator(".autonomy-repository-card-surface").dblclick();
    const dialog = page.getByRole("dialog", { name: mapName });
    await dialog.waitFor({ state: "visible" });
    await dialog.locator(".autonomy-repository-3d-view canvas").waitFor({ state: "visible" });
    if (await dialog.getByText("No verified 3D geometry is available", { exact: false }).count()) {
      throw new Error(`${mapName} failed to load its generated 3D geometry.`);
    }
    const response = await page.request.get(`${origin}/console/asset-geometry/maps/${geometryKey}.json`);
    if (!response.ok()) throw new Error(`${mapName} geometry request failed.`);
    const generatedGeometry = await response.json();
    if (generatedGeometry.building_footprints?.length !== buildingCount) {
      throw new Error(`${mapName} must expose all ${buildingCount} registered building footprints.`);
    }
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
  }

  await openProductPage(page, "/console/autonomy/aircraft", ".autonomy-repository-page");
  if (await page.locator(".autonomy-repository-grid article").count() !== 6) {
    throw new Error("Aircraft repository must expose one admitted X500 Depth model and five pending cards.");
  }
  const pendingAircraft = page.locator(".autonomy-repository-grid article.autonomy-repository-pending");
  if (await pendingAircraft.count() !== 5) throw new Error("Aircraft repository must expose five disabled pending cards.");
  if (await pendingAircraft.locator(".autonomy-repository-delete:disabled").count() !== 5) throw new Error("Pending aircraft delete controls must remain visible and disabled.");
  const myDrone = page.locator(".autonomy-repository-grid article").filter({ hasText: "X500 Depth" });
  if (await myDrone.count() !== 1) throw new Error("Aircraft repository must expose exactly one X500 Depth card.");
  if (await myDrone.getAttribute("data-selected") !== "false") throw new Error("Aircraft repository must begin without a selected aircraft.");
  if (await page.locator(".autonomy-asset-toolbar button").count() !== 0) throw new Error("Aircraft repository must not expose an in-product model creator.");
  if (await page.getByRole("button", { name: "Import aircraft", exact: true }).count() !== 1) throw new Error("Aircraft repository is missing its external import action.");
  const aircraftScreenshot = path.join(outputRoot, `${screenshotPrefix}my-drone-repository-1600x1000.png`);
  await page.screenshot({ path: aircraftScreenshot, fullPage: false });
  await myDrone.locator(".autonomy-repository-card-surface").dblclick();
  const aircraftDialog = page.getByRole("dialog", { name: "X500 Depth" });
  await aircraftDialog.waitFor({ state: "visible" });
  const aircraftCanvas = aircraftDialog.locator(".autonomy-repository-3d-view canvas");
  await aircraftCanvas.waitFor({ state: "visible" });
  const aircraftCanvasBox = await aircraftCanvas.boundingBox();
  if (!aircraftCanvasBox) throw new Error("X500 canvas geometry could not be measured.");
  const partCard = aircraftDialog.locator(".autonomy-vehicle-part-card");
  if (await partCard.count()) throw new Error("The X500 part card must stay hidden until a part is selected.");
  for (const [xRatio, yRatio] of [[0.5, 0.5], [0.48, 0.44], [0.57, 0.48], [0.42, 0.52]]) {
    await aircraftCanvas.click({ position: { x: aircraftCanvasBox.width * xRatio, y: aircraftCanvasBox.height * yRatio } });
    if (await partCard.isVisible()) break;
  }
  if (!await partCard.isVisible()) throw new Error("Clicking an X500 component must open its part card.");
  if (!await aircraftDialog.locator(".autonomy-repository-3d-view[data-selected-vehicle-part]").count()) {
    throw new Error("Clicking an X500 component must mark that component as the highlighted selection.");
  }
  if (await partCard.locator("dt").allTextContents().then((labels) => labels.join("|") !== "No.|Name|Function")) {
    throw new Error("A selected aircraft part must show its number, name, and function.");
  }
  const aircraftDetailScreenshot = path.join(outputRoot, `${screenshotPrefix}x500-depth-3d-detail-1600x1000.png`);
  await page.screenshot({ path: aircraftDetailScreenshot, fullPage: false });
  await aircraftDialog.getByRole("button", { name: "Close", exact: true }).click();

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
  const expectedMapNames = [
    "Kumpula Campus",
    "Meilahti Hospital Campus",
    "Kalasatama Waterfront",
    "Vuosaari Harbour",
    "Suomenlinna Sea Fortress",
    "Uutela Coastal Forest",
  ];
  for (const mapName of expectedMapNames) {
    if (await mapSubmenu.getByRole("menuitemradio", { name: mapName, exact: true }).count() !== 1) {
      throw new Error(`Map submenu is missing the qualified ${mapName} selection.`);
    }
  }
  if (await mapSubmenu.locator(".autonomy-context-choice:not(.is-clear)").count() !== expectedMapNames.length) {
    throw new Error("Map submenu must expose exactly the six qualified maps.");
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
  if (submenuMetrics.scrollbarWidth !== "none") throw new Error("Map submenu scrollbar must remain visually hidden.");
  const contextScreenshot = path.join(outputRoot, `${screenshotPrefix}autonomy-mission-context-1600x1000.png`);
  await page.screenshot({ path: contextScreenshot, fullPage: false });
  await contextPopover.getByRole("menuitem", { name: "Select aircraft", exact: true }).hover();
  const aircraftOptions = contextPopover.locator(".autonomy-context-submenu .autonomy-context-choice:not(.is-clear)");
  await aircraftOptions.filter({ hasText: "X500 Depth" }).waitFor({ state: "visible" });
  if (await aircraftOptions.count() !== 1 || await aircraftOptions.first().innerText() !== "X500 Depth") {
    throw new Error("Aircraft picker must only expose the admitted X500 Depth default.");
  }

  process.stdout.write(`${JSON.stringify({
    status: "pass",
    screenshots: [mapScreenshot, mapDetailScreenshot, aircraftScreenshot, aircraftDetailScreenshot, contextScreenshot],
  }, null, 2)}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server?.close();
}
