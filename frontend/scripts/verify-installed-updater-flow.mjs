import assert from "node:assert/strict";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const args = new Map(process.argv.slice(2).map((argument) => {
  const [key, ...value] = argument.split("=");
  return [key, value.join("=") || true];
}));

function required(name) {
  const value = args.get(name);
  if (!value || value === true) throw new Error(`Missing required argument ${name}`);
  return String(value);
}

const cdpEndpoint = required("--cdp-endpoint");
const outputPath = path.resolve(required("--output"));
const screenshotRoot = path.resolve(required("--screenshot-root"));
assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP must remain loopback-only");

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function atomicJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
    await rename(temporary, filePath);
  } finally {
    await rm(temporary, { force: true });
  }
}

async function waitForCdp(expectedAvailable, timeoutMilliseconds) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const available = await (async () => {
      try {
        const response = await fetch(`${cdpEndpoint}/json/version`, {
          signal: AbortSignal.timeout(1_000),
        });
        return response.ok;
      } catch {
        return false;
      }
    })();
    if (available === expectedAvailable) return;
    await sleep(250);
  }
  throw new Error(`CDP did not become ${expectedAvailable ? "available" : "unavailable"}`);
}

async function connectInstalledPage() {
  await waitForCdp(true, 60_000);
  const browser = await chromium.connectOverCDP(cdpEndpoint);
  const contexts = browser.contexts();
  assert.equal(contexts.length, 1, "Expected one installed-app browser context");
  const pages = contexts[0].pages();
  assert(pages.length >= 1, "Installed app exposed no WebView page");
  const page = pages.find((candidate) => /(?:tauri|localhost)/u.test(candidate.url())) ?? pages[0];
  await page.waitForLoadState("domcontentloaded");
  return { browser, page };
}

async function readAccountSurface(page) {
  const account = page.locator(".app-account-button:visible").first();
  if (!(await account.isVisible())) return null;
  return account.evaluate((element) => {
    const image = element.querySelector("img");
    const strong = element.querySelector("strong");
    const small = element.querySelector("small");
    return {
      displayName: strong?.textContent?.trim() ?? null,
      plan: small?.textContent?.trim() ?? null,
      avatar: image ? {
        src: image.currentSrc || image.src,
        complete: image.complete,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
      } : null,
    };
  });
}

const evidence = {
  schemaVersion: 1,
  kind: "dronedream-installed-updater-flow",
  startedAt: new Date().toISOString(),
  initial: null,
  progress: [],
  restartObserved: false,
  final: null,
  status: "running",
};

try {
  await mkdir(screenshotRoot, { recursive: true });
  const initialConnection = await connectInstalledPage();
  const page = initialConnection.page;
  const updateButton = page.locator(".app-update-button:visible").first();
  await updateButton.waitFor({ state: "visible", timeout: 90_000 });
  await page.screenshot({
    path: path.join(screenshotRoot, "before-update.png"),
    fullPage: false,
  });
  evidence.initial = {
    url: page.url(),
    updateLabel: await updateButton.getAttribute("aria-label"),
    account: await readAccountSurface(page),
  };

  await page.evaluate(() => {
    globalThis.__dronedreamUpdaterProgress = [];
    const record = () => {
      const button = document.querySelector(".app-update-button");
      const progress = button?.querySelector(".app-update-progress")?.textContent?.trim() ?? null;
      const label = button?.getAttribute("aria-label") ?? null;
      const previous = globalThis.__dronedreamUpdaterProgress.at(-1);
      if (!previous || previous.progress !== progress || previous.label !== label) {
        globalThis.__dronedreamUpdaterProgress.push({
          observedAt: new Date().toISOString(),
          progress,
          label,
        });
      }
    };
    record();
    globalThis.__dronedreamUpdaterObserver = new MutationObserver(record);
    globalThis.__dronedreamUpdaterObserver.observe(document.body, {
      attributes: true,
      childList: true,
      subtree: true,
      characterData: true,
    });
  });

  await updateButton.click();
  const downloadDeadline = Date.now() + 10 * 60_000;
  let sawOneHundred = false;
  while (Date.now() < downloadDeadline) {
    try {
      const records = await page.evaluate(() => globalThis.__dronedreamUpdaterProgress ?? []);
      evidence.progress = records;
      sawOneHundred = records.some((record) => record.progress === "100%");
      if (sawOneHundred) break;
    } catch {
      break;
    }
    await sleep(250);
  }
  assert(sawOneHundred, "Updater never displayed 100%");

  await waitForCdp(false, 3 * 60_000);
  evidence.restartObserved = true;
  await waitForCdp(true, 3 * 60_000);

  const finalConnection = await connectInstalledPage();
  const finalPage = finalConnection.page;
  await finalPage.locator("body").waitFor({ state: "visible", timeout: 60_000 });
  await sleep(20_000);
  const finalUpdateButtons = finalPage.locator(".app-update-button:visible");
  const finalUpdateButtonCount = await finalUpdateButtons.count();
  await finalPage.screenshot({
    path: path.join(screenshotRoot, "after-update.png"),
    fullPage: false,
  });
  evidence.final = {
    url: finalPage.url(),
    updateButtonCount: finalUpdateButtonCount,
    updateLabel: finalUpdateButtonCount > 0
      ? await finalUpdateButtons.first().getAttribute("aria-label")
      : null,
    account: await readAccountSurface(finalPage),
  };
  assert.equal(finalUpdateButtonCount, 0, "Latest build still exposes the update button");
  evidence.status = "verified";
} catch (error) {
  evidence.status = "failed";
  evidence.error = error instanceof Error ? error.message : String(error);
  throw error;
} finally {
  evidence.finishedAt = new Date().toISOString();
  await atomicJson(outputPath, evidence);
}

console.log(JSON.stringify(evidence, null, 2));
