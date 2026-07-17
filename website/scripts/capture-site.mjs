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
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

try {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on("pageerror", (error) => diagnostics.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !isOptionalPreviewManifest(message.text())) diagnostics.push(message.text());
  });
  page.on("requestfailed", (request) => {
    if (isOptionalPreviewManifest(request.url())) return;
    diagnostics.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText ?? "request failed"}`);
  });

  await page.goto(url, { waitUntil: "networkidle", timeout: 60_000 });
  await page.waitForSelector(selector, { state: "visible", timeout: 60_000 });
  if (locale === "en" || locale === "zh-CN") {
    await page.evaluate((nextLocale) => localStorage.setItem("drone-dream:locale", nextLocale), locale);
    await page.reload({ waitUntil: "networkidle", timeout: 60_000 });
    await page.waitForSelector(selector, { state: "visible", timeout: 60_000 });
  }
  await page.evaluate(() => document.fonts.ready);
  if (actionBase64) {
    const action = Buffer.from(actionBase64, "base64").toString("utf8");
    await page.evaluate(async (code) => {
      const run = new Function(`return (async () => { ${code} })()`);
      await run();
    }, action);
  }
  await page.locator(selector).scrollIntoViewIfNeeded();
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
