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

  const illustration = page.locator(".launcher-flight-illustration");
  if (await illustration.count() !== 1 ||
      await illustration.locator("svg.launcher-flight-map").count() !== 1) {
    throw new Error("The installed Field launcher did not render its lightweight flight illustration.");
  }
  if (await launcher.locator("canvas").count() !== 0) {
    throw new Error("The installed Field launcher still creates a WebGL canvas.");
  }
  const illustrationBounds = await illustration.boundingBox();
  if (!illustrationBounds || illustrationBounds.width <= 0 || illustrationBounds.height <= 0) {
    throw new Error("The installed Field launch illustration has no visible area.");
  }

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
    illustrationBounds,
    launcherRenderer: "lightweight-svg",
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
