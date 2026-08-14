import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const label = process.argv[2] || "after";
const outputRoot = path.join(repoRoot, "artifacts", "test-runs", "community-layout", label);
const host = "127.0.0.1";
const port = 5194;
const origin = `http://${host}:${port}`;

process.env.VITE_SUPABASE_URL = origin;
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "community-layout-test-key";

const shortTitles = [
  "Hover recovery evidence",
  "Route tracking comparison",
  "Wind tunnel notes",
  "Battery sag diagnosis",
  "Motor response review",
  "航线跟踪证据",
  "悬停恢复记录",
  "风场测试复查",
  "电池压降分析",
  "电机响应比较",
];

const topics = Array.from({ length: 28 }, (_, index) => {
  const rankedIndex = index + 1;
  const isLong = rankedIndex > 10 && [12, 17, 23].includes(rankedIndex);
  return {
    id: `00000000-0000-0000-0000-${String(rankedIndex).padStart(12, "0")}`,
    author_id: rankedIndex % 2 ? "docs-preview" : "evidence-pilot",
    author_name: rankedIndex % 2 ? "DroneDream Pilot" : "Evidence Pilot",
    author_avatar_url: rankedIndex % 2
      ? null
      : "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32'%3E%3Crect width='32' height='32' rx='16' fill='%238a4ad0'/%3E%3C/svg%3E",
    title: isLong
      ? `Cross-scenario recovery evidence with a deliberately detailed engineering title ${rankedIndex}`
      : `${shortTitles[index % shortTitles.length]} ${rankedIndex}`,
    body: "Reproducible local evidence with the aircraft, route, parameters, and observed result.",
    tags: ["PX4", "Evidence", "Flight track"],
    image_urls: [],
    created_at: `2026-08-${String(14 - Math.floor(index / 4)).padStart(2, "0")}T10:00:00Z`,
    comment_count: rankedIndex,
    like_count: rankedIndex * 2,
    liked_by_viewer: false,
    card_variant: isLong ? "long" : "short",
  };
});

function filteredTopics(payload) {
  const query = String(payload?.p_search || "").trim().toLowerCase();
  const tag = String(payload?.p_tag || "").trim();
  const offset = Number(payload?.p_offset || 0);
  const limit = Number(payload?.p_limit || 24);
  const matches = topics.filter((topic) =>
    (!query || `${topic.title} ${topic.body} ${topic.tags.join(" ")}`.toLowerCase().includes(query))
    && (!tag || topic.tags.includes(tag))
  );
  return { matches, page: matches.slice(offset, offset + limit) };
}

async function mockCommunityApi(page) {
  await page.route("**/rest/v1/rpc/**", async (route) => {
    const request = route.request();
    const name = new URL(request.url()).pathname.split("/").at(-1);
    const payload = request.postDataJSON?.() || {};
    const { matches, page: topicPage } = filteredTopics(payload);
    const body = name === "community_count_topics"
      ? JSON.stringify(matches.length)
      : name === "community_list_comments"
        ? "[]"
        : JSON.stringify(topicPage);
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });
}

async function measure(page) {
  return page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const bounds = element.getBoundingClientRect();
      return {
        left: Number(bounds.left.toFixed(2)),
        top: Number(bounds.top.toFixed(2)),
        right: Number(bounds.right.toFixed(2)),
        bottom: Number(bounds.bottom.toFixed(2)),
        width: Number(bounds.width.toFixed(2)),
        height: Number(bounds.height.toFixed(2)),
      };
    };
    const headings = Array.from(document.querySelectorAll(".community-hero h1"), (entry) => entry.textContent?.trim());
    return {
      language: document.documentElement.lang,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
      },
      hero: box(".community-hero"),
      heroTitle: box(".community-hero h1"),
      heroButton: box(".community-hero > button"),
      feed: box(".community-feed"),
      grid: box(".community-topic-grid"),
      headings,
      cards: document.querySelectorAll(".community-topic-grid article").length,
      longCards: document.querySelectorAll(".community-topic-grid article.is-long").length,
      maxTags: Math.max(0, ...Array.from(
        document.querySelectorAll(".community-topic-grid .community-cover-tags"),
        (entry) => entry.children.length,
      )),
      oldHeroTitles: Array.from(document.querySelectorAll(".community-hero *"), (entry) => entry.textContent?.trim())
        .filter((value) => value === "All topics" || value === "Share questions. Compare flight evidence.").length,
    };
  });
}

await mkdir(path.dirname(outputRoot), { recursive: true });
await mkdir(outputRoot);
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.site.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
});

let browser;
const results = [];
try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });

  for (const testCase of [
    { id: "recent-en", locale: "en", path: "/community/?docsPreview=1", viewport: { width: 1440, height: 900 }, expectedCards: 5 },
    { id: "all-zh", locale: "zh-CN", path: "/community/?view=all&docsPreview=1", viewport: { width: 1920, height: 1080 }, expectedCards: 10 },
  ]) {
    const context = await browser.newContext({ viewport: testCase.viewport, colorScheme: "light" });
    await context.addInitScript((locale) => window.localStorage.setItem("drone-dream:locale", locale), testCase.locale);
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockCommunityApi(page);
    await page.goto(`${origin}${testCase.path}`, { waitUntil: "networkidle" });
    await page.locator(".community-topic-grid article").first().waitFor();
    const initial = await measure(page);
    await page.screenshot({ path: path.join(outputRoot, `${testCase.id}.png`) });

    let mixedPage = null;
    if (testCase.id === "all-zh") {
      await page.getByRole("button", { name: "第 2" }).click();
      await page.locator(".community-topic-grid article.is-long").first().waitFor();
      mixedPage = await measure(page);
      await page.screenshot({ path: path.join(outputRoot, "all-zh-mixed.png") });
    }

    const aligned = initial.heroTitle && initial.feed
      && Math.abs(initial.heroTitle.left - initial.feed.left) <= 1;
    const passed = initial.language === testCase.locale
      && initial.cards === testCase.expectedCards
      && initial.oldHeroTitles === 0
      && initial.maxTags <= 3
      && aligned
      && initial.document.scrollWidth <= initial.document.clientWidth + 1
      && initial.document.scrollHeight <= initial.document.clientHeight + 1
      && (!mixedPage || (mixedPage.longCards > 0 && mixedPage.cards <= 10 && mixedPage.maxTags <= 3))
      && consoleErrors.length === 0
      && pageErrors.length === 0;
    results.push({ ...testCase, passed, initial, mixedPage, aligned, consoleErrors, pageErrors });
    await context.close();
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
  await context.addInitScript(() => window.localStorage.setItem("drone-dream:locale", "en"));
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mockCommunityApi(page);
  await page.goto(`${origin}/community/?docsPreview=1`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Create a topic" }).click();
  const titleInput = page.locator("#community-topic-title-input");
  await titleInput.fill("Crosswind recovery\nwith payload evidence");
  await page.getByRole("button", { name: "Long card" }).click();
  await page.locator(".community-composer-preview .community-cover-copy strong").waitFor();
  const composer = await page.evaluate(() => ({
    dialog: Boolean(document.querySelector(".community-composer")),
    columns: getComputedStyle(document.querySelector(".community-composer-layout")).gridTemplateColumns,
    previewLong: Boolean(document.querySelector(".community-composer-preview article.is-long")),
    previewTitle: document.querySelector(".community-composer-preview .community-cover-copy strong")?.textContent,
    dialogScrolls: document.querySelector(".community-composer")?.scrollHeight > document.querySelector(".community-composer")?.clientHeight,
  }));
  await page.screenshot({ path: path.join(outputRoot, "composer-en-long.png") });
  const passed = composer.dialog
    && composer.previewLong
    && composer.previewTitle === "Crosswind recovery\nwith payload evidence"
    && composer.columns.split(" ").length >= 2
    && !composer.dialogScrolls
    && consoleErrors.length === 0
    && pageErrors.length === 0;
  results.push({ id: "composer-en-long", passed, composer, consoleErrors, pageErrors });
  await context.close();
} finally {
  await browser?.close();
  await server.close();
}

const evidence = {
  schemaVersion: 1,
  expected: "Community uses one aligned purple title, compact ten-slot discovery pages, mixed card sizes, and a synchronized two-column composer",
  passed: results.every((result) => result.passed),
  results,
};
await writeFile(path.join(outputRoot, "measurements.json"), `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
for (const result of results) {
  process.stdout.write(`${result.id}: ${result.passed ? "PASS" : "FAIL"}\n`);
}
process.stdout.write(`Evidence: ${path.join(outputRoot, "measurements.json")}\n`);
if (!evidence.passed) process.exitCode = 1;
