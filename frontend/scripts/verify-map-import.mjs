import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const output = path.resolve(root, "../artifacts/test-runs/map-upload");
await mkdir(output, { recursive: true });
process.env.VITE_PUBLIC_DEMO_CONSOLE = "true";
process.env.VITE_API_BASE_URL = "http://127.0.0.1:5203";
process.env.VITE_SUPABASE_URL = "https://local-build.invalid";
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "local-build-placeholder";
const server = await createServer({ root, configFile: path.join(root, "vite.console.config.ts"), logLevel: "warn", server: { host: "127.0.0.1", port: 5203, strictPort: true } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => localStorage.setItem("drone-dream:locale", "zh-CN"));
  await page.goto("http://127.0.0.1:5203/console/autonomy/maps", { waitUntil: "networkidle" });
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((e) => e.removeAttribute("inert"));
    window.mapUploadCalls = [];
    window.__TAURI_INTERNALS__ = { invoke: async (command) => {
      window.mapUploadCalls.push(command);
      if (command === "plugin:dialog|open") return "fixture/campus.world";
      throw new Error(command);
    } };
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      window.mapUploadCalls.push(command);
      if (command === "stage_map_import_file") return { role: args.role, filePath: "cache/campus.world", name: "campus.world", fileCount: 1 };
      throw new Error(command);
    } } };
  });
  await page.locator('.autonomy-new-map-card > button').click();
  const dialog = page.locator("dialog.map-import-dialog");
  await dialog.waitFor({ state: "visible" });
  if ((await page.evaluate(() => window.mapUploadCalls)).length) throw new Error("Opening Import must not open a picker");
  if (await dialog.locator("p").count()) throw new Error("Import must not contain explanation paragraphs");
  if (await dialog.locator(".map-import-slot").count() !== 4) throw new Error("Expected four upload slots");
  await page.screenshot({ path: path.join(output, "map-import-waiting.png") });
  await dialog.locator('.map-import-slot').first().locator('button').click();
  await dialog.locator('[data-state="uploaded"]').waitFor();
  for (const width of [1440, 1100, 1920]) {
    await page.setViewportSize({ width, height: width === 1100 ? 700 : 900 });
    const bounds = await dialog.boundingBox();
    if (!bounds || bounds.x < 0 || bounds.x + bounds.width > width + 1) throw new Error(`Dialog overflow at ${width}`);
    await page.screenshot({ path: path.join(output, `map-import-uploaded-${width}.png`) });
  }
  await writeFile(path.join(output, "result.json"), JSON.stringify({ ui: "passed", widths: [1440, 1100, 1920], mockedNativeTransport: true }, null, 2));
  console.log(output);
} finally {
  await browser?.close();
  await server.close();
}
