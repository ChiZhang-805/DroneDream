import {
  ChevronLeft,
  ChevronRight,
  FileDown,
  FileText,
  Languages,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCw,
  Search,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import {
  extractManualHeadings,
  stripManualFrontmatter,
  type ManualHeading,
} from "./manualParser";

const ManualDocument = lazy(() => import("./ManualDocument"));

type SiteLocale = "en" | "zh-CN";

interface ManualPageProps {
  locale: SiteLocale;
}

type LoadState = "loading" | "ready" | "error";

declare const __DRONEDREAM_CONTENT_REVISION__: string;

const manualContentRevision =
  typeof __DRONEDREAM_CONTENT_REVISION__ === "undefined"
    ? "development"
    : __DRONEDREAM_CONTENT_REVISION__;

interface ManualNavigationChapter {
  kind: "chapter";
  heading: ManualHeading;
  subsections: ManualHeading[];
}

interface ManualNavigationGroup {
  kind: "group";
  id: string;
  label: string;
  chapters: ManualNavigationChapter[];
}

type ManualNavigationItem = ManualNavigationChapter | ManualNavigationGroup;

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
    title: "DroneDream Manual",
    wizard: "Five-step workflow",
    loading: "Preparing the complete manual…",
    error: "The manual document could not be loaded.",
    retry: "Try again",
    noMatches: "No chapter title matches this search.",
    expandChapter: "Expand chapter",
    collapseChapter: "Collapse chapter",
    hideContents: "Hide manual contents",
    showContents: "Show manual contents",
    chapterNavigation: "Chapter navigation",
    previousChapter: "Previous chapter",
    nextChapter: "Next chapter",
    beginning: "Beginning",
    ending: "End of manual",
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
    title: "DroneDream Manual",
    wizard: "五步实验流程",
    loading: "正在准备完整说明书……",
    error: "说明书正文加载失败。",
    retry: "重新加载",
    noMatches: "没有与搜索内容匹配的章节标题。",
    expandChapter: "展开章节",
    collapseChapter: "收起章节",
    hideContents: "收起说明书目录",
    showContents: "展开说明书目录",
    chapterNavigation: "章节导航",
    previousChapter: "上一章",
    nextChapter: "下一章",
    beginning: "手册开篇",
    ending: "手册结尾",
  },
} as const;

function normalizeSearch(value: string, locale: SiteLocale): string {
  return value.trim().toLocaleLowerCase(locale);
}

function manualNavigationLabel(heading: ManualHeading, locale: SiteLocale): string {
  const withoutNumber = heading.plainLabel
    .replace(/^\d+(?:\.\d+)*\.?\s+/u, "")
    .replace(/^Appendix\s+[A-Z]\s*[—-]\s*/u, "")
    .replace(/^附录\s*[A-Z]\s*[—-]\s*/u, "");

  const compactLabels: Record<SiteLocale, Record<string, string>> = {
    en: {
      "Workspace orientation": "Workspace",
      "Two ways to create an experiment": "Create an experiment",
      "Monitor, compare, and interpret results": "Results and evidence",
      "Exit, recovery, and safe interruption": "Exit and recovery",
      "Common study patterns": "Study patterns",
      "Validation limits at a glance": "Validation limits",
    },
    "zh-CN": {
      "两种创建实验的方式": "创建实验",
      "监控、比较与解释结果": "结果与证据",
      "退出、恢复与安全中断": "退出与恢复",
      "第一次实验检查表": "首次实验检查表",
      "常见研究模板": "研究模板",
      "校验范围速查": "校验范围",
    },
  };

  return compactLabels[locale][withoutNumber] ?? withoutNumber;
}

function isWizardStep(heading: ManualHeading, locale: SiteLocale): boolean {
  return locale === "zh-CN"
    ? /^\d+\.\s*第[一二三四五]步/u.test(heading.plainLabel)
    : /^\d+\.\s*Step\s+[1-5]\b/u.test(heading.plainLabel);
}

function extractManualChapterSource(source: string, chapterIndex: number): string {
  const body = stripManualFrontmatter(source);
  const lines = body.split(/\r?\n/);
  const chapterStarts = lines.flatMap((line, index) => (
    /^#\s+\S/u.test(line) ? [index] : []
  ));
  const start = chapterStarts[chapterIndex];
  if (start === undefined) return "";
  const end = chapterStarts[chapterIndex + 1] ?? lines.length;
  return lines
    .slice(start, end)
    .join("\n")
    .replace(/\n---\s*$/u, "")
    .trim();
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
  const [activeChapterIndex, setActiveChapterIndex] = useState(0);
  const [expandedChapterIds, setExpandedChapterIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const articleRef = useRef<HTMLElement>(null);
  const pendingHeadingIdRef = useRef("");

  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    setSource("");
    setQuery("");
    setActiveId("");
    setActiveChapterIndex(0);
    pendingHeadingIdRef.current = "";
    setExpandedChapterIds(new Set());

    void fetch(
      `${documentRoot}.md?revision=${encodeURIComponent(manualContentRevision)}`,
      {
        cache: "no-store",
        signal: controller.signal,
      },
    )
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
  const manualChapters = useMemo(
    () => headings.filter((heading) => heading.level === 1),
    [headings],
  );
  const activeChapterHeadings = useMemo(
    () => headings.filter((heading) => heading.majorIndex === activeChapterIndex),
    [activeChapterIndex, headings],
  );
  const activeChapterSource = useMemo(
    () => extractManualChapterSource(source, activeChapterIndex),
    [activeChapterIndex, source],
  );
  const previousChapter = manualChapters[activeChapterIndex - 1];
  const nextChapter = manualChapters[activeChapterIndex + 1];
  const navigationChapters = useMemo(() => {
    const normalized = normalizeSearch(query, locale);
    const chapters: ManualNavigationChapter[] = [];
    headings
      .filter((heading) => heading.level <= 2)
      .forEach((heading) => {
        if (heading.level === 1) {
          chapters.push({ kind: "chapter", heading, subsections: [] });
          return;
        }
        chapters.at(-1)?.subsections.push(heading);
      });

    const items: ManualNavigationItem[] = [];
    const wizardChapters: ManualNavigationChapter[] = [];
    chapters.forEach((chapter) => {
      if (isWizardStep(chapter.heading, locale)) {
        wizardChapters.push(chapter);
        return;
      }
      if (wizardChapters.length && !items.some((item) => item.kind === "group")) {
        items.push({
          kind: "group",
          id: "manual-five-step-workflow",
          label: copy.wizard,
          chapters: [...wizardChapters],
        });
      }
      items.push(chapter);
    });
    if (wizardChapters.length && !items.some((item) => item.kind === "group")) {
      items.push({
        kind: "group",
        id: "manual-five-step-workflow",
        label: copy.wizard,
        chapters: [...wizardChapters],
      });
    }

    if (!normalized) return items;

    const filterChapter = (chapter: ManualNavigationChapter) => {
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
      if (!chapterMatches && matchingSubsections.length === 0) return null;
      return {
        ...chapter,
        subsections: chapterMatches ? chapter.subsections : matchingSubsections,
      };
    };

    const filteredItems: ManualNavigationItem[] = [];
    items.forEach((item) => {
      if (item.kind === "chapter") {
        const match = filterChapter(item);
        if (match) filteredItems.push(match);
        return;
      }
      const groupMatches = normalizeSearch(item.label, locale).includes(normalized);
      const matchingChapters = groupMatches
        ? item.chapters
        : item.chapters.flatMap((chapter) => {
          const match = filterChapter(chapter);
          return match ? [match] : [];
        });
      if (matchingChapters.length) {
        filteredItems.push({ ...item, chapters: matchingChapters });
      }
    });
    return filteredItems;
  }, [copy.wizard, headings, locale, query]);

  useEffect(() => {
    if (!navigationChapters.length) return;
    setExpandedChapterIds((current) => {
      if (current.size) return current;
      const expanded = new Set<string>();
      navigationChapters.forEach((item) => {
        expanded.add(item.kind === "group" ? item.id : item.heading.id);
      });
      return expanded;
    });
  }, [navigationChapters]);

  useEffect(() => {
    if (!headings.length) return;
    const hashId = decodeURIComponent(window.location.hash.replace(/^#/u, ""));
    const initialHeading = headings.find((heading) => heading.id === hashId) ?? headings[0];
    setActiveId((current) => current || initialHeading.id);
    setActiveChapterIndex(initialHeading.majorIndex);
    if (hashId && initialHeading.id === hashId) pendingHeadingIdRef.current = hashId;

    const root = articleRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    let observer: IntersectionObserver | undefined;
    let observedSignature = "";

    const connect = () => {
      const observed = Array.from(
        root.querySelectorAll<HTMLElement>("[data-manual-heading='true']"),
      );
      const signature = observed.map((heading) => heading.id).join("|");
      if (!observed.length || signature === observedSignature) return;
      observer?.disconnect();
      observedSignature = signature;
      observer = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
          const first = visible[0]?.target;
          if (first instanceof HTMLElement && !pendingHeadingIdRef.current) {
            setActiveId(first.id);
          }
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

  useEffect(() => {
    if (state !== "ready" || !pendingHeadingIdRef.current) return;
    let frame = 0;
    let releaseTimer = 0;
    let attempts = 0;
    const scrollToPendingHeading = () => {
      const target = document.getElementById(pendingHeadingIdRef.current);
      if (!target && attempts < 12) {
        attempts += 1;
        frame = window.requestAnimationFrame(scrollToPendingHeading);
        return;
      }
      if (!target) return;
      target.scrollIntoView({ behavior: "auto", block: "start" });
      releaseTimer = window.setTimeout(() => {
        pendingHeadingIdRef.current = "";
      }, 650);
    };
    frame = window.requestAnimationFrame(scrollToPendingHeading);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(releaseTimer);
    };
  }, [activeChapterIndex, activeChapterSource, state]);

  const navigateToHeading = (heading: ManualHeading) => {
    pendingHeadingIdRef.current = heading.id;
    setActiveChapterIndex(heading.majorIndex);
    setActiveId(heading.id);
    window.history.replaceState(null, "", `#${heading.id}`);
    if (heading.majorIndex === activeChapterIndex) {
      window.requestAnimationFrame(() => {
        document.getElementById(heading.id)?.scrollIntoView({
          behavior: "auto",
          block: "start",
        });
        window.setTimeout(() => {
          pendingHeadingIdRef.current = "";
        }, 650);
      });
    }
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
    <div className={`site-portal site-manual-page${sidebarOpen ? "" : " is-sidebar-collapsed"}`}>
      <aside className="manual-sidebar" aria-label={copy.ariaLabel}>
        <header className="manual-sidebar-title">
          <strong>{copy.contents}</strong>
          <button
            type="button"
            className="manual-sidebar-toggle"
            aria-label={sidebarOpen ? copy.hideContents : copy.showContents}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((current) => !current)}
          >
            {sidebarOpen ? <PanelLeftClose aria-hidden="true" /> : <PanelLeftOpen aria-hidden="true" />}
          </button>
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
            <button type="button" aria-disabled="true">
              <FileText aria-hidden="true" />
              {copy.markdown}
            </button>
            <button type="button" aria-disabled="true">
              <FileDown aria-hidden="true" />
              {copy.pdf}
            </button>
          </div>
        </div>

        <nav aria-label={copy.contents}>
          {navigationChapters.map((item, itemIndex) => {
            if (item.kind === "group") {
              const expanded = Boolean(query) || expandedChapterIds.has(item.id);
              const groupPanelId = `${item.id}-steps`;
              const groupContainsActive = item.chapters.some((chapter) =>
                activeId === chapter.heading.id
                || chapter.subsections.some((heading) => heading.id === activeId)
              );
              return (
                <div
                  key={item.id}
                  className={`manual-nav-chapter is-step-group${groupContainsActive ? " contains-active" : ""}`}
                >
                  <button
                    type="button"
                    className="manual-nav-group-row"
                    aria-expanded={expanded}
                    aria-controls={groupPanelId}
                    aria-label={`${expanded ? copy.collapseChapter : copy.expandChapter}: ${item.label}`}
                    onClick={() => toggleChapter(item.id)}
                  >
                    <span aria-hidden="true">{String(itemIndex + 1).padStart(2, "0")}</span>
                    <strong>{item.label}</strong>
                    <ChevronRight aria-hidden="true" />
                  </button>
                  <div
                    id={groupPanelId}
                    className="manual-nav-step-list"
                    hidden={!expanded}
                  >
                    {item.chapters.map((chapter) => {
                      const stepExpanded = Boolean(query)
                        || expandedChapterIds.has(chapter.heading.id);
                      const stepPanelId = `${chapter.heading.id}-subsections`;
                      return (
                        <div className="manual-nav-step" key={chapter.heading.id}>
                          <div className="manual-nav-step-row">
                            <a
                              href={`#${chapter.heading.id}`}
                              className={activeId === chapter.heading.id ? "is-active" : ""}
                              aria-current={activeId === chapter.heading.id ? "location" : undefined}
                              onClick={(event) => {
                                event.preventDefault();
                                navigateToHeading(chapter.heading);
                              }}
                            >
                              <strong>{manualNavigationLabel(chapter.heading, locale)}</strong>
                            </a>
                            {chapter.subsections.length ? (
                              <button
                                type="button"
                                className="manual-nav-toggle"
                                aria-expanded={stepExpanded}
                                aria-controls={stepPanelId}
                                aria-label={`${stepExpanded ? copy.collapseChapter : copy.expandChapter}: ${manualNavigationLabel(chapter.heading, locale)}`}
                                onClick={() => toggleChapter(chapter.heading.id)}
                              >
                                <ChevronRight aria-hidden="true" />
                              </button>
                            ) : null}
                          </div>
                          {chapter.subsections.length ? (
                            <div
                              id={stepPanelId}
                              className="manual-nav-subsections is-tertiary"
                              hidden={!stepExpanded}
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
                                  <strong>{manualNavigationLabel(heading, locale)}</strong>
                                </a>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            }

            const chapter = item;
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
                      {String(itemIndex + 1).padStart(2, "0")}
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
              {copy.online}
            </p>
            <h1 id="manual-reader-title">{copy.title}</h1>
          </div>
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
              <FileText aria-hidden="true" />
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
              <div className="manual-chapter-view">
                <ManualDocument
                  source={activeChapterSource}
                  headings={activeChapterHeadings}
                />
                <nav className="manual-chapter-pager" aria-label={copy.chapterNavigation}>
                  <button
                    type="button"
                    disabled={!previousChapter}
                    onClick={() => previousChapter && navigateToHeading(previousChapter)}
                  >
                    <ChevronLeft aria-hidden="true" />
                    <span>
                      <small>{copy.previousChapter}</small>
                      <strong>
                        {previousChapter
                          ? manualNavigationLabel(previousChapter, locale)
                          : copy.beginning}
                      </strong>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="is-next"
                    disabled={!nextChapter}
                    onClick={() => nextChapter && navigateToHeading(nextChapter)}
                  >
                    <span>
                      <small>{copy.nextChapter}</small>
                      <strong>
                        {nextChapter
                          ? manualNavigationLabel(nextChapter, locale)
                          : copy.ending}
                      </strong>
                    </span>
                    <ChevronRight aria-hidden="true" />
                  </button>
                </nav>
              </div>
            </Suspense>
          ) : null}
        </article>
      </section>
    </div>
  );
}
