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
const runtimeReadyTimeoutMs = Number(required("--runtime-ready-timeout-ms"));
const oauthTimeoutMs = Number(required("--oauth-timeout-ms"));

assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP must remain loopback-only");
assert(Number.isInteger(runtimeReadyTimeoutMs) && runtimeReadyTimeoutMs <= 300_000);
assert(Number.isInteger(oauthTimeoutMs) && oauthTimeoutMs <= 600_000);

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

const counts = {
  runtimeStart: 0,
  loginButton: 0,
  oauthTransaction: 0,
  localLogout: 0,
};
const evidence = {
  schemaVersion: 1,
  kind: "dronedream-installed-universal-oauth-observation",
  passed: false,
  counts,
  runtimeReadyObserved: false,
  callbackSessionObserved: false,
  accountSurfaceObserved: false,
  localLogoutObserved: false,
};

function normalizedButtonText(value) {
  return value.replace(/\s+/gu, " ").trim().toLowerCase();
}

function isRuntimeStart(text) {
  return text === "start runtime" || text === "启动运行环境";
}

function isSignIn(text) {
  return text === "sign in and enter tuning workspace" || text === "登录并进入调优平台";
}

const browser = await chromium.connectOverCDP(cdpEndpoint);
try {
  const contexts = browser.contexts();
  assert.equal(contexts.length, 1, "Expected exactly one installed-app browser context");
  const pages = contexts[0].pages();
  assert(pages.length >= 1, "Installed app exposed no WebView page");
  const page = pages.find((candidate) => /(?:tauri|localhost)/u.test(candidate.url())) ?? pages[0];
  await page.waitForLoadState("domcontentloaded");
  await page.locator(".drone-launch-scene").waitFor({ state: "visible", timeout: 30_000 });

  await page.evaluate(() => window.localStorage.setItem("drone-dream:locale", "en"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".drone-launch-scene").waitFor({ state: "visible", timeout: 30_000 });

  const primary = page.locator(".launcher-primary-action:visible").first();
  await primary.waitFor({ state: "visible", timeout: 60_000 });
  let primaryText = normalizedButtonText(await primary.innerText());
  if (isRuntimeStart(primaryText)) {
    counts.runtimeStart += 1;
    assert.equal(counts.runtimeStart, 1, "Runtime start cap exceeded");
    await primary.focus();
    await primary.press("Enter");
    await page.waitForFunction(
      () => {
        const button = document.querySelector(".launcher-primary-action");
        const text = button?.textContent?.replace(/\s+/gu, " ").trim().toLowerCase();
        return text === "sign in and enter tuning workspace" || text === "登录并进入调优平台";
      },
      undefined,
      { timeout: runtimeReadyTimeoutMs },
    );
    evidence.runtimeReadyObserved = true;
    primaryText = normalizedButtonText(await primary.innerText());
  } else if (isSignIn(primaryText)) {
    evidence.runtimeReadyObserved = true;
  } else {
    throw new Error("Launcher did not expose the bounded Runtime-start or Universal sign-in action");
  }

  assert(isSignIn(primaryText), "Runtime became ready without exposing the Universal sign-in action");
  counts.loginButton += 1;
  counts.oauthTransaction += 1;
  await primary.focus();
  await primary.press("Enter");

  await page.waitForFunction(
    () => window.location.pathname === "/assistant" && Boolean(document.querySelector(".app-account-button")),
    undefined,
    { timeout: oauthTimeoutMs },
  );
  evidence.callbackSessionObserved = true;
  evidence.accountSurfaceObserved = true;
  evidence.postCallbackPath = await page.evaluate(() => window.location.pathname);

  const accountButton = page.locator(".app-account-button:visible").first();
  await accountButton.focus();
  await accountButton.press("Enter");
  const accountDialog = page.locator(".account-dialog");
  await accountDialog.waitFor({ state: "visible" });
  const signOut = accountDialog.locator(".account-sign-out");
  await signOut.waitFor({ state: "visible" });
  counts.localLogout += 1;
  await signOut.focus();
  await signOut.press("Enter");
  await signOut.waitFor({ state: "hidden", timeout: 30_000 });
  evidence.localLogoutObserved = true;

  assert.deepEqual(counts, {
    runtimeStart: counts.runtimeStart,
    loginButton: 1,
    oauthTransaction: 1,
    localLogout: 1,
  });
  evidence.passed = true;
} catch (error) {
  evidence.failure = {
    name: error instanceof Error ? error.name : "Error",
    message: error instanceof Error ? error.message : String(error),
  };
  throw error;
} finally {
  await atomicJson(outputPath, evidence);
  // This helper only observes an app-owned WebView2 instance. Never call
  // browser.close(), which would terminate a browser process it does not own.
  // Exit only this observer process so its CDP socket cannot keep the bounded
  // verifier alive after the app interaction has finished.
  process.exit(evidence.passed ? 0 : 1);
}
