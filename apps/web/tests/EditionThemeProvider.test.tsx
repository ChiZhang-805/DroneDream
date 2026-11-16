import { act, cleanup, render, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BrandEditionId } from "../src/brand/edition-brand.generated";
import { EditionThemeProvider, useEditionTheme } from "../src/theme/EditionThemeProvider";

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

  it("keeps the native caption and workspace on the same edition under a dark OS", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const view = render(<EditionThemeProvider edition="universal">{null}</EditionThemeProvider>);
    for (const edition of editions) {
      view.rerender(<EditionThemeProvider edition={edition}>{null}</EditionThemeProvider>);
      await waitFor(() => expect(invoke).toHaveBeenLastCalledWith("set_edition_caption", { edition }));
      expect(document.documentElement.dataset.brandEdition).toBe(edition);
      expect(document.documentElement).toHaveAttribute("data-desktop-frame");
      expect(document.documentElement.style.colorScheme).toBe("light");
    }
  });
});
