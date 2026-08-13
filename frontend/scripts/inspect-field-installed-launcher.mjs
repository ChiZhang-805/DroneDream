import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { chromium } from "playwright";

const [endpoint, phase, outputPath] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(endpoint ?? "")) {
  throw new Error("Expected an explicit loopback WebView2 debug endpoint.");
}
if (!/^(fresh|overlay)$/.test(phase ?? "")) {
  throw new Error("Expected the fresh or overlay lifecycle phase.");
}
if (!path.isAbsolute(outputPath ?? "")) {
  throw new Error("The inspection output path must be absolute.");
}

const expectedTheme = {
  "--dd-brand-start": "#ffc247",
  "--dd-brand-middle": "#ff754b",
  "--dd-brand-end": "#d746a5",
};
const forbiddenNetwork = [];
let browser;

try {
  browser = await chromium.connectOverCDP(endpoint);
  const page = browser.contexts().flatMap((context) => context.pages())
    .find((candidate) => !candidate.url().startsWith("devtools://"));
  if (!page) throw new Error("No inspectable Field WebView2 page was found.");

  page.on("request", (request) => {
    const url = request.url();
    if (/^https?:/i.test(url) && !/^https?:\/\/(?:127\.0\.0\.1|tauri\.localhost)(?::\d+)?\//i.test(url)) {
      forbiddenNetwork.push(url);
    }
  });

  await page.setViewportSize({ width: 390, height: 620 });
  const launcher = page.locator('.field-launcher[data-authority="false"]');
  await launcher.waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForFunction(() =>
    document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") === "100"
  );

  const initialLocale = await page.locator("html").getAttribute("lang");
  if (initialLocale !== "en" && initialLocale !== "zh-CN") {
    throw new Error(`Unexpected Field locale: ${initialLocale}`);
  }
  const initialEntryName = initialLocale === "en"
    ? "Sign in and enter the tuning platform"
    : "登录并进入调优平台";
  await page.getByRole("button", { name: initialEntryName }).waitFor();

  const scene = page.locator('.drone-launch-scene[data-theme-edition="field"]');
  const canvas = scene.locator("canvas");
  if (await scene.count() !== 1 || await canvas.count() !== 1) {
    throw new Error("The installed Field launcher did not render one shared 3D scene.");
  }
  const canvasBounds = await canvas.boundingBox();
  if (!canvasBounds || canvasBounds.width <= 0 || canvasBounds.height <= 0) {
    throw new Error("The installed Field 3D canvas has no visible area.");
  }
  const pixels = await canvas.screenshot();
  const pixelStats = await page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const sample = document.createElement("canvas");
    sample.width = 64;
    sample.height = 64;
    const context = sample.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas pixel sampler is unavailable.");
    context.drawImage(image, 0, 0, 64, 64);
    const values = context.getImageData(0, 0, 64, 64).data;
    let visiblePixels = 0;
    const buckets = new Set();
    for (let index = 0; index < values.length; index += 4) {
      const [red, green, blue, alpha] = values.slice(index, index + 4);
      if (alpha > 0 && red + green + blue > 24) visiblePixels += 1;
      buckets.add(`${red >> 4}:${green >> 4}:${blue >> 4}:${alpha >> 4}`);
    }
    return { visiblePixels, colorBuckets: buckets.size };
  }, pixels.toString("base64"));
  if (pixelStats.visiblePixels <= 512 || pixelStats.colorBuckets <= 24) {
    throw new Error("The installed Field 3D canvas is blank or lacks visual detail.");
  }

  if (await scene.getAttribute("data-flight-state") !== "hover") {
    throw new Error("The installed Field drone did not reach hover state.");
  }
  await page.mouse.click(
    canvasBounds.x + canvasBounds.width * 0.5,
    canvasBounds.y + canvasBounds.height * 0.42,
  );
  await page.waitForFunction(() =>
    document.querySelector(".drone-launch-scene")?.getAttribute("data-flight-state") === "starflight"
  );

  const theme = await page.locator("html").evaluate((element, tokens) => {
    const style = getComputedStyle(element);
    return {
      edition: element.dataset.brandEdition,
      presentationOnly: element.dataset.themePresentationOnly,
      grantsHardwareAuthority: element.dataset.themeGrantsHardwareAuthority,
      colors: Object.fromEntries(Object.keys(tokens).map((name) => [
        name,
        style.getPropertyValue(name).trim().toLowerCase(),
      ])),
    };
  }, expectedTheme);
  if (theme.edition !== "field" || theme.presentationOnly !== "true" ||
      theme.grantsHardwareAuthority !== "false") {
    throw new Error("Field presentation or authority theme binding drifted.");
  }
  for (const [name, value] of Object.entries(expectedTheme)) {
    if (theme.colors[name] !== value) throw new Error(`Field theme token drifted: ${name}`);
  }

  const visibleText = await page.locator("body").innerText();
  if (/PX4|Gazebo|SITL|HITL/i.test(visibleText)) {
    throw new Error("Simulator terminology is visible on the installed Field launcher.");
  }
  await page.locator(".field-launcher-language").click();
  const finalLocale = initialLocale === "en" ? "zh-CN" : "en";
  await page.waitForFunction((locale) => document.documentElement.lang === locale, finalLocale);
  const finalEntryName = finalLocale === "en"
    ? "Sign in and enter the tuning platform"
    : "登录并进入调优平台";
  await page.getByRole("button", { name: finalEntryName }).waitFor();

  if (forbiddenNetwork.length !== 0) {
    throw new Error("The launcher made an external or authentication request before user sign-in.");
  }
  const authStorageKeys = await page.evaluate(() =>
    Object.keys(localStorage).filter((key) => /auth|oauth|token|session/i.test(key))
  );
  if (authStorageKeys.length !== 0) {
    throw new Error("The launcher exposed an authentication/session local-storage key.");
  }

  const screenshotPath = path.join(path.dirname(outputPath), `${phase}-field-launcher-390x620.png`);
  await mkdir(path.dirname(outputPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const screenshotSha256 = createHash("sha256")
    .update(await readFile(screenshotPath))
    .digest("hex");
  const result = {
    schemaVersion: 1,
    kind: "dronedream-field-installed-launcher-inspection",
    phase,
    initialLocale,
    finalLocale,
    progress: 100,
    theme,
    pixelStats,
    droneInteraction: "hover-to-starflight",
    externalRequestCount: 0,
    authenticationRequestCount: 0,
    authStorageKeyCount: 0,
    presentationGrantsHardwareAuthority: false,
    screenshot: { path: screenshotPath, sha256: screenshotSha256 },
    passed: true,
  };
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result));
} finally {
  if (browser) await browser.close();
}
