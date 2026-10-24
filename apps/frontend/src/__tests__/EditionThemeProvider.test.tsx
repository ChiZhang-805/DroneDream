import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { EditionThemeProvider, useEditionTheme } from "../theme/EditionThemeProvider";

const nativeWindow = vi.hoisted(() => ({ setTheme: vi.fn<(theme: string) => Promise<void>>(async () => undefined) }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => nativeWindow }));

const editions = ["universal", "sim", "lab", "field", "autonomy"] as const;

function renderTheme(edition: BrandEditionId) {
  return renderHook(() => useEditionTheme(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <EditionThemeProvider edition={edition}>{children}</EditionThemeProvider>
    ),
  });
}

beforeEach(() => {
  window.localStorage.clear();
  nativeWindow.setTheme.mockClear();
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
  delete window.__TAURI__;
});

describe("appearance at app launch", () => {
  it.each(editions)("starts %s in light mode even with saved dark and a dark OS", (edition) => {
    window.localStorage.setItem("dronedream:appearance", "dark");
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    const { result } = renderTheme(edition);

    expect(result.current.appearancePreference).toBe("light");
    expect(result.current.appearance).toBe("light");
    expect(document.documentElement.dataset.ddAppearance).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(window.localStorage.getItem("drone-dream:locale")).toBe("zh-CN");
    // Old preferences remain intact, but no longer control the launch theme.
    expect(window.localStorage.getItem("dronedream:appearance")).toBe("dark");
  });

  it.each(editions)("allows %s to switch this session, then resets on reopening", (edition) => {
    const first = renderTheme(edition);
    act(() => first.result.current.setAppearance("dark"));
    expect(first.result.current.appearancePreference).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(window.localStorage.getItem("dronedream:appearance")).toBeNull();
    first.rerender();
    expect(first.result.current.appearancePreference).toBe("dark");
    first.unmount();

    const reopened = renderTheme(edition);
    expect(reopened.result.current.appearancePreference).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("keeps the current session choice across rerenders and resets explicitly to light", () => {
    const { result, rerender } = renderHook(() => useEditionTheme(), {
      wrapper: ({ children }) => <EditionThemeProvider edition="universal">{children}</EditionThemeProvider>,
    });
    act(() => result.current.setAppearance("dark"));
    rerender();
    expect(result.current.appearancePreference).toBe("dark");
    act(() => result.current.resetAppearance());
    expect(result.current.appearancePreference).toBe("light");
  });

  it("provides a light fallback for consumers before a provider is mounted", () => {
    const { result } = renderHook(() => useEditionTheme());
    expect(result.current.appearance).toBe("light");
    expect(result.current.appearancePreference).toBe("light");
  });

  it("starts native window chrome in light mode and follows only this session's changes", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    const first = renderTheme("autonomy");
    await waitFor(() => expect(nativeWindow.setTheme).toHaveBeenLastCalledWith("light"));
    act(() => first.result.current.setAppearance("dark"));
    await waitFor(() => expect(nativeWindow.setTheme).toHaveBeenLastCalledWith("dark"));
    first.unmount();

    renderTheme("autonomy");
    await waitFor(() => expect(nativeWindow.setTheme).toHaveBeenLastCalledWith("light"));
    expect(nativeWindow.setTheme).toHaveBeenCalledTimes(3);
  });
});
