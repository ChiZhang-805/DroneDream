import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { isDesktopRuntime } from "./bridge";

type Command = "back" | "forward" | "sidebar" | "settings";
type Actions = Partial<Record<Command, () => void>>;
type Entry = { index: number; url: string | null; sameDocument: boolean };
type NavigationHistory = { currentEntry: Entry | null; entries(): Entry[] };

export function captionHistory(nav = (window as Window & { navigation?: NavigationHistory }).navigation) {
  const entries = nav?.entries() ?? [];
  const current = nav?.currentEntry;
  function withinWorkspace(offset: number) {
    if (!current) return false;
    const entry = entries.find(item => item.index === current.index + offset);
    if (!entry?.sameDocument || !entry.url) return false;
    const target = new URL(entry.url);
    return target.origin === window.location.origin && target.hash.startsWith("#/") &&
      !target.hash.startsWith("#/desktop/setup");
  }
  return { back: withinWorkspace(-1), forward: withinWorkspace(1) };
}

export function useCaptionMenu(active: boolean, locale: string, actions: Actions, sidebarHidden = false) {
  const current = useRef(actions);
  useLayoutEffect(() => { current.current = actions; }, [actions]);
  const canBack = !!actions.back, canForward = !!actions.forward;
  const canSidebar = !!actions.sidebar, canSettings = !!actions.settings;
  const enabled = active && isDesktopRuntime();
  useEffect(() => {
    if (!enabled) return;
    void window.__TAURI__?.core?.invoke("configure_caption_menu", { state: {
      chinese: locale === "zh-CN", canBack, canForward, canSidebar, canSettings, sidebarHidden,
    } }).catch(console.warn);
  }, [enabled, locale, canBack, canForward, canSidebar, canSettings, sidebarHidden]);
  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let remove: (() => void) | undefined;
    void window.__TAURI__?.event?.listen<Command>("caption-action", ({ payload }) => {
      if (!disposed && !document.querySelector('[aria-modal="true"]')) current.current[payload]?.();
    }).then(unlisten => { if (disposed) unlisten(); else remove = unlisten; }).catch(console.warn);
    const mnemonics: Record<string, string> = { f: "file", e: "edit", v: "view", h: "help" };
    function onKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.shiftKey || document.querySelector('[aria-modal="true"]')) return;
      const menu = event.key === "F10" ? "file" : event.altKey ? mnemonics[event.key.toLowerCase()] : undefined;
      if (!menu) return;
      event.preventDefault();
      void window.__TAURI__?.core?.invoke("focus_caption_menu", { mnemonic: menu }).catch(console.warn);
    }
    window.addEventListener("keydown", onKey);
    return () => { disposed = true; remove?.(); window.removeEventListener("keydown", onKey); };
  }, [enabled]);
}

export function usePageHistory<T>(initial: T) {
  const [history, setHistory] = useState({ pages: [initial], index: 0 });
  const select = useCallback((page: T) => setHistory(old => old.pages[old.index] === page ? old : {
    pages: [...old.pages.slice(0, old.index + 1), page], index: old.index + 1,
  }), []);
  const move = (by: number) => setHistory(old => ({
    ...old, index: Math.max(0, Math.min(old.pages.length - 1, old.index + by)),
  }));
  return { page: history.pages[history.index], select,
    back: history.index > 0 ? () => move(-1) : undefined,
    forward: history.index + 1 < history.pages.length ? () => move(1) : undefined,
  };
}
