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
const brandLockupDataUrl = `data:image/png;base64,${
  readFileSync(
    resolve(
      repositoryRoot,
      "frontend",
      "src",
      "assets",
      "drone-dream-lockup-compact.png",
    ),
  ).toString("base64")
}`;
const outputIndex = process.argv.indexOf("--output");
const outputDirectory = outputIndex >= 0
  ? resolve(process.argv[outputIndex + 1] ?? "")
  : null;
if (outputIndex >= 0 && !process.argv[outputIndex + 1]) {
  throw new Error("--output requires a directory");
}
if (outputDirectory) mkdirSync(outputDirectory, { recursive: true });

const accountOrigin = "https://yggabfynndpzymlqvnim.supabase.co";
const state = "browser-auth-visual-test-state";
const nonce = "browser-auth-visual-test-nonce";
const publishableKey = "sb_publishable_browser_auth_visual_test";
const completePath = `/desktop-auth/${state}/complete`;
const cancelPath = `/desktop-auth/${state}/cancel`;
const requests = [];
const completions = [];
const cancellations = [];

function renderPage(locale) {
  const replacements = new Map([
    ["__DOCUMENT_LANGUAGE__", locale],
    ["__CSP_NONCE__", nonce],
    ["__BRAND_LOCKUP_DATA_URL__", brandLockupDataUrl],
    ["__LOCALE_JSON__", JSON.stringify(locale)],
    ["__STATE_JSON__", JSON.stringify(state)],
    ["__SUPABASE_URL_JSON__", JSON.stringify(accountOrigin)],
    ["__PUBLISHABLE_KEY_JSON__", JSON.stringify(publishableKey)],
    ["__COMPLETE_PATH_JSON__", JSON.stringify(completePath)],
    ["__CANCEL_PATH_JSON__", JSON.stringify(cancelPath)],
    ["__HOME_URL_JSON__", JSON.stringify("http://getdronedream.com/")],
  ]);
  let page = template;
  for (const [placeholder, replacement] of replacements) {
    page = page.replaceAll(placeholder, replacement);
  }
  if (/__[A-Z][A-Z0-9_]+__/u.test(page)) {
    throw new Error("Browser-auth visual page still contains a placeholder");
  }
  return page;
}

function contentSecurityPolicy() {
  return [
    "default-src 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    `connect-src 'self' ${accountOrigin}`,
    `script-src 'nonce-${nonce}'`,
    `style-src 'nonce-${nonce}'`,
    "img-src data:",
    "font-src 'none'",
  ].join("; ");
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (request.method === "GET" && url.pathname.startsWith("/desktop-auth/")) {
    const locale = url.searchParams.get("locale") === "zh-CN" ? "zh-CN" : "en";
    const body = Buffer.from(renderPage(locale), "utf8");
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
  if (request.method === "POST" && url.pathname === completePath) {
    completions.push(await readJson(request));
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-type": "application/json",
    });
    response.end('{"accepted":true}');
    return;
  }
  if (request.method === "POST" && url.pathname === cancelPath) {
    cancellations.push(await readJson(request));
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-type": "application/json",
    });
    response.end('{"cancelled":true}');
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

const measurements = [];
const fakeSession = {
  access_token: "visual-test-access-token",
  refresh_token: "visual-test-refresh-token",
};

async function installRoutes(page) {
  await page.route(`${accountOrigin}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({
      method: request.method(),
      path: `${url.pathname}${url.search}`,
    });
    const corsHeaders = {
      "access-control-allow-origin": localOrigin,
      "access-control-allow-headers": "apikey, authorization, content-type",
      "access-control-allow-methods": "POST, PUT, OPTIONS",
      "content-type": "application/json",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }
    if (url.pathname.endsWith("/otp")) {
      await route.fulfill({ status: 200, headers: corsHeaders, body: "{}" });
      return;
    }
    if (url.pathname.endsWith("/user")) {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: '{"id":"visual-test-user"}',
      });
      return;
    }
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      body: JSON.stringify(fakeSession),
    });
  });
  await page.route("http://getdronedream.com/", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<title>DroneDream</title><p>Authentication complete.</p>",
    }));
}

async function captureLayout(page, name, viewport) {
  const measurement = await page.evaluate(() => {
    const brand = document.querySelector(".brand img")?.getBoundingClientRect();
    const firstInput = document.querySelector("input")?.getBoundingClientRect();
    return {
      documentClientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      formVisible: Boolean(document.querySelector("#auth-form")?.getClientRects().length),
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      mainBackground: getComputedStyle(document.querySelector("main")).backgroundColor,
      mainBorderRadius: getComputedStyle(document.querySelector("main")).borderRadius,
      brandWidth: brand?.width ?? 0,
      inputWidth: firstInput?.width ?? 0,
      hasExplanatoryCopy: Boolean(
        document.querySelector(".intro, .security-note, .tabs"),
      ),
      title: document.title,
    };
  });
  if (
    measurement.documentClientWidth !== measurement.documentScrollWidth
    || !measurement.formVisible
    || measurement.bodyBackground !== "rgb(255, 255, 255)"
    || measurement.mainBackground !== "rgba(0, 0, 0, 0)"
    || measurement.mainBorderRadius !== "0px"
    || Math.abs(measurement.brandWidth - measurement.inputWidth) > 1
    || measurement.hasExplanatoryCopy
  ) {
    throw new Error(
      `${name} browser-auth layout did not preserve the plain white, cardless contract: `
      + JSON.stringify(measurement),
    );
  }
  measurements.push({ name, viewport, ...measurement });
  if (outputDirectory) {
    await page.screenshot({
      path: resolve(outputDirectory, `${name}.png`),
      fullPage: true,
    });
  }
}

async function waitForCompletion(previousCount) {
  const deadline = Date.now() + 5_000;
  while (completions.length === previousCount && Date.now() < deadline) {
    await new Promise((resolveWait) => setTimeout(resolveWait, 25));
  }
  if (completions.length !== previousCount + 1) {
    throw new Error("Browser-auth callback was not received exactly once");
  }
  const completion = completions.at(-1);
  if (
    completion.state !== state
    || completion.accessToken !== fakeSession.access_token
    || completion.refreshToken !== fakeSession.refresh_token
  ) {
    throw new Error("Browser-auth callback did not preserve the exact session");
  }
}

try {
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await installRoutes(page);
    await page.goto(`${localOrigin}/desktop-auth/${state}?locale=en`);
    await page.getByRole("heading", { name: "Sign in to DroneDream" }).waitFor();
    await captureLayout(page, "en-login-1440x900", { width: 1440, height: 900 });
    await page.getByLabel("Email", { exact: true }).fill("pilot@example.test");
    await page.getByLabel("Password", { exact: true }).fill("password-for-visual-test");
    const previousCount = completions.length;
    await page.getByRole("button", {
      name: "Sign in and enter tuning workspace",
    }).click();
    await waitForCompletion(previousCount);
    if (
      page.url().includes(fakeSession.access_token)
      || page.url().includes(fakeSession.refresh_token)
    ) {
      throw new Error("Browser-auth token leaked into the browser URL");
    }
    await page.close();
  }
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await installRoutes(page);
    await page.goto(`${localOrigin}/desktop-auth/${state}?locale=zh-CN`);
    const localeState = await page.evaluate(() => ({
      language: document.documentElement.lang,
      registerLabel: document.querySelector("#switch-mode")?.textContent ?? "",
    }));
    if (
      localeState.language !== "zh-CN"
      || localeState.registerLabel !== "还没有账户？注册"
    ) {
      throw new Error(`Chinese browser-auth copy did not render: ${JSON.stringify(localeState)}`);
    }
    await page.getByRole("button", { name: "还没有账户？注册", exact: true }).click();
    await page.getByRole("heading", { name: "创建 DroneDream 账户" }).waitFor();
    await page.getByLabel("邮箱", { exact: true }).fill("pilot@example.test");
    await page.getByLabel("新密码", { exact: true }).fill("same-password-is-client-valid");
    await page.getByLabel("确认密码", { exact: true }).fill("same-password-is-client-valid");
    await captureLayout(page, "zh-register-390x844", { width: 390, height: 844 });
    await page.getByRole("button", { name: "发送验证码" }).click();
    await page.getByLabel("邮件验证码", { exact: true }).fill("123456");
    const previousCount = completions.length;
    await page.getByRole("button", { name: "创建账户", exact: true }).click();
    await page.getByRole("heading", { name: "登录并进入 DroneDream" }).waitFor();
    await page.getByText("账户已创建。请使用邮箱和密码登录。").waitFor();
    if (completions.length !== previousCount) {
      throw new Error("Registration must not complete the desktop sign-in");
    }
    if (await page.getByLabel("邮箱", { exact: true }).inputValue() !== "pilot@example.test") {
      throw new Error("Registration did not preserve the email for explicit sign-in");
    }
    await page.getByLabel("密码", { exact: true }).fill("same-password-is-client-valid");
    await page.getByRole("button", {
      name: "登录并进入调优平台",
      exact: true,
    }).click();
    await waitForCompletion(previousCount);
    await page.close();
  }
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await installRoutes(page);
    await page.goto(`${localOrigin}/desktop-auth/${state}?locale=en`);
    await page.getByRole("button", { name: "Forgot password?" }).click();
    await page.getByLabel("Email", { exact: true }).fill("pilot@example.test");
    await page.getByLabel("New password", { exact: true }).fill("same-password-is-client-valid");
    await page.getByLabel("Confirm password", { exact: true })
      .fill("same-password-is-client-valid");
    await captureLayout(page, "en-reset-1440x900", { width: 1440, height: 900 });
    await page.getByRole("button", { name: "Send code" }).click();
    await page.getByLabel("Email verification code", { exact: true }).fill("123456");
    const previousCount = completions.length;
    await page.getByRole("button", { name: "Update password and continue" }).click();
    await waitForCompletion(previousCount);
    await page.close();
  }
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await installRoutes(page);
    await page.goto(`${localOrigin}/desktop-auth/${state}?locale=en`);
    const previousCount = cancellations.length;
    await page.getByRole("button", { name: "Cancel this sign-in" }).click();
    const deadline = Date.now() + 5_000;
    while (cancellations.length === previousCount && Date.now() < deadline) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 25));
    }
    if (
      cancellations.length !== previousCount + 1
      || cancellations.at(-1)?.state !== state
    ) {
      throw new Error("Browser-auth cancellation was not received exactly once");
    }
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolveClose) => server.close(resolveClose));
}

if (requests.some((entry) =>
  JSON.stringify(entry).includes(fakeSession.access_token)
  || JSON.stringify(entry).includes(fakeSession.refresh_token))) {
  throw new Error("Browser-auth token leaked into the request inventory");
}
const otpRequests = requests.filter((entry) => entry.path.endsWith("/otp"));
const verifyRequests = requests.filter((entry) => entry.path.endsWith("/verify"));
const userUpdates = requests.filter((entry) => entry.path.endsWith("/user"));
if (otpRequests.length !== 2 || verifyRequests.length !== 2 || userUpdates.length !== 2) {
  throw new Error("Register/reset endpoint sequence did not run exactly twice");
}

const summary = {
  schemaVersion: 1,
  browser: "Microsoft Edge (Playwright Chromium driver)",
  cases: measurements,
  callbackCount: completions.length,
  cancellationCount: cancellations.length,
  accountRequests: requests,
  tokenInUrl: false,
  tokenInRequestInventory: false,
};
if (outputDirectory) {
  writeFileSync(
    resolve(outputDirectory, "measurements.json"),
    `${JSON.stringify(summary, null, 2)}\n`,
    "utf8",
  );
}
console.log(
  `Desktop browser auth verified: ${measurements.length} layouts, `
  + `${completions.length} exact callbacks, ${cancellations.length} cancellation, `
  + "no token URL leakage.",
);
