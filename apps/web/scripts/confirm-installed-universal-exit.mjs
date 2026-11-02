import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const args = new Map(
  process.argv.slice(2).map((entry) => {
    const separator = entry.indexOf("=");
    assert(separator > 2, `Invalid argument: ${entry}`);
    return [entry.slice(0, separator), entry.slice(separator + 1)];
  }),
);

const cdpEndpoint = String(args.get("--cdp-endpoint") ?? "");
const outputPath = path.resolve(String(args.get("--output") ?? ""));
assert(/^http:\/\/127\.0\.0\.1:\d+$/u.test(cdpEndpoint), "CDP must remain loopback-only");
assert(outputPath.endsWith(".json"), "An owned JSON receipt path is required");

async function atomicJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}`;
  await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await fs.rename(temporary, filePath);
}

const receipt = {
  schemaVersion: 1,
  kind: "dronedream-installed-universal-exit-confirmation-receipt",
  confirmationClicks: 0,
  passed: false,
};

const browser = await chromium.connectOverCDP(cdpEndpoint);
try {
  const contexts = browser.contexts();
  assert.equal(contexts.length, 1, "Expected exactly one app-owned WebView2 context");
  const pages = contexts[0].pages();
  assert.equal(pages.length, 1, "Expected exactly one app-owned WebView2 page");
  const page = pages[0];
  const dialog = page.locator(".app-exit-dialog");
  await dialog.waitFor({ state: "visible", timeout: 30_000 });
  const confirm = dialog.locator(".app-exit-confirm");
  await confirm.waitFor({ state: "visible" });
  await confirm.focus();
  receipt.confirmationClicks += 1;
  await confirm.press("Enter");
  receipt.passed = true;
} finally {
  await atomicJson(outputPath, receipt);
  // This verifier observes an app-owned WebView2 instance. It never owns or
  // closes the browser process. Exit only this helper so the read-only CDP
  // socket cannot keep the bounded verifier alive.
  process.exit(receipt.passed ? 0 : 1);
}
