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
const origin = "http://127.0.0.1:5194";

process.env.VITE_SUPABASE_URL = origin;
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "community-layout-test-key";

const topics = Array.from({ length: 12 }, (_, index) => ({
  id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
  author_id: "docs-preview",
  author_name: "DroneDream Pilot",
  author_avatar_url: null,
  title: `Natural-language mission study ${index + 1}`,
  body: "A concise English topic description prepared for the unified landscape community card system.",
  tags: ["Flight agent", "PX4", "Mission"],
  image_urls: [],
  created_at: `2026-10-${String(19 - Math.floor(index / 4)).padStart(2, "0")}T10:00:00Z`,
  comment_count: index,
  like_count: index * 2,
  liked_by_viewer: false,
  card_variant: "long",
}));

async function mockCommunityApi(page) {
  await page.route("**/rest/v1/rpc/**", async (route) => {
    const name = new URL(route.request().url()).pathname.split("/").at(-1);
    const payload = route.request().postDataJSON?.() || {};
    const query = String(payload.p_search || "").trim().toLowerCase();
    const tag = String(payload.p_tag || "").trim();
    const matches = topics.filter((topic) =>
      (!query || `${topic.title} ${topic.body} ${topic.tags.join(" ")}`.toLowerCase().includes(query))
      && (!tag || topic.tags.includes(tag))
    );
    const body = name === "community_count_topics"
      ? JSON.stringify(matches.length)
      : name === "community_list_comments"
        ? "[]"
        : JSON.stringify(matches);
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });
}

function assertion(condition, message) {
  if (!condition) throw new Error(message);
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.site.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host: "127.0.0.1", port: 5194, strictPort: true },
});

let browser;
const report = [];
try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const cases = [
    { id: "recent-desktop", path: "/community/?docsPreview=1", width: 1440, height: 900 },
    { id: "all-desktop", path: "/community/?view=all&docsPreview=1", width: 1920, height: 1080 },
    { id: "recent-compact", path: "/community/?docsPreview=1", width: 1366, height: 768 },
  ];

  for (const testCase of cases) {
    const context = await browser.newContext({ viewport: { width: testCase.width, height: testCase.height } });
    await context.addInitScript(() => window.localStorage.setItem("drone-dream:locale", "en"));
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await mockCommunityApi(page);
    await page.goto(`${origin}${testCase.path}`, { waitUntil: "networkidle" });
    await page.locator(".community-topic-grid article").first().waitFor();

    const metrics = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".community-topic-grid article"));
      const rects = cards.map((card) => {
        const rect = card.getBoundingClientRect();
        return { width: rect.width, height: rect.height, bottom: rect.bottom };
      });
      const pagination = document.querySelector(".community-pagination")?.getBoundingClientRect();
      return {
        count: cards.length,
        widths: rects.map((rect) => rect.width),
        heights: rects.map((rect) => rect.height),
        legacyVariants: document.querySelectorAll("article.is-long, article.is-short").length,
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        paginationBottom: pagination?.bottom ?? 0,
        viewportHeight: window.innerHeight,
        titles: Array.from(document.querySelectorAll(".community-cover-title-group > strong"), (node) => node.textContent || ""),
      };
    });
    assertion(metrics.count === 5, `${testCase.id}: expected five cards, received ${metrics.count}`);
    assertion(metrics.legacyVariants === 0, `${testCase.id}: legacy card variants remain`);
    assertion(Math.max(...metrics.widths) - Math.min(...metrics.widths) < 2, `${testCase.id}: card widths differ`);
    assertion(Math.max(...metrics.heights) - Math.min(...metrics.heights) < 2, `${testCase.id}: card heights differ`);
    assertion(metrics.overflowX <= 1, `${testCase.id}: horizontal document overflow`);
    assertion(metrics.paginationBottom <= metrics.viewportHeight + 1, `${testCase.id}: pagination is below the viewport`);
    assertion(
      metrics.titles.every((title) => Array.from(title).every((character) => character.codePointAt(0) <= 0x7f)),
      `${testCase.id}: non-English card copy found`,
    );

    await page.getByRole("button", { name: "Page 2" }).click();
    await page.getByText("Natural-language mission study 6", { exact: true }).waitFor();
    await page.screenshot({ path: path.join(outputRoot, `${testCase.id}.png`), fullPage: true });
    report.push({ ...testCase, ...metrics, pageTwoStartsWith: "Natural-language mission study 6", errors });
    assertion(errors.length === 0, `${testCase.id}: browser errors: ${errors.join("; ")}`);
    await context.close();
  }
  await writeFile(path.join(outputRoot, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${outputRoot}\n`);
} finally {
  await browser?.close();
  await server.close();
}
