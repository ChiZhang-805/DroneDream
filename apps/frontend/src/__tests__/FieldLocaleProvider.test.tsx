import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FieldLocaleProvider, useFieldLocale } from "../field/FieldLocaleProvider";

function renderLocale() {
  return renderHook(() => useFieldLocale(), { wrapper: FieldLocaleProvider });
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("standalone FIELD language", () => {
  it("starts in English without inheriting the installer or OS language", () => {
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("zh-CN");
    const invoke = vi.fn(async () => "zh-CN");
    window.__TAURI__ = { core: { invoke } };
    const { result } = renderLocale();
    expect(result.current.locale).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(invoke).not.toHaveBeenCalled();
  });

  it.each(["en", "zh-CN"] as const)("keeps the user-selected %s after reopening", (locale) => {
    const first = renderLocale();
    act(() => first.result.current.setLocale(locale));
    first.unmount();
    const reopened = renderLocale();
    expect(reopened.result.current.locale).toBe(locale);
    expect(window.localStorage.getItem("dronedream:field:locale")).toBe(locale);
    expect(document.documentElement.lang).toBe(locale);
  });
});
