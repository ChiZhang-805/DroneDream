import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = frontendRequire("playwright");

const [baseUrlRaw, outputRaw = ""] = process.argv.slice(2);
if (!baseUrlRaw) {
  console.error("Usage: node audit-community-manual-ui.mjs <base-url> [output-directory]");
  process.exit(2);
}

const baseUrl = new URL(baseUrlRaw.endsWith("/") ? baseUrlRaw : `${baseUrlRaw}/`);
const outputDirectory = resolve(outputRaw || "website-ui-audit");
mkdirSync(outputDirectory, { recursive: true });

const discoverSupabaseAuthStorageKeys = async () => {
  const keys = new Set(["sb-local-preview-auth-token"]);
  try {
    const html = await (await fetch(new URL("site.html", baseUrl))).text();
    const scriptUrls = [...html.matchAll(/<script[^>]+src="([^"]+)"/giu)]
      .map((match) => new URL(match[1], baseUrl));
    for (const scriptUrl of scriptUrls) {
      const script = await (await fetch(scriptUrl)).text();
      for (const match of script.matchAll(/https:\/\/([a-z0-9-]+)\.supabase\.co/giu)) {
        keys.add(`sb-${match[1]}-auth-token`);
      }
    }
  } catch {
    // The local Vite source server does not expose a compiled bundle. Its
    // documented audit configuration uses the local-preview fallback above.
  }
  return [...keys];
};

const authStorageKeys = await discoverSupabaseAuthStorageKeys();

const edgeCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const executablePath = edgeCandidates.find(existsSync);
if (!executablePath) throw new Error("Microsoft Edge was not found.");

const accountId = "00000000-0000-0000-0000-000000000099";
const authorId = "00000000-0000-0000-0000-000000000042";
const now = "2026-07-29T01:00:00.000Z";
const topics = [
  {
    title: "Diagnosing altitude overshoot after a route change",
    body: "Compare matched flight seeds before accepting a gain change.",
    tags: ["Failure analysis", "Simulation"],
  },
  {
    title: "Bayesian optimization versus CMA-ES under a fixed budget",
    body: "A reproducible comparison with identical simulator budgets.",
    tags: ["Optimizer", "Evidence"],
  },
  {
    title: "Wind-robust circular-track tuning in PX4",
    body: "Review holdout evidence under controlled wind disturbances.",
    tags: ["PX4", "Flight track"],
  },
  {
    title: "Tracking a slow convergence plateau",
    body: "A bounded study of convergence diagnostics and stopping rules.",
    tags: ["Simulation", "Evidence"],
  },
  {
    title: "Cross-seed evidence for a safer candidate",
    body: "Five independent seeds expose the candidate's failure boundary.",
    tags: ["Evidence", "Failure analysis"],
  },
].map((topic, index) => ({
  id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
  author_id: authorId,
  author_name: `pilot-${index + 1}`,
  image_urls: [],
  created_at: now,
  comment_count: index,
  like_count: index + 2,
  liked_by_viewer: false,
  ...topic,
}));

const base64Url = (value) => Buffer.from(JSON.stringify(value))
  .toString("base64url");
const accessToken = [
  base64Url({ alg: "HS256", typ: "JWT" }),
  base64Url({
    aud: "authenticated",
    exp: 4_102_444_800,
    iat: 1_785_279_600,
    sub: accountId,
    email: "visual-audit@example.invalid",
    role: "authenticated",
  }),
  "visual-audit-signature",
].join(".");
const auditUser = {
  id: accountId,
  aud: "authenticated",
  role: "authenticated",
  email: "visual-audit@example.invalid",
  email_confirmed_at: now,
  phone: "",
  confirmed_at: now,
  last_sign_in_at: now,
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: { display_name: "Visual audit pilot" },
  identities: [],
  created_at: now,
  updated_at: now,
  is_anonymous: false,
};
const auditSession = {
  access_token: accessToken,
  token_type: "bearer",
  expires_in: 2_316_932_000,
  expires_at: 4_102_444_800,
  refresh_token: "visual-audit-refresh-token",
  user: auditUser,
};

const profiles = [
  {
    name: "desktop",
    viewport: { width: 1440, height: 1000 },
    desktop: true,
    expectedRecentCards: 5,
    topicCount: 5,
  },
  {
    name: "wide-desktop",
    viewport: { width: 2000, height: 1080 },
    desktop: true,
    expectedRecentCards: 5,
    topicCount: 5,
  },
  {
    name: "wide-three-topics",
    viewport: { width: 2000, height: 1080 },
    desktop: true,
    expectedRecentCards: 3,
    topicCount: 3,
  },
  {
    name: "mobile",
    viewport: { width: 390, height: 844 },
    desktop: false,
    expectedRecentCards: 5,
    topicCount: 5,
  },
];
const locales = ["en", "zh-CN"];
const results = [];

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu"],
});

const installApiRoutes = async (context, topicCount) => {
  const fulfillApiRoute = async (route) => {
    const url = new URL(route.request().url());
    const headers = {
      "access-control-allow-origin": baseUrl.origin,
      "access-control-allow-credentials": "true",
      "content-type": "application/json",
    };
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (url.pathname.endsWith("/rpc/community_list_topics")) {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify(topics.slice(0, topicCount)),
      });
      return;
    }
    if (url.pathname.endsWith("/rpc/community_list_comments")) {
      await route.fulfill({ status: 200, headers, body: "[]" });
      return;
    }
    if (url.pathname.endsWith("/auth/v1/user")) {
      await route.fulfill({ status: 200, headers, body: JSON.stringify(auditUser) });
      return;
    }
    await route.fulfill({ status: 404, headers, body: JSON.stringify({ message: "audit stub" }) });
  };
  await context.route("**/auth/v1/**", fulfillApiRoute);
  await context.route("**/rest/v1/rpc/**", fulfillApiRoute);
};

const settle = async (page) => {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      [...document.images]
        .filter((image) => {
          const rect = image.getBoundingClientRect();
          return rect.bottom >= 0
            && rect.top <= window.innerHeight
            && rect.right >= 0
            && rect.left <= window.innerWidth;
        })
        .map((image) => image.decode().catch(() => undefined)),
    );
    await new Promise((resolveFrame) => requestAnimationFrame(() => requestAnimationFrame(resolveFrame)));
  });
  await page.waitForTimeout(250);
};

const screenshot = async (page, name, fullPage = false) => {
  const path = join(outputDirectory, `${name}.png`);
  await page.screenshot({ path, fullPage, animations: "disabled" });
  return path;
};

const pageLayout = async (page) => page.evaluate(() => ({
  viewportWidth: document.documentElement.clientWidth,
  documentWidth: Math.max(
    document.documentElement.scrollWidth,
    document.body?.scrollWidth ?? 0,
  ),
  viewportHeight: window.innerHeight,
  documentHeight: document.documentElement.scrollHeight,
  footerPresent: document.querySelector(".site-footer") !== null,
}));

try {
  for (const profile of profiles) {
    for (const locale of locales) {
      const context = await browser.newContext({
        viewport: profile.viewport,
        locale: locale === "zh-CN" ? "zh-CN" : "en-US",
        reducedMotion: "reduce",
        serviceWorkers: "block",
      });
      await context.addInitScript(({ activeLocale, session, storageKeys }) => {
        localStorage.setItem("drone-dream:locale", activeLocale);
        storageKeys.forEach((key) => localStorage.setItem(key, JSON.stringify(session)));
      }, {
        activeLocale: locale,
        session: auditSession,
        storageKeys: authStorageKeys,
      });
      await installApiRoutes(context, profile.topicCount);
      const page = await context.newPage();
      const failures = [];
      const prefix = `${locale}-${profile.name}`;

      await page.goto(new URL("community/", baseUrl).href, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await page.waitForSelector(".community-topic-grid > article", { timeout: 60_000 });
      await settle(page);
      const recent = await page.evaluate(() => {
        const articles = [...document.querySelectorAll(".community-topic-grid > article")];
        const feed = document.querySelector(".community-feed");
        const more = document.querySelector(".community-more");
        const search = document.querySelector(".community-search");
        const filterRow = document.querySelector(".community-filter-row");
        const moreRect = more?.getBoundingClientRect();
        const searchRect = search?.getBoundingClientRect();
        const filterRect = filterRow?.getBoundingClientRect();
        return {
          ...(feed instanceof HTMLElement ? {
            feedBottom: Math.round(feed.getBoundingClientRect().bottom),
            feedScrollHeight: feed.scrollHeight,
            feedClientHeight: feed.clientHeight,
          } : {}),
          visibleCards: articles.filter((article) => {
            const style = getComputedStyle(article);
            const rect = article.getBoundingClientRect();
            return style.display !== "none" && rect.width > 0 && rect.height > 0;
          }).length,
          ...(moreRect ? {
            moreTop: Math.round(moreRect.top),
            moreBottom: Math.round(moreRect.bottom),
            moreRight: Math.round(moreRect.right),
          } : {}),
          searchRight: Math.round(searchRect?.right ?? 0),
          filterTop: Math.round(filterRect?.top ?? 0),
          filterBottom: Math.round(filterRect?.bottom ?? 0),
          cardRects: articles.map((article) => {
            const rect = article.getBoundingClientRect();
            const cover = article.querySelector(".community-topic-cover");
            const body = article.querySelector(".community-topic-card-body");
            const title = cover?.querySelector(".community-cover-art > strong");
            const coverRect = cover?.getBoundingClientRect();
            const bodyRect = body?.getBoundingClientRect();
            return {
              display: getComputedStyle(article).display,
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              top: Math.round(rect.top),
              bottom: Math.round(rect.bottom),
              clientHeight: article.clientHeight,
              scrollHeight: article.scrollHeight,
              coverWidth: Math.round(coverRect?.width ?? 0),
              coverHeight: Math.round(coverRect?.height ?? 0),
              coverTop: Math.round(coverRect?.top ?? 0),
              coverBottom: Math.round(coverRect?.bottom ?? 0),
              coverPosition: cover ? getComputedStyle(cover).position : "",
              coverAspectRatio: cover ? getComputedStyle(cover).aspectRatio : "",
              bodyHeight: Math.round(bodyRect?.height ?? 0),
              bodyClientHeight: body?.clientHeight ?? 0,
              bodyScrollHeight: body?.scrollHeight ?? 0,
              titleScrollWidth: title?.scrollWidth ?? 0,
              titleClientWidth: title?.clientWidth ?? 0,
            };
          }),
          footerPresent: document.querySelector(".site-footer") !== null,
        };
      });
      const recentLayout = await pageLayout(page);
      if (recent.footerPresent) failures.push("community recent unexpectedly renders footer");
      if (recentLayout.documentWidth > recentLayout.viewportWidth + 2) {
        failures.push("community recent has document horizontal overflow");
      }
      if (recentLayout.documentHeight > recentLayout.viewportHeight + 2) {
        failures.push(
          `community recent owns document vertical scroll `
          + `(${recentLayout.documentHeight}px > ${recentLayout.viewportHeight}px)`,
        );
      }
      if (
        profile.expectedRecentCards !== null
        && recent.visibleCards !== profile.expectedRecentCards
      ) {
        failures.push(
          `${profile.name} recent visible card count ${recent.visibleCards}, `
          + `expected ${profile.expectedRecentCards}`,
        );
      }
      if (
        recent.cardRects.some((card) =>
          card.display !== "none"
          && card.bottom > recent.feedBottom + 1
        )
      ) {
        failures.push("desktop recent card extends below its feed");
      }
      if (
        recent.feedScrollHeight > recent.feedClientHeight + 2
      ) {
        failures.push("community recent feed clips content");
      }
      if (
        !recent.moreRight
        || Math.abs(recent.moreRight - recent.searchRight) > 3
        || recent.moreTop < recent.filterTop - 1
        || recent.moreBottom > recent.filterBottom + 1
      ) {
        failures.push("community recent More topics is not aligned with the search/filter edge");
      }
      if (profile.desktop) {
        const visibleCardBottoms = recent.cardRects
          .filter((card) => card.display !== "none")
          .map((card) => card.bottom);
        const maxCardBottom = Math.max(...visibleCardBottoms);
        const cardToFeedGap = recent.feedBottom - maxCardBottom;
        if (cardToFeedGap < 6 || cardToFeedGap > 26) {
          failures.push(
            `desktop recent card-to-feed gap ${cardToFeedGap}px outside 6-26px`,
          );
        }
      }
      if (
        recent.cardRects.some((card) =>
          card.display !== "none"
          && (
            card.bodyHeight < 64
            || card.scrollHeight > card.clientHeight + 2
            || card.bodyScrollHeight > card.bodyClientHeight + 2
            || card.coverTop < card.top - 1
            || card.coverBottom > card.bottom - card.bodyHeight + 2
            || card.titleScrollWidth > card.titleClientWidth + 2
          )
        )
      ) {
        failures.push("community recent card cover or body is not fully contained");
      }
      await screenshot(page, `${prefix}-community-recent`);

      await page.locator(".community-topic-cover").first().click();
      const dialog = page.locator(".community-topic-dialog");
      await dialog.waitFor({ state: "visible" });
      await settle(page);
      const detail = await page.evaluate(() => {
        const dialogNode = document.querySelector(".community-topic-dialog");
        const visual = document.querySelector(".community-topic-dialog-visual");
        const cover = visual?.querySelector(":scope > .community-cover-art");
        const textarea = document.querySelector(".community-comment-form textarea");
        if (
          !(dialogNode instanceof HTMLElement)
          || !(visual instanceof HTMLElement)
          || !(cover instanceof HTMLElement)
          || !(textarea instanceof HTMLTextAreaElement)
        ) return null;
        const visualRect = visual.getBoundingClientRect();
        const coverRect = cover.getBoundingClientRect();
        const dialogRect = dialogNode.getBoundingClientRect();
        return {
          dialog: {
            left: dialogRect.left,
            top: dialogRect.top,
            width: dialogRect.width,
            height: dialogRect.height,
          },
          visual: {
            left: visualRect.left,
            top: visualRect.top,
            width: visualRect.width,
            height: visualRect.height,
          },
          cover: {
            left: coverRect.left,
            top: coverRect.top,
            width: coverRect.width,
            height: coverRect.height,
          },
          textareaHeight: textarea.getBoundingClientRect().height,
        };
      });
      if (!detail) {
        failures.push("topic detail did not expose the cover and signed-in comment form");
      } else {
        const tolerance = 2;
        for (const dimension of ["left", "top", "width", "height"]) {
          if (Math.abs(detail.visual[dimension] - detail.cover[dimension]) > tolerance) {
            failures.push(`topic cover does not fill visual ${dimension}`);
          }
        }
        const minimumTextarea = profile.desktop ? 190 : 132;
        if (detail.textareaHeight + tolerance < minimumTextarea) {
          failures.push(`comment textarea ${detail.textareaHeight}px below ${minimumTextarea}px`);
        }
      }
      const textarea = page.locator(".community-comment-form textarea");
      await textarea.focus();
      await textarea.fill("Keyboard focus and submission remain available.");
      if (!await page.getByRole("button", { name: /Post comment|发表评论/u }).isEnabled()) {
        failures.push("comment submit remains disabled after valid input");
      }
      await screenshot(page, `${prefix}-community-topic-detail`);
      await page.keyboard.press("Escape");

      await page.goto(new URL("community/?view=all", baseUrl).href, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await page.waitForSelector(".community-topic-grid > article", { timeout: 60_000 });
      await settle(page);
      const allTopics = await page.evaluate(() => {
        const feed = document.querySelector(".community-feed");
        const pageNode = document.querySelector(".community-page");
        const header = document.querySelector(".site-header");
        const headerRect = header?.getBoundingClientRect();
        return {
          ...(feed instanceof HTMLElement ? {
            feedOverflowY: getComputedStyle(feed).overflowY,
            feedScrollHeight: feed.scrollHeight,
            feedClientHeight: feed.clientHeight,
          } : {}),
          ...(pageNode instanceof HTMLElement ? {
            pageOverflowY: getComputedStyle(pageNode).overflowY,
          } : {}),
          headerLeft: headerRect?.left ?? null,
          headerRightGap: headerRect ? window.innerWidth - headerRect.right : null,
          footerPresent: document.querySelector(".site-footer") !== null,
        };
      });
      const allLayout = await pageLayout(page);
      if (allTopics.footerPresent) failures.push("all topics unexpectedly renders footer");
      if (["auto", "scroll"].includes(allTopics.feedOverflowY)) {
        failures.push(`all topics feed owns vertical scroll (${allTopics.feedOverflowY})`);
      }
      if (["auto", "scroll"].includes(allTopics.pageOverflowY)) {
        failures.push(`all topics page owns vertical scroll (${allTopics.pageOverflowY})`);
      }
      if (allLayout.documentHeight <= allLayout.viewportHeight) {
        failures.push("all topics does not extend the document for browser scrolling");
      }
      if (allLayout.documentWidth > allLayout.viewportWidth + 2) {
        failures.push("all topics has document horizontal overflow");
      }
      await screenshot(page, `${prefix}-community-all-topics`, true);

      await page.goto(new URL("manual/", baseUrl).href, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await page.waitForSelector(".manual-reader-document [data-manual-heading='true']", {
        timeout: 60_000,
      });
      await settle(page);
      const initialManual = await page.evaluate(() => {
        const header = document.querySelector(".site-header");
        const sidebar = document.querySelector(".manual-sidebar");
        const toggles = [...document.querySelectorAll(".manual-nav-toggle")];
        const groupToggles = [...document.querySelectorAll(".manual-nav-group-row")];
        const readerHeader = document.querySelector(".manual-reader-header");
        const introductionHeading = document.querySelector(".manual-markdown > h1:first-child");
        const firstChapterRow = document.querySelector(
          ".manual-nav-chapter:not(.is-step-group) .manual-nav-chapter-row",
        );
        const readerEyebrow = document.querySelector(".manual-reader-header p");
        const readerTitle = document.querySelector(".manual-reader-header h1");
        const introductionParagraphs = [];
        let introductionSibling = introductionHeading?.nextElementSibling;
        while (introductionSibling && introductionSibling.tagName !== "H2") {
          if (introductionSibling.tagName === "P") introductionParagraphs.push(introductionSibling);
          introductionSibling = introductionSibling.nextElementSibling;
        }
        const headerRect = header?.getBoundingClientRect();
        const sidebarRect = sidebar?.getBoundingClientRect();
        const brandRect = document.querySelector(".site-brand")?.getBoundingClientRect();
        const readerHeaderRect = readerHeader?.getBoundingClientRect();
        const firstChapterRowRect = firstChapterRow?.getBoundingClientRect();
        const introductionHeadingRect = introductionHeading?.getBoundingClientRect();
        const readerEyebrowRect = readerEyebrow?.getBoundingClientRect();
        const readerTitleRect = readerTitle?.getBoundingClientRect();
        const isWithinViewport = (selector) => {
          const element = document.querySelector(selector);
          if (!(element instanceof HTMLElement)) return false;
          const style = getComputedStyle(element);
          if (style.display === "none" || style.visibility === "hidden") return true;
          const rect = element.getBoundingClientRect();
          return rect.left >= -1 && rect.right <= window.innerWidth + 1;
        };
        return {
          headerHeight: headerRect?.height ?? null,
          headerBottom: headerRect?.bottom ?? null,
          sidebarTop: sidebarRect?.top ?? null,
          sidebarScrollHeight: sidebar instanceof HTMLElement ? sidebar.scrollHeight : null,
          sidebarClientHeight: sidebar instanceof HTMLElement ? sidebar.clientHeight : null,
          brandLeft: brandRect?.left ?? null,
          headerContentWithinViewport:
            isWithinViewport(".site-brand")
            && isWithinViewport(".site-header-actions"),
          toggleCount: toggles.length,
          expandedCount: toggles.filter((toggle) => toggle.getAttribute("aria-expanded") === "true").length,
          expandedGroupCount: groupToggles.filter(
            (toggle) => toggle.getAttribute("aria-expanded") === "true",
          ).length,
          groupToggleCount: groupToggles.length,
          numericChapterLabelCount: [...document.querySelectorAll(
            ".manual-nav-chapter-row > a > strong",
          )].filter((label) => /^\d+\./u.test(label.textContent?.trim() ?? "")).length,
          readerHeaderPdfPresent: Boolean(document.querySelector(".manual-reader-header > a")),
          readerHeaderDescriptionPresent: Boolean(
            document.querySelector(".manual-reader-header div > span"),
          ),
          readerHeaderBorderBottom: readerHeader instanceof HTMLElement
            ? getComputedStyle(readerHeader).borderBottomWidth
            : null,
          firstChapterTop: firstChapterRowRect?.top ?? null,
          introductionHeadingTop: introductionHeadingRect?.top ?? null,
          readerTopBreathing: readerHeaderRect && readerEyebrowRect
            ? readerEyebrowRect.top - readerHeaderRect.top
            : null,
          readerBottomBreathing: introductionHeadingRect && readerTitleRect
            ? introductionHeadingRect.top - readerTitleRect.bottom
            : null,
          introductionParagraphCount: introductionParagraphs.length,
          editionSubtitlePresent: Boolean(
            document.querySelector(".manual-sidebar-title span"),
          ),
          footerPresent: document.querySelector(".site-footer") !== null,
        };
      });
      if (initialManual.footerPresent) failures.push("manual unexpectedly renders footer");
      if (initialManual.editionSubtitlePresent) failures.push("manual sidebar edition subtitle remains");
      if (!initialManual.toggleCount) failures.push("manual has no chapter toggles");
      if (initialManual.expandedCount) failures.push("manual chapters are not collapsed by default");
      if (initialManual.expandedGroupCount) failures.push("manual step group is not collapsed by default");
      if (initialManual.groupToggleCount !== 1) failures.push("manual five-step group is missing");
      if (initialManual.numericChapterLabelCount) {
        failures.push("manual chapter labels retain duplicate numeric prefixes");
      }
      if (initialManual.readerHeaderPdfPresent) failures.push("manual reader retains duplicate PDF action");
      if (initialManual.readerHeaderDescriptionPresent) {
        failures.push("manual reader retains the removed supporting description");
      }
      if (initialManual.readerHeaderBorderBottom !== "0px") {
        failures.push("manual reader retains the faint separator above the first chapter");
      }
      if (initialManual.introductionParagraphCount !== 1) {
        failures.push(
          `manual introduction has ${initialManual.introductionParagraphCount} paragraphs instead of one`,
        );
      }
      if (profile.desktop && initialManual.brandLeft !== null && initialManual.brandLeft > 25) {
        failures.push(`manual brand remains ${initialManual.brandLeft}px from the left edge`);
      }
      if (
        profile.desktop
        && initialManual.firstChapterTop !== null
        && initialManual.introductionHeadingTop !== null
        && Math.abs(
          initialManual.firstChapterTop - initialManual.introductionHeadingTop,
        ) > 2
      ) {
        failures.push(
          "manual introduction heading no longer aligns with the first sidebar chapter",
        );
      }
      if (
        profile.desktop
        && (initialManual.readerTopBreathing === null
          || initialManual.readerTopBreathing < 24)
      ) {
        failures.push("manual reader eyebrow lacks top breathing room");
      }
      if (
        profile.desktop
        && (initialManual.readerBottomBreathing === null
          || initialManual.readerBottomBreathing < 40)
      ) {
        failures.push("manual reader title lacks bottom breathing room");
      }
      if (
        profile.desktop
        && initialManual.sidebarScrollHeight > initialManual.sidebarClientHeight + 2
      ) {
        failures.push("collapsed manual navigation does not fit its initial sidebar viewport");
      }
      if (!initialManual.headerContentWithinViewport) {
        failures.push("manual header content is clipped before scrolling");
      }

      const firstToggle = page.locator(".manual-nav-toggle").first();
      await firstToggle.focus();
      await firstToggle.press("Enter");
      if (await firstToggle.getAttribute("aria-expanded") !== "true") {
        failures.push("manual chapter did not expand from keyboard");
      }
      const firstSubsectionIndent = await page.evaluate(() => {
        const chapter = document.querySelector(".manual-nav-chapter:not(.is-step-group)");
        const chapterRow = chapter?.querySelector(".manual-nav-chapter-row");
        const subsection = chapter?.querySelector(".manual-nav-subsections .is-subsection");
        const chapterRowRect = chapterRow?.getBoundingClientRect();
        const subsectionRect = subsection?.getBoundingClientRect();
        return chapterRowRect && subsectionRect
          ? subsectionRect.left - chapterRowRect.left
          : null;
      });
      initialManual.firstSubsectionIndent = firstSubsectionIndent;
      if (
        profile.desktop
        && (firstSubsectionIndent === null || firstSubsectionIndent < 16)
      ) {
        failures.push("manual chapter subsection lacks a clear nested indent");
      }
      await firstToggle.press("Enter");
      const chapterToggleLabels = await page.locator(".manual-nav-toggle").evaluateAll(
        (toggles) => toggles.map((toggle) => toggle.getAttribute("aria-label") ?? ""),
      );
      const workspaceToggleIndex = chapterToggleLabels.findIndex(
        (label) => /:\s*(?:Workspace|工作区)/u.test(label),
      );
      if (workspaceToggleIndex < 0) {
        failures.push("manual workspace chapter toggle is missing");
      } else {
        const workspaceToggle = page.locator(".manual-nav-toggle").nth(workspaceToggleIndex);
        await workspaceToggle.focus();
        await workspaceToggle.press("Enter");
        if (await workspaceToggle.getAttribute("aria-expanded") !== "true") {
          failures.push("manual workspace chapter did not expand from keyboard");
        }
      }
      const accountLabel = locale === "en"
        ? "Accounts and data"
        : "账户与数据";
      const accountLink = page.locator(".manual-sidebar").getByRole("link", {
        name: accountLabel,
        exact: true,
      });
      if (await accountLink.count() !== 1) {
        failures.push(`manual shortened account label is missing: ${accountLabel}`);
      } else {
        const accountLabelLayout = await accountLink.evaluate((link) => {
          const label = link.querySelector("strong");
          if (!(label instanceof HTMLElement)) {
            return { lineCount: 0, fontSize: 0, withinWidth: false };
          }
          const range = document.createRange();
          range.selectNodeContents(label);
          const lineTops = [...range.getClientRects()].map((rect) => Math.round(rect.top));
          return {
            lineCount: new Set(lineTops).size,
            fontSize: Number.parseFloat(getComputedStyle(label).fontSize),
            withinWidth: label.scrollWidth <= label.clientWidth + 1,
          };
        });
        if (accountLabelLayout.lineCount !== 1 || !accountLabelLayout.withinWidth) {
          failures.push(`manual ${accountLabel} navigation label wraps`);
        }
        if (accountLabelLayout.fontSize < 12) {
          failures.push(`manual ${accountLabel} navigation label uses undersized text`);
        }
      }
      await screenshot(page, `${prefix}-manual-accordion`);
      await page.evaluate(() => window.scrollTo({ top: 1_500, behavior: "instant" }));
      await settle(page);
      const scrolledManual = await page.evaluate(() => {
        const headerRect = document.querySelector(".site-header")?.getBoundingClientRect();
        const sidebarRect = document.querySelector(".manual-sidebar")?.getBoundingClientRect();
        const isWithinViewport = (selector) => {
          const element = document.querySelector(selector);
          if (!(element instanceof HTMLElement)) return false;
          const style = getComputedStyle(element);
          if (style.display === "none" || style.visibility === "hidden") return true;
          const rect = element.getBoundingClientRect();
          return rect.left >= -1 && rect.right <= window.innerWidth + 1;
        };
        return {
          headerHeight: headerRect?.height ?? null,
          headerBottom: headerRect?.bottom ?? null,
          sidebarTop: sidebarRect?.top ?? null,
          headerContentWithinViewport:
            isWithinViewport(".site-brand")
            && isWithinViewport(".site-header-actions"),
          scrollY: window.scrollY,
        };
      });
      if (Math.abs((initialManual.headerHeight ?? 0) - (scrolledManual.headerHeight ?? 0)) > 1) {
        failures.push("manual header height changes after scrolling");
      }
      if (
        profile.desktop
        && Math.abs((scrolledManual.headerBottom ?? 0) - (scrolledManual.sidebarTop ?? 0)) > 1
      ) {
        failures.push("manual sticky header and sidebar no longer meet");
      }
      if (!scrolledManual.headerContentWithinViewport) {
        failures.push("manual header content is clipped after scrolling");
      }
      const manualLayout = await pageLayout(page);
      if (manualLayout.documentWidth > manualLayout.viewportWidth + 2) {
        failures.push("manual has document horizontal overflow");
      }
      await screenshot(page, `${prefix}-manual-scrolled`);

      await page.goto(new URL("pricing/", baseUrl).href, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await settle(page);
      const pricingLayout = await pageLayout(page);
      if (pricingLayout.footerPresent) failures.push("product page unexpectedly renders footer");
      if (pricingLayout.documentWidth > pricingLayout.viewportWidth + 2) {
        failures.push("product page has document horizontal overflow");
      }
      await screenshot(page, `${prefix}-product`);

      await page.goto(new URL("site.html", baseUrl).href, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await settle(page);
      const homeLayout = await pageLayout(page);
      if (!homeLayout.footerPresent) failures.push("homepage footer is missing");

      results.push({
        locale,
        profile,
        recent,
        recentLayout,
        detail,
        allTopics,
        allLayout,
        initialManual,
        scrolledManual,
        manualLayout,
        pricingLayout,
        homeFooterPresent: homeLayout.footerPresent,
        failures,
      });
      await context.close();
    }
  }
} finally {
  await browser.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: baseUrl.href,
  results,
  summary: {
    cases: results.length,
    passed: results.filter((result) => result.failures.length === 0).length,
    failed: results.filter((result) => result.failures.length > 0).length,
    failures: results.flatMap((result) =>
      result.failures.map((failure) => `${result.locale}/${result.profile.name}: ${failure}`),
    ),
  },
};
writeFileSync(
  join(outputDirectory, "community-manual-ui-audit.json"),
  `${JSON.stringify(report, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify(report.summary, null, 2));
if (report.summary.failed > 0) process.exitCode = 1;
