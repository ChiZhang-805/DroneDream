import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileDown,
  FileText,
  Languages,
  LoaderCircle,
  Network,
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
import ManualArchitecture from "./ManualArchitecture";
import {
  getArchitectureSections,
  type ArchitectureSectionId,
} from "./manualArchitectureData";

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
    architectureContents: "Core architecture",
    architectureOnline: "CORE ARCHITECTURE",
    architectureTitle: "How DroneDream sees the world",
    openArchitecture: "Open core architecture",
    openManual: "Return to manual",
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
    architectureContents: "核心架构",
    architectureOnline: "核心架构",
    architectureTitle: "DroneDream 如何理解世界",
    openArchitecture: "打开核心架构",
    openManual: "返回说明书",
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
  const [manualView, setManualView] = useState<"manual" | "architecture">("manual");
  const [architectureSection, setArchitectureSection] = useState<ArchitectureSectionId>("map");
  const [architectureActiveId, setArchitectureActiveId] = useState("architecture-map-title");
  const [expandedArchitectureIds, setExpandedArchitectureIds] = useState<Set<ArchitectureSectionId>>(
    () => new Set(["map", "drone", "model"]),
  );
  const articleRef = useRef<HTMLElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
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
    if (manualView !== "manual") return;
    if (!headings.length) return;
    const hashId = decodeURIComponent(window.location.hash.replace(/^#/u, ""));
    const initialHeading = headings.find((heading) => heading.id === hashId) ?? headings[0];
    setActiveId((current) => current || initialHeading.id);
    setActiveChapterIndex(initialHeading.majorIndex);
    if (hashId && initialHeading.id === hashId) pendingHeadingIdRef.current = hashId;

    const root = articleRef.current;
    if (!root) return;
    let frame = 0;

    const updateActiveHeading = () => {
      frame = 0;
      if (pendingHeadingIdRef.current) return;
      const observed = Array.from(
        root.querySelectorAll<HTMLElement>("[data-manual-heading='true']"),
      );
      if (!observed.length) return;

      const headerHeight = document.querySelector<HTMLElement>(".site-header")?.offsetHeight ?? 78;
      const readingLine = headerHeight + 56;
      let currentHeading = observed[0];
      for (const heading of observed) {
        if (heading.getBoundingClientRect().top <= readingLine) currentHeading = heading;
        else break;
      }

      setActiveId((current) => {
        if (current === currentHeading.id) return current;
        window.history.replaceState(null, "", `#${currentHeading.id}`);
        return currentHeading.id;
      });
    };

    const scheduleUpdate = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(updateActiveHeading);
    };

    scheduleUpdate();
    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    const mutationObserver = new MutationObserver(scheduleUpdate);
    mutationObserver.observe(root, { childList: true, subtree: true });

    return () => {
      window.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
      window.cancelAnimationFrame(frame);
      mutationObserver.disconnect();
    };
  }, [activeChapterIndex, headings, manualView, state]);

  useEffect(() => {
    if (manualView !== "manual") return;
    if (state !== "ready" || !pendingHeadingIdRef.current) return;
    const root = articleRef.current;
    if (!root) return;
    let frame = 0;
    let releaseTimer = 0;
    let contentObserver: MutationObserver | null = null;
    let resizeObserver: ResizeObserver | null = null;
    const finishPendingScroll = () => {
      pendingHeadingIdRef.current = "";
      contentObserver?.disconnect();
      resizeObserver?.disconnect();
    };
    const scrollToPendingHeading = () => {
      const target = document.getElementById(pendingHeadingIdRef.current);
      if (!target) return;
      target.scrollIntoView({ behavior: "auto", block: "start" });
      window.clearTimeout(releaseTimer);
      releaseTimer = window.setTimeout(finishPendingScroll, 700);
    };
    const scheduleScroll = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(scrollToPendingHeading);
    };
    contentObserver = new MutationObserver(scheduleScroll);
    contentObserver.observe(root, { childList: true, subtree: true });
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(scheduleScroll);
      resizeObserver.observe(root);
    }
    scheduleScroll();
    return () => {
      contentObserver?.disconnect();
      resizeObserver?.disconnect();
      window.cancelAnimationFrame(frame);
      window.clearTimeout(releaseTimer);
    };
  }, [activeChapterIndex, activeChapterSource, manualView, state]);

  useEffect(() => {
    if (!activeId || !sidebarOpen) return;
    const sidebar = sidebarRef.current;
    const activeLink = sidebar?.querySelector<HTMLElement>(
      'a[aria-current="location"]',
    );
    if (!sidebar || !activeLink) return;

    const sidebarBounds = sidebar.getBoundingClientRect();
    const activeBounds = activeLink.getBoundingClientRect();
    const topInset = 12;
    const bottomInset = 16;
    if (
      typeof activeLink.scrollIntoView === "function"
      && (
        activeBounds.top < sidebarBounds.top + topInset
        || activeBounds.bottom > sidebarBounds.bottom - bottomInset
      )
    ) {
      activeLink.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [activeId, sidebarOpen]);

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

  const architectureSections = getArchitectureSections(locale);
  const navigateToArchitecture = (sectionId: ArchitectureSectionId, anchorId: string) => {
    setArchitectureSection(sectionId);
    setArchitectureActiveId(anchorId);
    setExpandedArchitectureIds((current) => new Set(current).add(sectionId));
    window.history.replaceState(null, "", `#${anchorId}`);
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.getElementById(anchorId)?.scrollIntoView({ behavior: "auto", block: "start" });
      });
    });
  };
  const toggleArchitectureChapter = (sectionId: ArchitectureSectionId) => {
    setExpandedArchitectureIds((current) => {
      const next = new Set(current);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  };
  const switchManualView = () => {
    setSidebarOpen(true);
    setManualView((current) => {
      const next = current === "manual" ? "architecture" : "manual";
      if (next === "architecture") {
        setQuery("");
        setArchitectureActiveId(
          architectureSections.find((item) => item.id === architectureSection)?.anchorId
            ?? "architecture-map-title",
        );
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
      }
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      return next;
    });
  };

  return (
    <div className={`site-portal site-manual-page${sidebarOpen ? "" : " is-sidebar-collapsed"}${manualView === "architecture" ? " is-architecture-view" : ""}`}>
      <aside
        ref={sidebarRef}
        className="manual-sidebar"
        aria-label={manualView === "manual" ? copy.ariaLabel : copy.architectureContents}
      >
        <header className="manual-sidebar-title">
          <strong>{manualView === "manual" ? copy.contents : copy.architectureContents}</strong>
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

        {manualView === "manual" ? <>
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
        </> : (
          <nav className="manual-architecture-nav" aria-label={copy.architectureContents}>
            {architectureSections.map((section, index) => {
              const expanded = expandedArchitectureIds.has(section.id);
              const active = architectureSection === section.id;
              const panelId = `architecture-${section.id}-subsections`;
              return (
                <div
                  key={section.id}
                  className={`manual-nav-chapter${active ? " contains-active" : ""}`}
                >
                  <div className="manual-nav-chapter-row">
                    <a
                      href={`#${section.anchorId}`}
                      className={architectureActiveId === section.anchorId ? "is-active" : ""}
                      aria-current={architectureActiveId === section.anchorId ? "location" : undefined}
                      onClick={(event) => {
                        event.preventDefault();
                        navigateToArchitecture(section.id, section.anchorId);
                      }}
                    >
                      <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                      <strong>{section.label}</strong>
                    </a>
                    <button
                      type="button"
                      className="manual-nav-toggle"
                      aria-expanded={expanded}
                      aria-controls={panelId}
                      aria-label={`${expanded ? copy.collapseChapter : copy.expandChapter}: ${section.label}`}
                      onClick={() => toggleArchitectureChapter(section.id)}
                    >
                      <ChevronRight aria-hidden="true" />
                    </button>
                  </div>
                  <div id={panelId} className="manual-nav-subsections" hidden={!expanded}>
                    {section.subsections.map((subsection) => (
                      <a
                        key={subsection.id}
                        href={`#${subsection.id}`}
                        className={`is-subsection${architectureActiveId === subsection.id ? " is-active" : ""}`}
                        aria-current={architectureActiveId === subsection.id ? "location" : undefined}
                        onClick={(event) => {
                          event.preventDefault();
                          navigateToArchitecture(section.id, subsection.id);
                        }}
                      >
                        <strong>{subsection.label}</strong>
                      </a>
                    ))}
                  </div>
                </div>
              );
            })}
          </nav>
        )}

      </aside>

      <section className="manual-reader" aria-labelledby="manual-reader-title">
        <header className="manual-reader-header">
          <div>
            <p>
              <Languages aria-hidden="true" />
              {manualView === "manual" ? copy.online : copy.architectureOnline}
            </p>
            <h1 id="manual-reader-title">
              {manualView === "manual" ? copy.title : copy.architectureTitle}
            </h1>
          </div>
        </header>

        <article ref={articleRef} className="manual-reader-document">
          {manualView === "architecture" ? (
            <ManualArchitecture locale={locale} section={architectureSection} />
          ) : <>
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
          </>}
        </article>
      </section>

      <div className="manual-mode-switch">
        <button
          type="button"
          aria-label={manualView === "manual" ? copy.openArchitecture : copy.openManual}
          title={manualView === "manual" ? copy.openArchitecture : copy.openManual}
          onClick={switchManualView}
        >
          {manualView === "manual" ? <Network aria-hidden="true" /> : <BookOpen aria-hidden="true" />}
          <span>{manualView === "manual" ? copy.architectureContents : copy.contents}</span>
        </button>
      </div>
    </div>
  );
}
