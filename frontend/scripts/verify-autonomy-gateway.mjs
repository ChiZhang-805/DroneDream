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
  "autonomy-gateway",
);
const origin = "http://127.0.0.1:5207";

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const connectorCatalog = {
  success: true,
  error: null,
  data: {
    schema_version: "dronedream.autonomy.asset-connector-catalog.v1",
    normalized_format: "ddpkg-v1",
    imported_code_execution: false,
    items: [
      ["dronedream.ddpkg", "DroneDream Package", ["ddpkg"], ["map", "world", "vehicle"], "builtin", true, "qualified"],
      ["gazebo.sdf", "Gazebo SDF", ["sdf", "world"], ["map", "world", "vehicle"], "builtin", true, "simulation_ready"],
      ["ros2.urdf", "ROS 2 URDF", ["urdf"], ["vehicle"], "builtin", true, "physics_ready"],
      ["ros2.xacro", "ROS 2 Xacro", ["xacro"], ["vehicle"], "companion_required", false, "physics_ready"],
      ["blender.phobos", "Blender + Phobos", ["blend", "smurf"], ["map", "world", "vehicle"], "companion_required", false, "simulation_ready"],
      ["solidworks.urdf", "SOLIDWORKS", ["sldasm", "step"], ["vehicle"], "plugin_required", false, "physics_ready"],
      ["autodesk.fusion", "Autodesk Fusion", ["f3d", "step"], ["map", "vehicle"], "plugin_required", false, "physics_ready"],
      ["onshape.translation", "Onshape", ["onshape-document", "step"], ["map", "vehicle"], "plugin_required", false, "physics_ready"],
      ["freecad.robotics", "FreeCAD", ["fcstd", "step"], ["map", "vehicle"], "companion_required", false, "physics_ready"],
      ["gis.gdal", "GIS / DEM", ["geotiff", "dem", "osm"], ["map", "world"], "companion_required", false, "visual_only"],
    ].map(([connector_id, name, source_formats, asset_kinds, availability, enabled, maximum_import_maturity]) => ({
      connector_id,
      name,
      source_application: name,
      source_formats,
      asset_kinds,
      availability,
      execution_boundary: availability === "builtin" ? "declarative_parser" : availability === "plugin_required" ? "isolated_plugin" : "isolated_local_companion",
      enabled,
      output_format: "ddpkg",
      maximum_import_maturity,
    })),
  },
};

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  root: frontendRoot,
  server: { host: "127.0.0.1", port: 5207, strictPort: true },
  logLevel: "error",
});
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];

try {
  for (const testCase of [
    { id: "desktop-en", locale: "en", viewport: { width: 1440, height: 900 } },
    { id: "desktop-zh", locale: "zh-CN", mode: "autonomy", viewport: { width: 1440, height: 900 } },
    { id: "mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
  ]) {
    const context = await browser.newContext({ viewport: testCase.viewport });
    await context.route("**/api/v1/**", (route) => route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Visual validation fixture" }),
    }));
    // Playwright evaluates routes in reverse registration order, so the exact
    // connector fixture must be registered after the generic offline fallback.
    await context.route("**/api/v1/autonomy/asset-connectors", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(connectorCatalog),
    }));
    const page = await context.newPage();
    await page.goto(`${origin}/`, { waitUntil: "domcontentloaded" });
    await page.evaluate((locale) => window.localStorage.setItem("drone-dream:locale", locale), testCase.locale);
    await page.goto(`${origin}/autonomy?docsPreview=1`, { waitUntil: "networkidle" });
    await page.locator(".autonomy-connector-row").first().waitFor();

    if (testCase.mode) {
      await page.getByRole("combobox", { name: testCase.locale === "zh-CN" ? "工作区" : "Workspace mode" })
        .selectOption(testCase.mode);
      await page.waitForFunction((mode) => (
        document.documentElement.dataset.brandEdition === mode
        && document.documentElement.dataset.themeGrantsHardwareAuthority === "false"
      ), testCase.mode);
    }

    const metrics = await page.locator(".autonomy-gateway-page").evaluate((element) => ({
      rows: element.querySelectorAll(".autonomy-connector-row").length,
      maturityLevels: element.querySelectorAll(".autonomy-maturity-strip li").length,
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      brandEdition: document.documentElement.dataset.brandEdition,
      grantsHardwareAuthority: document.documentElement.dataset.themeGrantsHardwareAuthority,
    }));
    assert.equal(metrics.rows, 10, `${testCase.id}: connector rows`);
    assert.equal(metrics.maturityLevels, 5, `${testCase.id}: maturity levels`);
    assert(metrics.scrollWidth <= metrics.viewportWidth, `${testCase.id}: horizontal overflow`);
    if (testCase.mode) {
      assert.equal(metrics.brandEdition, testCase.mode, `${testCase.id}: active brand edition`);
      assert.equal(metrics.grantsHardwareAuthority, "false", `${testCase.id}: hardware authority boundary`);
    }
    if (testCase.locale === "zh-CN") {
      await page.getByRole("heading", { name: "自主任务" }).waitFor();
      await page.getByText("导入代码默认不执行").waitFor();
    } else {
      await page.getByRole("heading", { name: "Autonomous tasks" }).waitFor();
    }

    const screenshot = path.join(outputRoot, `${testCase.id}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    results.push({ ...testCase, screenshot, metrics });
    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}

await writeFile(
  path.join(outputRoot, "receipt.json"),
  `${JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify(results, null, 2));
