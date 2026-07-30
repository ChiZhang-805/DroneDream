import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { gzipSync } from "node:zlib";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [baseUrlRaw, outputRaw = ""] = process.argv.slice(2);
if (!baseUrlRaw) {
  console.error("Usage: node audit-site-performance.mjs <base-url> [output.json]");
  process.exit(2);
}

const baseUrl = new URL(baseUrlRaw.endsWith("/") ? baseUrlRaw : `${baseUrlRaw}/`);
if (!["http:", "https:"].includes(baseUrl.protocol)) {
  throw new Error("The performance base URL must use HTTP or HTTPS.");
}

const outputPath = outputRaw ? resolve(outputRaw) : "";
const routes = [
  { name: "home", path: "/" },
  { name: "pricing", path: "/pricing/" },
  { name: "manual", path: "/manual/" },
  { name: "community", path: "/community/" },
  { name: "account", path: "/account/?source=website&mode=sign-in&returnTo=%2F" },
  { name: "console", path: "/console/" },
];
const budgets = {
  requestCount: 28,
  totalRawBytes: 3_000_000,
  totalGzipBytes: 900_000,
  javascriptRawBytes: 1_700_000,
  javascriptGzipBytes: 520_000,
  cssRawBytes: 300_000,
  cssGzipBytes: 70_000,
  imageRawBytes: 650_000,
  largestResourceRawBytes: 850_000,
};

const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const executablePath = edgeCandidates.find(existsSync);
const browser = await chromium.launch({
  ...(executablePath ? { executablePath } : {}),
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

const classify = (url, contentType) => {
  const path = new URL(url).pathname.toLowerCase();
  const type = contentType.toLowerCase();
  if (type.includes("javascript") || path.endsWith(".js")) return "javascript";
  if (type.includes("text/css") || path.endsWith(".css")) return "css";
  if (type.startsWith("image/") || /\.(?:avif|gif|jpe?g|png|svg|webp)$/u.test(path)) return "image";
  if (type.includes("font") || /\.(?:otf|ttf|woff2?)$/u.test(path)) return "font";
  if (type.includes("html") || path.endsWith(".html") || path.endsWith("/")) return "document";
  return "data";
};
const compressible = (contentType, category) => (
  ["javascript", "css", "document", "data"].includes(category)
  || /(?:json|svg|text|xml)/u.test(contentType)
);

const results = [];
try {
  for (const route of routes) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      locale: "en-US",
      reducedMotion: "reduce",
      serviceWorkers: "block",
    });
    await context.addInitScript(() => {
      localStorage.setItem("drone-dream:locale", "en");
    });
    const page = await context.newPage();
    const resources = new Map();
    const pendingResponses = [];
    page.on("response", (response) => {
      const responseUrl = response.url();
      if (new URL(responseUrl).origin !== baseUrl.origin) return;
      if (response.status() < 200 || response.status() >= 400) return;
      const responseTask = (async () => {
        await response.finished();
        const body = await response.body();
        const contentType = response.headers()["content-type"] ?? "";
        const category = classify(responseUrl, contentType);
        const gzipBytes = compressible(contentType, category)
          ? gzipSync(body, { level: 9 }).byteLength
          : body.byteLength;
        resources.set(responseUrl, {
          url: responseUrl,
          path: new URL(responseUrl).pathname,
          category,
          contentType,
          rawBytes: body.byteLength,
          gzipBytes,
        });
      })().catch((error) => {
        resources.set(responseUrl, {
          url: responseUrl,
          path: new URL(responseUrl).pathname,
          category: "error",
          contentType: "",
          rawBytes: 0,
          gzipBytes: 0,
          error: error instanceof Error ? error.message : String(error),
        });
      });
      pendingResponses.push(responseTask);
    });

    const url = new URL(route.path, baseUrl).href;
    await page.goto(url, { waitUntil: "networkidle", timeout: 60_000 });
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise((resolveFrame) => {
        requestAnimationFrame(() => requestAnimationFrame(resolveFrame));
      });
    });
    await page.waitForTimeout(250);
    await Promise.all(pendingResponses);

    const resourceList = [...resources.values()]
      .sort((left, right) => right.rawBytes - left.rawBytes);
    const sum = (category, field) => resourceList
      .filter((resource) => !category || resource.category === category)
      .reduce((total, resource) => total + resource[field], 0);
    const metrics = {
      requestCount: resourceList.length,
      totalRawBytes: sum(null, "rawBytes"),
      totalGzipBytes: sum(null, "gzipBytes"),
      javascriptRawBytes: sum("javascript", "rawBytes"),
      javascriptGzipBytes: sum("javascript", "gzipBytes"),
      cssRawBytes: sum("css", "rawBytes"),
      cssGzipBytes: sum("css", "gzipBytes"),
      imageRawBytes: sum("image", "rawBytes"),
      largestResourceRawBytes: resourceList[0]?.rawBytes ?? 0,
    };
    const violations = Object.entries(budgets)
      .filter(([metric, maximum]) => metrics[metric] > maximum)
      .map(([metric, maximum]) => `${metric} ${metrics[metric]} exceeds ${maximum}`);
    const resourceErrors = resourceList
      .filter((resource) => resource.error)
      .map((resource) => `${resource.path}: ${resource.error}`);
    violations.push(...resourceErrors);
    results.push({
      route: route.name,
      url,
      metrics,
      budgets,
      violations,
      resources: resourceList,
    });
    await context.close();
  }
} finally {
  await browser.close();
}

const failures = results.filter((result) => result.violations.length > 0);
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: baseUrl.href,
  browser: executablePath ?? "playwright-chromium",
  budgets,
  summary: {
    routes: results.length,
    passed: results.length - failures.length,
    failed: failures.length,
  },
  failures: failures.map(({ route, violations }) => ({ route, violations })),
  results,
};

if (outputPath) {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}
console.table(results.map((result) => ({
  route: result.route,
  requests: result.metrics.requestCount,
  rawKB: Math.round(result.metrics.totalRawBytes / 1024),
  gzipKB: Math.round(result.metrics.totalGzipBytes / 1024),
  jsGzipKB: Math.round(result.metrics.javascriptGzipBytes / 1024),
  cssGzipKB: Math.round(result.metrics.cssGzipBytes / 1024),
  largestKB: Math.round(result.metrics.largestResourceRawBytes / 1024),
  status: result.violations.length ? "failed" : "passed",
})));
console.log(JSON.stringify({
  output: outputPath || null,
  summary: report.summary,
  failures: report.failures,
}, null, 2));
if (failures.length > 0) process.exitCode = 1;
