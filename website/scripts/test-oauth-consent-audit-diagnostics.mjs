import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  buildAuditStorageState,
  childProcessExited,
  collectFailureDiagnostic,
  createPageEventJournal,
  localPreviewLatestFixture,
  redactDiagnosticText,
  safeRequestSummary,
} from "./oauth-consent-audit-diagnostics.mjs";

const localLatestRequest = {
  baseUrl: "http://127.0.0.1:4174/",
  requestUrl: "http://127.0.0.1:4174/downloads/latest.json",
  method: "GET",
};
assert.deepEqual(localPreviewLatestFixture(localLatestRequest), {
  status: 200,
  contentType: "application/json",
  body: "{}",
});
for (const request of [
  { ...localLatestRequest, method: "POST" },
  { ...localLatestRequest, requestUrl: "https://127.0.0.1:4174/downloads/latest.json" },
  { ...localLatestRequest, requestUrl: "http://localhost:4174/downloads/latest.json" },
  { ...localLatestRequest, requestUrl: "http://127.0.0.1:4175/downloads/latest.json" },
  { ...localLatestRequest, requestUrl: "https://external.invalid/downloads/latest.json" },
  { ...localLatestRequest, requestUrl: "http://127.0.0.1:4174/downloads/latest-universal.json" },
  { ...localLatestRequest, requestUrl: "http://127.0.0.1:4174/downloads/latest.json?edition=sim" },
  { ...localLatestRequest, baseUrl: "https://local-preview.invalid/" },
  { ...localLatestRequest, baseUrl: "not-a-url" },
]) {
  assert.equal(localPreviewLatestFixture(request), null);
}

assert.equal(
  redactDiagnosticText("Authorization: Bearer secret-value"),
  "Authorization=[redacted]",
);
assert.equal(
  redactDiagnosticText("access_token=secret refresh-token:other"),
  "access_token=[redacted] refresh_token=[redacted]",
);
assert.match(redactDiagnosticText("x".repeat(1_500)), /\[truncated\]$/u);
assert.deepEqual(safeRequestSummary({
  method: () => "GET",
  url: () => "https://local-preview.invalid/auth/v1/user?access_token=secret",
}), {
  method: "GET",
  origin: "https://local-preview.invalid",
  pathname: "/auth/v1/user",
});
assert.equal(childProcessExited({ exitCode: null, signalCode: "SIGTERM" }), true);
assert.equal(childProcessExited({ exitCode: null, signalCode: null }), false);
const storageState = buildAuditStorageState({
  origin: "http://127.0.0.1:4174/path",
  locale: "zh-CN",
  authStorageKey: "sb-local-preview-auth-token",
  session: { access_token: "synthetic", expires_at: 4_000_000_000 },
});
assert.equal(storageState.origins[0].origin, "http://127.0.0.1:4174");
assert.equal(storageState.origins[0].localStorage[0].value, "zh-CN");
assert.equal(storageState.origins[0].localStorage[1].name, "sb-local-preview-auth-token");

class FakePage extends EventEmitter {
  url() {
    return "http://127.0.0.1:4174/account/?returnTo=%2Foauth%2Fconsent%2F";
  }

  async screenshot({ path: target }) {
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, Buffer.from("synthetic-failure-image"));
  }

  async evaluate() {
    return {
      readyState: "complete",
      title: "Sign in",
      lang: "en",
      siteRootChildren: 1,
      sitePage: "account",
      headings: ["Sign in"],
      alerts: [],
      bodyText: "Sign in access_token=must-not-survive",
      bodyHtml: "<main>Sign in refresh_token=must-not-survive</main>",
      storage: { sessionPresent: false, locale: "en" },
      bootstrap: { sessionPresent: true, locale: "en" },
    };
  }
}

const page = new FakePage();
const journal = createPageEventJournal(page);
page.emit("console", { type: () => "error", text: () => "Bearer secret-console" });
page.emit("pageerror", new Error("access_token=secret-error"));
page.emit("requestfailed", {
  method: () => "GET",
  url: () => "https://local-preview.invalid/auth/v1/user?apikey=secret",
  failure: () => ({ errorText: "Bearer secret-request" }),
});
const output = path.join(os.tmpdir(), "dronedream-oauth-diagnostic-offline-test");
const diagnostic = await collectFailureDiagnostic({
  page,
  response: {
    status: () => 200,
    url: () => "http://127.0.0.1:4174/oauth/consent/?authorization_id=synthetic",
  },
  journal,
  screenshotDirectory: output,
  caseId: "edge-en-desktop-1440",
  authStorageKey: "sb-local-preview-auth-token",
});

assert.equal(diagnostic.currentUrl.includes("/account/"), true);
assert.equal(diagnostic.response.status, 200);
assert.equal(diagnostic.dom.sitePage, "account");
assert.equal(diagnostic.dom.storage.sessionPresent, false);
assert.equal(diagnostic.dom.bootstrap.sessionPresent, true);
assert.match(diagnostic.dom.bodyText, /access_token=\[redacted\]/u);
assert.match(diagnostic.dom.bodyHtml, /refresh_token=\[redacted\]/u);
assert.equal(diagnostic.events.console.length, 1);
assert.equal(diagnostic.events.pageErrors.length, 1);
assert.equal(diagnostic.events.requestFailures.length, 1);
assert.equal(diagnostic.screenshot.bytes, 23);
assert.match(diagnostic.screenshot.sha256, /^[a-f0-9]{64}$/u);

console.log("oauth consent audit diagnostics: offline checks passed");
