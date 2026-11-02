import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.join(frontendRoot, "node_modules", ".cache", "fixed-scenarios-layout");
const host = "127.0.0.1";
const port = 5201;
const externalOrigin = process.env.FIXED_SCENARIOS_VERIFY_ORIGIN?.replace(/\/$/, "");
const origin = externalOrigin ?? `http://${host}:${port}`;
const screenshotName = `${externalOrigin ? "online-" : ""}fixed-scenarios-button-below-preview-1600x1000.png`;

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
  await page.goto(`${origin}/console/scenarios`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
  });

  const cards = page.locator(".fixed-scenario-card");
  if (await cards.count() !== 2) throw new Error("Fixed Scenarios must show two cards per page.");
  for (let index = 0; index < 2; index += 1) {
    const card = cards.nth(index);
    const preview = await card.locator(".experience-preview").boundingBox();
    const button = await card.locator(".fixed-scenario-use").boundingBox();
    if (!preview || !button || button.y <= preview.y + preview.height) {
      throw new Error(`Scenario card ${index + 1} does not place its action below the preview.`);
    }
    if (button.y + button.height > 995) {
      throw new Error(`Scenario card ${index + 1} action is clipped below the desktop viewport.`);
    }
  }

  const screenshotPath = path.join(outputRoot, screenshotName);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  process.stdout.write(`${screenshotPath}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server?.close();
}
