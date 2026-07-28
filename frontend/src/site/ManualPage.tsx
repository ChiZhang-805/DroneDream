import {
  BookOpen,
  ChevronRight,
  Download,
  FileDown,
  FileText,
  Languages,
  LoaderCircle,
  RotateCw,
  Search,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { extractManualHeadings, type ManualHeading } from "./manualParser";

const ManualDocument = lazy(() => import("./ManualDocument"));

type SiteLocale = "en" | "zh-CN";

interface ManualPageProps {
  locale: SiteLocale;
}

type LoadState = "loading" | "ready" | "error";

interface ManualNavigationChapter {
  heading: ManualHeading;
  subsections: ManualHeading[];
}

const manualCopy = {
  en: {
    ariaLabel: "DroneDream manual contents",
    contents: "Manual contents",
    edition: "English edition",
    search: "Search chapters",
    downloads: "Download editions",
    markdown: "Markdown",
    pdf: "PDF",
    online: "ONLINE MANUAL",
    title: "DroneDream 1.0.0 User Manual",
    description:
      "The complete field-by-field guide, rendered as a native web document with the same verified text, tables, and product screenshots as the downloadable editions.",
    loading: "Preparing the complete manual…",
    error: "The manual document could not be loaded.",
    retry: "Try again",
    noMatches: "No chapter title matches this search.",
    expandChapter: "Expand chapter",
    collapseChapter: "Collapse chapter",
  },
  "zh-CN": {
    ariaLabel: "DroneDream 说明书目录",
    contents: "说明书目录",
    edition: "简体中文版",
    search: "搜索章节",
    downloads: "下载版本",
    markdown: "Markdown",
    pdf: "PDF",
    online: "在线说明书",
    title: "DroneDream 1.0.0 用户说明书",
    description:
      "把经过校验的完整文字、字段表格和软件截图重新排成网站原生文档；PDF 与 Markdown 仅作为离线下载版本。",
    loading: "正在准备完整说明书……",
    error: "说明书正文加载失败。",
    retry: "重新加载",
    noMatches: "没有与搜索内容匹配的章节标题。",
    expandChapter: "展开章节",
    collapseChapter: "收起章节",
  },
} as const;

function normalizeSearch(value: string, locale: SiteLocale): string {
  return value.trim().toLocaleLowerCase(locale);
}

function manualNavigationLabel(heading: ManualHeading, locale: SiteLocale): string {
  if (!/^2\.2(?:\s|$)/u.test(heading.plainLabel)) return heading.plainLabel;
  return locale === "zh-CN" ? "2.2 账户与数据" : "2.2 Accounts and data";
}

export function ManualPage({ locale }: ManualPageProps) {
  const copy = manualCopy[locale];
  const documentRoot = locale === "en"
    ? "/docs/downloads/DroneDream-Manual-en"
    : "/docs/downloads/DroneDream-Manual-zh-CN";
  const [source, setSource] = useState("");
  const [state, setState] = useState<LoadState>("loading");
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState("");
  const [expandedChapterIds, setExpandedChapterIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [loadAttempt, setLoadAttempt] = useState(0);
  const articleRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    setSource("");
    setQuery("");
    setActiveId("");
    setExpandedChapterIds(new Set());

    void fetch(`${documentRoot}.md`, {
      cache: "force-cache",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Manual request failed: ${response.status}`);
        return response.text();
      })
      .then((value) => {
        if (controller.signal.aborted) return;
        setSource(value);
        setState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });

    return () => controller.abort();
  }, [documentRoot, loadAttempt]);

  const headings = useMemo(() => extractManualHeadings(source), [source]);
  const navigationChapters = useMemo(() => {
    const normalized = normalizeSearch(query, locale);
    const chapters: ManualNavigationChapter[] = [];
    headings
      .filter((heading) => heading.level <= 2)
      .forEach((heading) => {
        if (heading.level === 1) {
          chapters.push({ heading, subsections: [] });
          return;
        }
        chapters.at(-1)?.subsections.push(heading);
      });
    if (!normalized) return chapters;
    return chapters.flatMap((chapter) => {
      const chapterMatches = normalizeSearch(
        manualNavigationLabel(chapter.heading, locale),
        locale,
      ).includes(normalized);
      const matchingSubsections = chapter.subsections.filter((heading) =>
        normalizeSearch(
          manualNavigationLabel(heading, locale),
          locale,
        ).includes(normalized),
      );
      if (!chapterMatches && matchingSubsections.length === 0) return [];
      return [{
        ...chapter,
        subsections: chapterMatches ? chapter.subsections : matchingSubsections,
      }];
    });
  }, [headings, locale, query]);

  useEffect(() => {
    if (!headings.length) return;
    setActiveId((current) => current || headings[0].id);

    const root = articleRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    let observer: IntersectionObserver | undefined;
    let observedCount = 0;

    const connect = () => {
      const observed = Array.from(
        root.querySelectorAll<HTMLElement>("[data-manual-heading='true']"),
      );
      if (!observed.length || observed.length === observedCount) return;
      observer?.disconnect();
      observedCount = observed.length;
      observer = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
          const first = visible[0]?.target;
          if (first instanceof HTMLElement) setActiveId(first.id);
        },
        { rootMargin: "-18% 0px -70% 0px", threshold: [0, 1] },
      );
      observed.forEach((heading) => observer?.observe(heading));
    };

    connect();
    const mutationObserver = new MutationObserver(connect);
    mutationObserver.observe(root, { childList: true, subtree: true });

    return () => {
      mutationObserver.disconnect();
      observer?.disconnect();
    };
  }, [headings, state]);

  const navigateToHeading = (heading: ManualHeading) => {
    setActiveId(heading.id);
    const target = document.getElementById(heading.id);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `#${heading.id}`);
  };

  const toggleChapter = (chapterId: string) => {
    setExpandedChapterIds((current) => {
      const next = new Set(current);
      if (next.has(chapterId)) next.delete(chapterId);
      else next.add(chapterId);
      return next;
    });
  };

  return (
    <div className="site-portal site-manual-page">
      <aside className="manual-sidebar" aria-label={copy.ariaLabel}>
        <header className="manual-sidebar-title">
          <BookOpen aria-hidden="true" />
          <strong>{copy.contents}</strong>
        </header>

        <label className="manual-search">
          <Search aria-hidden="true" />
          <span className="site-sr-only">{copy.search}</span>
          <input
            type="search"
            placeholder={copy.search}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        <div className="manual-downloads" role="group" aria-label={copy.downloads}>
          <strong>{copy.downloads}</strong>
          <div>
            <a href={`${documentRoot}.md`} download>
              <FileText aria-hidden="true" />
              {copy.markdown}
            </a>
            <a href={`${documentRoot}.pdf`} download>
              <FileDown aria-hidden="true" />
              {copy.pdf}
            </a>
          </div>
        </div>

        <nav aria-label={copy.contents}>
          {navigationChapters.map((chapter) => {
            const expanded = Boolean(query)
              || expandedChapterIds.has(chapter.heading.id);
            const chapterPanelId = `${chapter.heading.id}-subsections`;
            const chapterContainsActive = activeId === chapter.heading.id
              || chapter.subsections.some((heading) => heading.id === activeId);
            return (
              <div
                key={chapter.heading.id}
                className={`manual-nav-chapter${chapterContainsActive ? " contains-active" : ""}`}
              >
                <div className="manual-nav-chapter-row">
                  <a
                    href={`#${chapter.heading.id}`}
                    className={activeId === chapter.heading.id ? "is-active" : ""}
                    aria-current={activeId === chapter.heading.id ? "location" : undefined}
                    onClick={(event) => {
                      event.preventDefault();
                      navigateToHeading(chapter.heading);
                    }}
                  >
                    <span aria-hidden="true">
                      {String(chapter.heading.majorIndex + 1).padStart(2, "0")}
                    </span>
                    <strong>{manualNavigationLabel(chapter.heading, locale)}</strong>
                  </a>
                  {chapter.subsections.length ? (
                    <button
                      type="button"
                      className="manual-nav-toggle"
                      aria-expanded={expanded}
                      aria-controls={chapterPanelId}
                      aria-label={`${expanded ? copy.collapseChapter : copy.expandChapter}: ${manualNavigationLabel(chapter.heading, locale)}`}
                      onClick={() => toggleChapter(chapter.heading.id)}
                    >
                      <ChevronRight aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
                {chapter.subsections.length ? (
                  <div
                    id={chapterPanelId}
                    className="manual-nav-subsections"
                    hidden={!expanded}
                  >
                    {chapter.subsections.map((heading) => (
                      <a
                        key={heading.id}
                        href={`#${heading.id}`}
                        className={`is-subsection${activeId === heading.id ? " is-active" : ""}`}
                        aria-current={activeId === heading.id ? "location" : undefined}
                        onClick={(event) => {
                          event.preventDefault();
                          navigateToHeading(heading);
                        }}
                      >
                        <span aria-hidden="true">—</span>
                        <strong>{manualNavigationLabel(heading, locale)}</strong>
                      </a>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
          {state === "ready" && !navigationChapters.length ? (
            <p className="manual-no-results">{copy.noMatches}</p>
          ) : null}
        </nav>
      </aside>

      <section className="manual-reader" aria-labelledby="manual-reader-title">
        <header className="manual-reader-header">
          <div>
            <p>
              <Languages aria-hidden="true" />
              {copy.online} · {copy.edition}
            </p>
            <h1 id="manual-reader-title">{copy.title}</h1>
            <span>{copy.description}</span>
          </div>
          <a href={`${documentRoot}.pdf`} download>
            <Download aria-hidden="true" />
            PDF
          </a>
        </header>

        <article ref={articleRef} className="manual-reader-document">
          {state === "loading" ? (
            <div className="manual-reader-state" role="status">
              <LoaderCircle className="is-spinning" aria-hidden="true" />
              <p>{copy.loading}</p>
            </div>
          ) : null}
          {state === "error" ? (
            <div className="manual-reader-state" role="alert">
              <BookOpen aria-hidden="true" />
              <p>{copy.error}</p>
              <button type="button" onClick={() => setLoadAttempt((value) => value + 1)}>
                <RotateCw aria-hidden="true" />
                {copy.retry}
              </button>
            </div>
          ) : null}
          {state === "ready" ? (
            <Suspense
              fallback={(
                <div className="manual-reader-state" role="status">
                  <LoaderCircle className="is-spinning" aria-hidden="true" />
                  <p>{copy.loading}</p>
                </div>
              )}
            >
              <ManualDocument source={source} headings={headings} />
            </Suspense>
          ) : null}
        </article>
      </section>
    </div>
  );
}
