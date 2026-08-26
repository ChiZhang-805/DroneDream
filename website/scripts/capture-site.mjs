import { existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [
  url,
  selector = "#home",
  output = join(tmpdir(), "dronedream-site.png"),
  widthRaw = "1440",
  heightRaw = "1000",
  locale = "",
  actionBase64 = "",
] = process.argv.slice(2);

if (!url) {
  console.error("Usage: node capture-site.mjs <url> [selector] [output] [width] [height] [en|zh-CN] [action-base64]");
  process.exit(2);
}

const width = Number.parseInt(widthRaw, 10);
const height = Number.parseInt(heightRaw, 10);
if (!Number.isFinite(width) || !Number.isFinite(height) || width < 320 || height < 480) {
  throw new Error("Invalid viewport dimensions.");
}

const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const edge = edgeCandidates.find(existsSync);
if (!edge) throw new Error("Microsoft Edge was not found.");

const diagnostics = [];
const isOptionalPreviewManifest = (value) => value.includes("/downloads/latest.json");
const isBenignStaticAbort = (request) =>
  request.failure()?.errorText === "net::ERR_ABORTED" &&
  (
    request.url().endsWith("/drone-favicon.png") ||
    request.url().includes("/assets/128x128-")
  );
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

try {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on("pageerror", (error) => diagnostics.push(error.message));
  page.on("console", (message) => {
    const value = message.text();
    const browserResourceSummary = value.startsWith("Failed to load resource: the server responded with a status of ");
    if (message.type() === "error" && !browserResourceSummary && !isOptionalPreviewManifest(value)) diagnostics.push(value);
  });
  page.on("requestfailed", (request) => {
    if (isOptionalPreviewManifest(request.url()) || isBenignStaticAbort(request)) return;
    diagnostics.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText ?? "request failed"}`);
  });
  page.on("response", (response) => {
    if (response.status() < 400 || isOptionalPreviewManifest(response.url())) return;
    diagnostics.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  });

  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  if (locale === "en" || locale === "zh-CN") {
    await page.evaluate((nextLocale) => localStorage.setItem("drone-dream:locale", nextLocale), locale);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
    // Requests started by the disposable pre-locale navigation are expected to
    // be aborted by reload. Only diagnostics from the canonical locale render
    // belong in the visual receipt.
    diagnostics.length = 0;
  }
  if (actionBase64) {
    await page.waitForTimeout(300);
    const action = Buffer.from(actionBase64, "base64").toString("utf8");
    if (action.startsWith("playwright:")) {
      const steps = JSON.parse(action.slice("playwright:".length));
      for (const step of steps) {
        if (step.fill) await page.locator(step.fill).fill(step.value ?? "");
        if (step.click) await page.locator(step.click).click();
        if (step.hover) await page.locator(step.hover).hover();
        if (step.wait) await page.waitForTimeout(step.wait);
      }
    } else {
      await page.evaluate(async (code) => {
        const run = new Function(`return (async () => { ${code} })()`);
        await run();
      }, action);
    }
  }
  await page.waitForSelector(selector, {
    state: selector === "#root" ? "attached" : "visible",
    timeout: 60_000,
  });
  await page.evaluate(() => document.fonts.ready);
  if (selector !== "body" && selector !== "#root") {
    await page.locator(selector).scrollIntoViewIfNeeded();
  }
  await page.waitForTimeout(2_000);
  await page.screenshot({ path: output, fullPage: false });
  console.log(output);

  if (diagnostics.length > 0) {
    writeFileSync(`${output}.diagnostics.txt`, `${diagnostics.join("\n")}\n`, "utf8");
    throw new Error(`Page diagnostics:\n${diagnostics.join("\n")}`);
  }
} finally {
  await browser.close();
}
