/** Device appearance must remain usable even when browser persistence is denied. */
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appReducedMotionEnabled, setAppReducedMotionEnabled } from "../desktop/uiMotionPreferences";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { loadUniversalMode, persistUniversalMode } from "../features/distribution/universalMode";
import { EditionThemeProvider, useEditionTheme } from "../theme/EditionThemeProvider";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAppReducedMotionEnabled(false);
});

describe("motion preferences", () => {
  it("survives a denied localStorage property getter in workspace mode helpers", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(loadUniversalMode()).toBe("universal");
    expect(() => persistUniversalMode("sim")).not.toThrow();
  });

  it("keeps theme controls usable with no persistent storage", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    const { result } = renderHook(() => useEditionTheme(), {
      wrapper: ({ children }) => <EditionThemeProvider edition="sim">{children}</EditionThemeProvider>,
    });
    expect(result.current.appearancePreference).toBe("dark");
    act(() => result.current.setAppearance("light"));
    expect(result.current.appearancePreference).toBe("light");
    act(() => result.current.setCustomAccent("#AABBCC"));
    expect(result.current.customAccent).toBe("#aabbcc");
  });
  it("keeps a denied storage read from crashing the UI", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(() => appReducedMotionEnabled()).not.toThrow();
  });

  it("applies a session preference even when persistence fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    expect(() => setAppReducedMotionEnabled(true)).not.toThrow();
    expect(appReducedMotionEnabled()).toBe(true);
  });

  it("updates JS-driven animation when the in-app preference changes", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    } as unknown as MediaQueryList));
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
    act(() => setAppReducedMotionEnabled(true));
    expect(result.current).toBe(true);
    act(() => setAppReducedMotionEnabled(false));
    expect(result.current).toBe(false);
  });
});
