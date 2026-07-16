import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [
  url,
  selector = "#home",
  output = join(tmpdir(), "dronedream-site.png"),
  widthRaw = "1440",
  heightRaw = "1000",
  locale = "",
  actionBase64 = "",
] = process.argv.slice(2);
if (!url) {
  console.error("Usage: node capture-site.mjs <url> [selector] [output] [width] [height] [en|zh-CN] [action-base64]");
  process.exit(2);
}

const width = Number.parseInt(widthRaw, 10);
const height = Number.parseInt(heightRaw, 10);
if (!Number.isFinite(width) || !Number.isFinite(height) || width < 320 || height < 480) {
  throw new Error("Invalid viewport dimensions.");
}

const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const edge = edgeCandidates.find(existsSync);
if (!edge) throw new Error("Microsoft Edge was not found.");

const port = 9300 + Math.floor(Math.random() * 400);
const profile = join(tmpdir(), `dronedream-edge-${process.pid}-${Date.now()}`);
mkdirSync(profile, { recursive: true });

const browser = spawn(edge, [
  "--headless=new",
  "--no-first-run",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: "ignore" });

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function findPageTarget() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json());
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {
      // Browser startup is asynchronous.
    }
    await pause(100);
  }
  throw new Error("Timed out waiting for the Edge DevTools endpoint.");
}

let commandId = 0;
const pending = new Map();
const pageDiagnostics = [];

function connect(webSocketUrl) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webSocketUrl);
    socket.addEventListener("open", () => resolve(socket), { once: true });
    socket.addEventListener("error", reject, { once: true });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.method === "Runtime.exceptionThrown") {
        const details = message.params?.exceptionDetails;
        pageDiagnostics.push(details?.exception?.description ?? details?.text ?? "Uncaught page exception");
      }
      if (message.method === "Runtime.consoleAPICalled" && message.params?.type === "error") {
        const text = (message.params.args ?? [])
          .map((argument) => argument.value ?? argument.description ?? "")
          .filter(Boolean)
          .join(" ");
        pageDiagnostics.push(text || "console.error was called");
      }
      if (!message.id) return;
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
      else request.resolve(message.result);
    });
  });
}

function command(socket, method, params = {}) {
  const id = ++commandId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function waitForPageReady(socket, targetSelector, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await command(socket, "Runtime.evaluate", {
      expression: `document.readyState === "complete" && Boolean(document.querySelector(${JSON.stringify(targetSelector)}))`,
      returnByValue: true,
    });
    if (result?.result?.value === true) return;
    await pause(250);
  }
  throw new Error(`Timed out waiting for ${targetSelector} to render.`);
}

try {
  const socket = await connect(await findPageTarget());
  await command(socket, "Page.enable");
  await command(socket, "Runtime.enable");
  await command(socket, "Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width <= 600,
  });
  await command(socket, "Page.navigate", { url });
  await waitForPageReady(socket, selector);
  if (locale === "en" || locale === "zh-CN") {
    await command(socket, "Runtime.evaluate", {
      expression: `localStorage.setItem("drone-dream:locale", ${JSON.stringify(locale)}); location.reload()`,
      awaitPromise: true,
    });
    await waitForPageReady(socket, selector);
  }
  if (actionBase64) {
    const action = Buffer.from(actionBase64, "base64").toString("utf8");
    await command(socket, "Runtime.evaluate", {
      expression: `(async () => { ${action} })()`,
      awaitPromise: true,
    });
    await pause(750);
  }
  await command(socket, "Runtime.evaluate", {
    expression: `document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({block: "start"})`,
    awaitPromise: true,
  });
  await pause(2_000);
  const screenshot = await command(socket, "Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  writeFileSync(output, Buffer.from(screenshot.data, "base64"));
  console.log(output);
  if (pageDiagnostics.length > 0) {
    throw new Error(`Page diagnostics:\n${pageDiagnostics.join("\n")}`);
  }
  socket.close();
} finally {
  browser.kill();
  for (let attempt = 0; attempt < 20 && browser.exitCode === null; attempt += 1) {
    await pause(100);
  }
  // Edge can keep a short-lived crash-handler process attached to its profile
  // after the main process exits. Do not turn a valid screenshot into a failed
  // QA run solely because Windows needs another moment to release that folder.
  let cleanupError;
  for (let attempt = 0; attempt < 40 && existsSync(profile); attempt += 1) {
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 2, retryDelay: 100 });
      cleanupError = undefined;
    } catch (error) {
      if (!["EBUSY", "ENOTEMPTY", "EPERM"].includes(error?.code)) throw error;
      cleanupError = error;
      await pause(250);
    }
  }
  if (existsSync(profile)) {
    console.warn(`Could not remove temporary Edge profile ${profile}: ${cleanupError?.message ?? "still in use"}`);
  }
}
