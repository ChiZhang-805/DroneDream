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
const mode = required("--mode");

assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP must remain loopback-only");
assert(Number.isInteger(runtimeReadyTimeoutMs) && runtimeReadyTimeoutMs <= 300_000);
assert(Number.isInteger(oauthTimeoutMs) && oauthTimeoutMs <= 600_000);
assert(["oauth", "runtime-diagnosis"].includes(mode), "Unknown installed-app observer mode");
const runtimeDiagnosisOnly = mode === "runtime-diagnosis";

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
  schemaVersion: 2,
  kind: "dronedream-installed-universal-oauth-observation",
  passed: false,
  counts,
  stage: "initialized",
  runtimeReadyObserved: false,
  runtimeActionSettled: false,
  runtimeFailureCode: null,
  diagnosisComplete: false,
  callbackSessionObserved: false,
  accountSurfaceObserved: false,
  localLogoutObserved: false,
};

async function persist(stage) {
  evidence.stage = stage;
  evidence.updatedAt = new Date().toISOString();
  await atomicJson(outputPath, evidence);
}

function safeFailure(error) {
  if (error?.name === "TimeoutError") {
    return { name: "TimeoutError", message: "A bounded observer wait timed out." };
  }
  if (error instanceof assert.AssertionError) {
    return { name: "AssertionError", message: "A bounded observer assertion failed." };
  }
  return { name: "Error", message: "The bounded installed-app observer failed." };
}

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
  await persist("connected");
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
    await persist("runtime-start-attempted");
    await primary.focus();
    await primary.press("Enter");
    let runtimeOutcome = "runtime_start_pending_timeout";
    try {
      const runtimeOutcomeHandle = await page.waitForFunction(
        () => {
        const button = document.querySelector(".launcher-primary-action");
        const text = button?.textContent?.replace(/\s+/gu, " ").trim().toLowerCase();
        if (
          text === "sign in and enter tuning workspace" ||
          text === "登录并进入调优平台"
        ) return "ready";
        const runtimeError = [...document.querySelectorAll(".alert-body code")]
          .map((node) => node.textContent ?? "")
          .find((value) => value.trim().toLowerCase().startsWith("start_runtime:"));
        if (!runtimeError) return false;
        const normalized = runtimeError.toLowerCase();
        for (const code of [
          "runtime_service_unhealthy",
          "runtime_host_connectivity",
          "runtime_health_unknown",
        ]) {
          if (normalized.includes(code)) return code;
        }
        if (normalized.includes("another runtime installation or maintenance operation")) {
          return "runtime_operation_busy";
        }
        if (normalized.includes("update quiesce is active")) return "runtime_update_quiesce_active";
        if (normalized.includes("runtime is not installed")) return "runtime_not_installed";
        if (normalized.includes("windows cannot reach it")) return "runtime_host_connectivity";
        if (normalized.includes("runtime-internal backend")) return "runtime_service_unhealthy";
        if (normalized.includes("did not become healthy")) return "runtime_health_unknown";
        return "runtime_error_unclassified";
        },
        undefined,
        { timeout: runtimeReadyTimeoutMs },
      );
      runtimeOutcome = await runtimeOutcomeHandle.jsonValue();
      evidence.runtimeActionSettled = true;
    } catch (error) {
      if (error?.name !== "TimeoutError") throw error;
    }
    if (runtimeOutcome !== "ready") {
      evidence.runtimeFailureCode = runtimeOutcome;
      await persist("runtime-start-failed");
      if (!runtimeDiagnosisOnly) {
        throw new Error("Runtime start failed before browser authentication became available.");
      }
    } else {
      evidence.runtimeReadyObserved = true;
      await persist("runtime-ready");
      primaryText = normalizedButtonText(await primary.innerText());
    }
  } else if (isSignIn(primaryText)) {
    evidence.runtimeReadyObserved = true;
    evidence.runtimeActionSettled = true;
    await persist("runtime-already-ready");
  } else {
    throw new Error("Launcher did not expose the bounded Runtime-start or Universal sign-in action");
  }

  if (runtimeDiagnosisOnly) {
    evidence.diagnosisComplete = true;
    evidence.passed = true;
    await persist("runtime-diagnosis-completed");
  } else {
    assert(isSignIn(primaryText), "Runtime became ready without exposing the Universal sign-in action");
    counts.loginButton += 1;
    counts.oauthTransaction += 1;
    await persist("oauth-attempted");
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
    await persist("local-logout-attempted");
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
    await persist("completed");
  }
} catch (error) {
  if (counts.runtimeStart === 1 && !evidence.runtimeActionSettled) {
    evidence.runtimeFailureCode = "runtime_start_pending_timeout";
  }
  evidence.failure = safeFailure(error);
  throw error;
} finally {
  evidence.terminalState = evidence.passed ? "passed" : "failed";
  evidence.completedAt = new Date().toISOString();
  await atomicJson(outputPath, evidence);
  // This helper only observes an app-owned WebView2 instance. Never call
  // browser.close(), which would terminate a browser process it does not own.
  // Exit only this observer process so its CDP socket cannot keep the bounded
  // verifier alive after the app interaction has finished.
  process.exit(evidence.passed ? 0 : 1);
}
