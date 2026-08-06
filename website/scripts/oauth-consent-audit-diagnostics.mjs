import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";

const MAX_EVENT_COUNT = 40;

const LOOPBACK_HOSTNAMES = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function localPreviewLatestFixture({ baseUrl, requestUrl, method }) {
  let base;
  let request;
  try {
    base = new URL(baseUrl);
    request = new URL(requestUrl);
  } catch {
    return null;
  }

  if (
    !["http:", "https:"].includes(base.protocol)
    || !LOOPBACK_HOSTNAMES.has(base.hostname)
    || base.username
    || base.password
    || method !== "GET"
    || request.origin !== base.origin
    || request.pathname !== "/downloads/latest.json"
    || request.search
    || request.hash
  ) {
    return null;
  }

  return {
    status: 200,
    contentType: "application/json",
    body: "{}",
  };
}

export function redactDiagnosticText(value, limit = 1_200) {
  const text = String(value ?? "")
    .replace(/authorization\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+/giu, "Authorization=[redacted]")
    .replace(/apikey\s*[:=]\s*[^\s,;]+/giu, "apikey=[redacted]")
    .replace(/(access|refresh|id)[_-]?token\s*[:=]\s*[^\s,;]+/giu, "$1_token=[redacted]")
    .replace(/Bearer\s+[^\s,;]+/giu, "Bearer [redacted]");
  return text.length <= limit ? text : `${text.slice(0, limit)}...[truncated]`;
}

export function safeRequestSummary(request) {
  let parsed;
  try {
    parsed = new URL(request.url());
  } catch {
    return {
      method: request.method(),
      url: redactDiagnosticText(request.url(), 300),
    };
  }
  return {
    method: request.method(),
    origin: parsed.origin,
    pathname: parsed.pathname,
  };
}

export function createPageEventJournal(page) {
  const journal = {
    console: [],
    pageErrors: [],
    requestFailures: [],
    dialogs: [],
  };
  const append = (target, value) => {
    if (target.length < MAX_EVENT_COUNT) target.push(value);
  };
  page.on("console", (message) => append(journal.console, {
    type: message.type(),
    text: redactDiagnosticText(message.text()),
  }));
  page.on("pageerror", (error) => append(
    journal.pageErrors,
    redactDiagnosticText(error?.message ?? error),
  ));
  page.on("requestfailed", (request) => append(journal.requestFailures, {
    ...safeRequestSummary(request),
    failure: redactDiagnosticText(request.failure()?.errorText ?? "unknown request failure", 300),
  }));
  page.on("dialog", async (dialog) => {
    append(journal.dialogs, {
      type: dialog.type(),
      message: redactDiagnosticText(dialog.message(), 300),
    });
    await dialog.dismiss();
  });
  return journal;
}

export function childProcessExited(child) {
  return !child || child.exitCode !== null || child.signalCode !== null;
}

export function buildAuditStorageState({ origin, locale, authStorageKey, session }) {
  const localStorage = [{ name: "drone-dream:locale", value: locale }];
  if (session) {
    localStorage.push({ name: authStorageKey, value: JSON.stringify(session) });
  }
  return {
    cookies: [],
    origins: [{ origin: new URL(origin).origin, localStorage }],
  };
}

export async function collectFailureDiagnostic({
  page,
  response,
  journal,
  screenshotDirectory,
  caseId,
  authStorageKey,
}) {
  await mkdir(screenshotDirectory, { recursive: true });
  const screenshotPath = path.join(screenshotDirectory, `${caseId}-failure.png`);
  let screenshot;
  try {
    await page.screenshot({ path: screenshotPath, fullPage: true, animations: "disabled" });
    const bytes = await readFile(screenshotPath);
    screenshot = {
      path: screenshotPath,
      bytes: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    };
  } catch (error) {
    screenshot = {
      path: screenshotPath,
      error: redactDiagnosticText(error instanceof Error ? error.message : error),
    };
  }

  let dom;
  try {
    dom = await page.evaluate((storageKey) => {
      const text = document.body?.innerText ?? "";
      const html = document.body?.innerHTML ?? "";
      const bootstrap = window.__droneDreamOAuthAuditBootstrap ?? null;
      return {
        readyState: document.readyState,
        title: document.title,
        lang: document.documentElement.lang,
        siteRootChildren: document.getElementById("site-root")?.childElementCount ?? null,
        sitePage: document.querySelector(".dd-site")?.getAttribute("data-page") ?? null,
        headings: [...document.querySelectorAll("h1,h2")]
          .map((node) => node.textContent?.replace(/\s+/gu, " ").trim())
          .filter(Boolean)
          .slice(0, 12),
        alerts: [...document.querySelectorAll("[role='alert']")]
          .map((node) => node.textContent?.replace(/\s+/gu, " ").trim())
          .filter(Boolean)
          .slice(0, 8),
        bodyText: text,
        bodyHtml: html,
        storage: {
          sessionPresent: window.localStorage.getItem(storageKey) !== null,
          locale: window.localStorage.getItem("drone-dream:locale"),
        },
        bootstrap,
      };
    }, authStorageKey);
  } catch (error) {
    dom = { error: redactDiagnosticText(error instanceof Error ? error.message : error) };
  }

  if (typeof dom.bodyText === "string") dom.bodyText = redactDiagnosticText(dom.bodyText, 1_000);
  if (typeof dom.bodyHtml === "string") dom.bodyHtml = redactDiagnosticText(dom.bodyHtml, 1_600);

  return {
    caseId,
    currentUrl: redactDiagnosticText(page.url(), 600),
    response: response ? {
      status: response.status(),
      url: redactDiagnosticText(response.url(), 600),
    } : null,
    dom,
    events: journal,
    screenshot,
  };
}
