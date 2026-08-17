import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.join(frontendRoot, "node_modules", ".cache", "school-map-and-drone");
const host = "127.0.0.1";
const port = 5198;
const externalOrigin = process.env.SCHOOL_MAP_VERIFY_ORIGIN?.replace(/\/$/, "");
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

async function changeSchoolMapView(page, schoolCanvas, buttonName, cameraPreset) {
  const button = page.getByRole("button", { name: buttonName, exact: true });
  const isFloorButton = /^(ALL|L[123])$/.test(buttonName);
  const isAlreadySelectedFloor = isFloorButton && await button.getAttribute("aria-pressed") === "true";
  if (!isAlreadySelectedFloor) {
    const marker = `before-${buttonName}-${Date.now()}`;
    await schoolCanvas.evaluate((canvas, value) => {
      canvas.dataset.schoolMapVerificationMarker = value;
    }, marker);
    await button.click();
    await page.waitForFunction((value) => {
      const canvas = document.querySelector('.autonomy-world-3d[data-scene="school-campus-v1"] canvas');
      return canvas instanceof HTMLCanvasElement
        && canvas.dataset.schoolMapVerificationMarker !== value;
    }, marker);
  }
  await schoolCanvas.waitFor({ state: "visible" });
  await page.evaluate((preset) => {
    window.dispatchEvent(new CustomEvent("dronedream:school-map-camera", { detail: { preset } }));
  }, cameraPreset);
  await page.waitForTimeout(700);
}

try {
  await server?.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: "light", deviceScaleFactor: 1 });
  await context.addInitScript(() => {
    window.localStorage.setItem("dronedream:universal-workspace:v2", "universal");
    window.localStorage.setItem("drone-dream:locale", "en");
  });
  const page = await context.newPage();

  await page.goto(`${origin}/console/autonomy/live`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  const schoolCanvas = page.locator('.autonomy-world-3d[data-scene="school-campus-v1"] canvas');
  await schoolCanvas.waitFor({ state: "visible" });
  await page.waitForTimeout(1800);
  const world = page.locator(".autonomy-world-3d");
  if (await world.getAttribute("data-xray") !== "false") throw new Error("School Map must open in solid mode.");
  if (Number(await world.getAttribute("data-road-segments")) < 8) throw new Error("School Map road graph is incomplete.");
  if (Number(await world.getAttribute("data-road-junctions")) < 6) throw new Error("School Map intersections are incomplete.");
  const vehicleDiameter = Number(await world.getAttribute("data-vehicle-collision-diameter-m"));
  const minimumRoadWidth = Number(await world.getAttribute("data-min-road-width-m"));
  const openDoorClearance = Number(await world.getAttribute("data-open-door-clearance-m"));
  if (!(minimumRoadWidth > vehicleDiameter * 4)) throw new Error("School Map roads do not preserve the reviewed My Drone operating envelope.");
  if (!(openDoorClearance > vehicleDiameter * 2)) throw new Error("School Map teaching entrance does not preserve the reviewed My Drone door clearance.");
  if (await page.getByRole("button", { name: "X-ray" }).count() !== 1) throw new Error("School Map is missing the X-ray control.");
  for (const label of ["ALL", "L1", "L2", "L3"]) {
    if (await page.getByRole("button", { name: label, exact: true }).count() !== 1) throw new Error(`School Map is missing ${label}.`);
  }
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}school-map-solid-1600x1000.png`), fullPage: false });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("dronedream:school-map-camera", { detail: { preset: "teaching-entrance" } })));
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}school-map-entrances-1600x1000.png`), fullPage: false });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("dronedream:school-map-camera", { detail: { preset: "cafeteria-entrance" } })));
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}school-map-cafeteria-entrance-1600x1000.png`), fullPage: false });
  await page.reload({ waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  await schoolCanvas.waitFor({ state: "visible" });
  await page.waitForTimeout(1000);
  const canvasBounds = await schoolCanvas.boundingBox();
  if (!canvasBounds) throw new Error("School Map canvas bounds are unavailable for orbit verification.");
  await page.mouse.move(canvasBounds.x + canvasBounds.width * 0.56, canvasBounds.y + canvasBounds.height * 0.52);
  await page.mouse.down();
  await page.mouse.move(canvasBounds.x + canvasBounds.width * 0.76, canvasBounds.y + canvasBounds.height * 0.47, { steps: 14 });
  await page.mouse.up();
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}school-map-solid-west-angle-1600x1000.png`), fullPage: false });
  await changeSchoolMapView(page, schoolCanvas, "X-ray", "teaching-stair");
  if (await world.getAttribute("data-xray") !== "true") throw new Error("X-ray state did not reach the rendered world.");
  for (const floor of ["L1", "L2", "L3"]) {
    await changeSchoolMapView(page, schoolCanvas, floor, "teaching-stair");
    await page.screenshot({
      path: path.join(outputRoot, `${screenshotPrefix}school-map-xray-level-${floor.slice(1)}-1600x1000.png`),
      fullPage: false,
    });
  }
  await changeSchoolMapView(page, schoolCanvas, "L1", "cafeteria-stair");
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}school-map-xray-cafeteria-stair-1600x1000.png`), fullPage: false });
  await changeSchoolMapView(page, schoolCanvas, "Solid", "teaching-stair");
  for (const floor of ["L1", "L2", "L3"]) {
    await changeSchoolMapView(page, schoolCanvas, floor, "teaching-stair");
    await page.screenshot({
      path: path.join(outputRoot, `${screenshotPrefix}school-map-solid-level-${floor.slice(1)}-1600x1000.png`),
      fullPage: false,
    });
  }

  await page.goto(`${origin}/console/vehicle-studio`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  await page.locator(".vehicle-viewport-stage canvas").waitFor({ state: "visible" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}my-drone-vehicle-studio-1600x1000.png`), fullPage: false });
  const vehicleText = await page.locator("body").innerText();
  const inputValues = await page.locator("input").evaluateAll((elements) => elements.map((element) => element.value));
  if (!vehicleText.includes("My Drone") && !inputValues.includes("My Drone")) throw new Error(`Vehicle Studio did not open My Drone. Inputs: ${inputValues.join(" | ")}`);
  if (await page.getByText("Jetson Orin NX compute enclosure", { exact: true }).count() < 1) throw new Error("My Drone is missing its onboard compute component.");

  await page.goto(`${origin}/console/assistant`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  await page.locator(".assistant-add-button").click();
  if (await page.getByText("My Drone", { exact: true }).count() !== 1) throw new Error("Tuning Chat + must expose exactly one My Drone entry.");
  if (await page.getByText("School Map", { exact: true }).count() !== 1) throw new Error("Tuning Chat + must expose exactly one School Map entry.");
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}tuning-chat-public-assets-1600x1000.png`), fullPage: false });

  await page.evaluate(() => {
    const updatedAt = new Date().toISOString();
    const legacyMap = {
      schemaVersion: 2,
      id: "map-legacy-5-environment",
      version: 3,
      status: "draft",
      qualificationReceiptId: null,
      contentHash: null,
      name: "5 environment",
      representation: "hybrid-3d",
      coordinateFrame: "ENU",
      resolutionM: 0.1,
      floorCount: 1,
      liveUpdates: "depth-fusion",
      calibrated: false,
      compilerSceneId: null,
      semanticLayers: ["free-space", "people"],
      planningLayers: ["collision-geometry", "occupancy"],
      origin: { latitude: null, longitude: null, altitudeM: null },
      boundsM: { x: 40, y: 30, z: 12 },
      confidencePercent: 0,
      sourceFiles: [],
      updatedAt,
    };
    window.localStorage.setItem("dronedream:autonomy-workspace:v2:local:universal", JSON.stringify({
      schemaVersion: 2,
      mapPack: legacyMap,
      mission: { schemaVersion: 2, mapPackId: legacyMap.id, updatedAt },
    }));
    window.localStorage.setItem("dronedream:autonomy-assets:v1:local:universal", JSON.stringify({
      schemaVersion: 1,
      aircraft: [],
      maps: [legacyMap],
    }));
  });
  await page.goto(`${origin}/console/autonomy`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  await page.locator(".assistant-add-button").click();
  const contextPopover = page.locator(".autonomy-context-popover");
  await contextPopover.waitFor({ state: "visible" });
  const contextGeometry = await contextPopover.evaluate((element) => {
    const headers = Array.from(element.querySelectorAll(".autonomy-context-group > header span"));
    const headerRows = Array.from(element.querySelectorAll(".autonomy-context-group > header"));
    return {
      width: element.getBoundingClientRect().width,
      headersFit: headers.map((header) => getComputedStyle(header).whiteSpace === "nowrap"),
      rowsFit: headerRows.map((header) => getComputedStyle(header).flexWrap === "nowrap"),
    };
  });
  if (contextGeometry.width < 440) throw new Error(`Mission Context is still too narrow: ${contextGeometry.width}px.`);
  if (contextGeometry.headersFit.some((fits) => !fits) || contextGeometry.rowsFit.some((fits) => !fits)) throw new Error(`Mission Context headings wrapped: ${JSON.stringify(contextGeometry)}.`);
  if (await contextPopover.getByText("5 environment", { exact: true }).count() !== 0) throw new Error("The retired 5 environment map is still visible.");
  if (await contextPopover.getByText("School Map", { exact: true }).count() !== 1) throw new Error("Mission Context must expose exactly one School Map entry.");
  if (await contextPopover.locator('input[name="autonomy-map"]:checked').count() !== 0) throw new Error("Opening Mission Context must not silently replace a custom map binding.");
  await contextPopover.locator('input[name="autonomy-map"][value="map-school"]').check();
  if (await contextPopover.locator('input[name="autonomy-map"]:checked').getAttribute("value") !== "map-school") throw new Error("School Map was not selected after an explicit user choice.");
  const reboundMapId = await page.evaluate(() => {
    const stored = window.localStorage.getItem("dronedream:autonomy-workspace:v2:local:universal");
    return stored ? JSON.parse(stored).mapPack?.id : null;
  });
  if (reboundMapId !== "map-school") throw new Error(`Mission Context did not persist the School Map binding: ${reboundMapId}.`);
  await page.screenshot({ path: path.join(outputRoot, `${screenshotPrefix}autonomy-mission-context-1600x1000.png`), fullPage: false });

  await page.goto(`${origin}/console/autonomy/maps`, { waitUntil: "networkidle" });
  await clearBlockingDialog(page);
  const savedMapLabels = await page.locator('select[aria-label="Saved maps"] option').allTextContents();
  if (savedMapLabels.some((label) => /\s·\sv\d+$/iu.test(label))) throw new Error(`Map revision suffix returned: ${savedMapLabels.join(" | ")}`);
  const mapName = page.getByLabel("Map name", { exact: true });
  await mapName.fill("School Map ");
  await mapName.fill("School Map");
  await page.getByRole("button", { name: "Save Map Pack", exact: true }).click();
  const persistedMap = await page.evaluate(() => {
    const stored = window.localStorage.getItem("dronedream:autonomy-workspace:v2:local:universal");
    return stored ? JSON.parse(stored).mapPack : null;
  });
  if (persistedMap?.id !== "map-school" || persistedMap?.name !== "School Map" || persistedMap?.version !== 1) {
    throw new Error(`Map save did not replace School Map in place: ${JSON.stringify(persistedMap)}`);
  }

  process.stdout.write(`${JSON.stringify({
    screenshots: [
      path.join(outputRoot, `${screenshotPrefix}school-map-solid-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-entrances-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-cafeteria-entrance-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-solid-west-angle-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-xray-level-1-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-xray-level-2-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-xray-level-3-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-xray-cafeteria-stair-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-solid-level-1-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-solid-level-2-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}school-map-solid-level-3-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}my-drone-vehicle-studio-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}tuning-chat-public-assets-1600x1000.png`),
      path.join(outputRoot, `${screenshotPrefix}autonomy-mission-context-1600x1000.png`),
    ],
  }, null, 2)}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server?.close();
}
