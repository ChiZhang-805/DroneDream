import { createServer } from "node:http";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "..", "..");
const template = readFileSync(
  resolve(repositoryRoot, "desktop", "src-tauri", "browser-auth.html"),
  "utf8",
);
const outputIndex = process.argv.indexOf("--output");
const outputDirectory = outputIndex >= 0
  ? resolve(process.argv[outputIndex + 1] ?? "")
  : null;
if (outputIndex >= 0 && !process.argv[outputIndex + 1]) {
  throw new Error("--output requires a directory");
}
if (outputDirectory) mkdirSync(outputDirectory, { recursive: true });

const nonce = "browser-auth-result-visual-nonce";
const homeUrl = "http://getdronedream.com/";
const editions = {
  universal: {
    displayName: "DroneDream",
    lockupPath: "brand/commercial/universal-lockup.png",
  },
  sim: {
    displayName: "DroneDream · SIM",
    lockupPath: "brand/commercial/sim-lockup.png",
  },
  lab: {
    displayName: "DroneDream · LAB",
    lockupPath: "brand/commercial/lab-lockup.png",
  },
  field: {
    displayName: "DroneDream · FIELD",
    lockupPath: "brand/commercial/field-lockup.png",
  },
};

function renderPage({ edition, locale, success }) {
  const identity = editions[edition];
  if (!identity) throw new Error(`Unknown browser-auth edition: ${edition}`);
  const brandLockupDataUrl = `data:image/png;base64,${readFileSync(
    resolve(repositoryRoot, identity.lockupPath),
  ).toString("base64")}`;
  const replacements = new Map([
    ["__DOCUMENT_LANGUAGE__", locale],
    ["__CSP_NONCE__", nonce],
    ["__BRAND_LOCKUP_DATA_URL__", brandLockupDataUrl],
    ["__DISPLAY_NAME_JSON__", JSON.stringify(identity.displayName)],
    ["__LOCALE_JSON__", JSON.stringify(locale)],
    ["__SUCCESS_JSON__", JSON.stringify(success)],
    ["__HOME_URL_JSON__", JSON.stringify(homeUrl)],
  ]);
  let page = template;
  for (const [placeholder, replacement] of replacements) {
    page = page.replaceAll(placeholder, replacement);
  }
  if (/__[A-Z][A-Z0-9_]+__/u.test(page)) {
    throw new Error("Browser-auth result page still contains a placeholder");
  }
  return page;
}

function contentSecurityPolicy() {
  return [
    "default-src 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
    "connect-src 'none'",
    `script-src 'nonce-${nonce}'`,
    `style-src 'nonce-${nonce}'`,
    "img-src data:",
    "font-src 'none'",
  ].join("; ");
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (request.method === "GET" && url.pathname === "/callback-result") {
    const body = Buffer.from(renderPage({
      edition: url.searchParams.get("edition") ?? "universal",
      locale: url.searchParams.get("locale") === "zh-CN" ? "zh-CN" : "en",
      success: url.searchParams.get("success") === "true",
    }), "utf8");
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-security-policy": contentSecurityPolicy(),
      "content-type": "text/html; charset=utf-8",
      "content-length": body.length,
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      "x-frame-options": "DENY",
    });
    response.end(body);
    return;
  }
  response.writeHead(404, { "content-type": "text/plain" });
  response.end("not found");
});

await new Promise((resolveListen, rejectListen) => {
  server.once("error", rejectListen);
  server.listen(0, "127.0.0.1", resolveListen);
});
const address = server.address();
if (!address || typeof address === "string") {
  throw new Error("Visual test server did not expose a loopback port");
}
const localOrigin = `http://127.0.0.1:${address.port}`;

let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: true });
} catch {
  browser = await chromium.launch({ headless: true });
}

const cases = [
  { edition: "universal", locale: "en", success: true, width: 1440, height: 900 },
  { edition: "sim", locale: "zh-CN", success: true, width: 390, height: 844 },
  { edition: "lab", locale: "en", success: false, width: 760, height: 900 },
  { edition: "field", locale: "zh-CN", success: false, width: 390, height: 844 },
];
const measurements = [];

try {
  for (const testCase of cases) {
    const page = await browser.newPage({
      viewport: { width: testCase.width, height: testCase.height },
    });
    await page.route(homeUrl, (route) => route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<title>DroneDream</title>",
    }));
    const url = new URL("/callback-result", localOrigin);
    url.searchParams.set("edition", testCase.edition);
    url.searchParams.set("locale", testCase.locale);
    url.searchParams.set("success", String(testCase.success));
    await page.goto(url.toString());
    await page.locator("#result-title").waitFor();
    const measurement = await page.evaluate(() => ({
      language: document.documentElement.lang,
      documentClientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      brandVisible: Boolean(document.querySelector(".brand")?.getClientRects().length),
      inputCount: document.querySelectorAll("input").length,
      buttonCount: document.querySelectorAll("button").length,
      hasCancel: document.body.textContent?.includes("Cancel this sign-in") ?? false,
      hasPassword: /password|密码/iu.test(document.body.textContent ?? ""),
      result: document.querySelector("#result-mark")?.getAttribute("data-success"),
      title: document.title,
    }));
    if (
      measurement.language !== testCase.locale
      || measurement.documentClientWidth !== measurement.documentScrollWidth
      || !measurement.brandVisible
      || measurement.inputCount !== 0
      || measurement.buttonCount !== 0
      || measurement.hasCancel
      || measurement.hasPassword
      || measurement.result !== String(testCase.success)
    ) {
      throw new Error(
        `Browser-auth result layout failed for ${testCase.edition}: `
        + JSON.stringify(measurement),
      );
    }
    measurements.push({ ...testCase, ...measurement });
    if (outputDirectory) {
      await page.screenshot({
        path: resolve(
          outputDirectory,
          `${testCase.edition}-${testCase.locale}-${testCase.success ? "success" : "failure"}-${testCase.width}x${testCase.height}.png`,
        ),
        fullPage: true,
      });
    }
    if (testCase.success) {
      await page.waitForURL(homeUrl, { timeout: 5_000 });
    } else {
      await page.waitForTimeout(1_350);
      if (page.url() !== url.toString()) {
        throw new Error("Failed browser-auth result must not redirect automatically");
      }
    }
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolveClose) => server.close(resolveClose));
}

const summary = {
  schemaVersion: 2,
  browser: "Microsoft Edge (Playwright Chromium driver)",
  cases: measurements,
  credentialFields: 0,
  cancellationControls: 0,
  successRedirect: homeUrl,
  failureRedirect: null,
};
if (outputDirectory) {
  writeFileSync(
    resolve(outputDirectory, "measurements.json"),
    `${JSON.stringify(summary, null, 2)}\n`,
    "utf8",
  );
}
console.log(
  `Desktop browser-auth result verified: ${measurements.length} edition/locale/viewports, `
  + "0 credential fields, 0 cancellation controls.",
);
