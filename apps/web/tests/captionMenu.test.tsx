import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { captionHistory, useCaptionMenu, usePageHistory } from "../src/desktop/captionMenu";

afterEach(() => vi.unstubAllGlobals());

describe("desktop caption commands", () => {
  it("only enables adjacent workspace entries in the same document", () => {
    const entries = [
      { index: 0, url: window.location.origin + "/#/desktop/setup", sameDocument: true },
      { index: 1, url: window.location.origin + "/#/assistant", sameDocument: true },
      { index: 2, url: window.location.origin + "/#/history", sameDocument: true },
    ];
    const nav = { currentEntry: entries[1], entries: () => entries };
    expect(captionHistory(nav)).toEqual({ back: false, forward: true });
    nav.currentEntry = entries[2];
    expect(captionHistory(nav)).toEqual({ back: true, forward: false });
    entries[1].sameDocument = false;
    expect(captionHistory(nav).back).toBe(false);
  });

  it("discards forward FIELD pages after navigating down another branch", () => {
    const { result } = renderHook(() => usePageHistory("assistant"));
    act(() => result.current.select("device"));
    act(() => result.current.select("tuning"));
    act(() => result.current.back?.());
    expect(result.current.page).toBe("device");
    expect(result.current.forward).toBeDefined();
    act(() => result.current.select("recovery"));
    expect(result.current.forward).toBeUndefined();
    act(() => result.current.back?.());
    expect(result.current.page).toBe("device");
  });

  it("delivers native actions, reports the locale and supports keyboard menus", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const remove = vi.fn();
    let listener: ((event: { payload: string }) => void) | undefined;
    const listen = vi.fn((_name, callback) => { listener = callback; return Promise.resolve(remove); });
    vi.stubGlobal("__TAURI__", { core: { invoke }, event: { listen } });
    const sidebar = vi.fn();
    const { rerender, unmount } = renderHook(({ locale }) => useCaptionMenu(true, locale, { sidebar }), { initialProps: { locale: "en" } });
    await waitFor(() => expect(listen).toHaveBeenCalledOnce());
    expect(invoke).toHaveBeenCalledWith("configure_caption_menu", { state: {
      chinese: false, canBack: false, canForward: false, canSidebar: true, canSettings: false, sidebarHidden: false,
    } });
    act(() => listener?.({ payload: "sidebar" }));
    expect(sidebar).toHaveBeenCalledOnce();
    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { altKey: true, key: "e" })));
    expect(invoke).toHaveBeenCalledWith("focus_caption_menu", { mnemonic: "edit" });
    rerender({ locale: "zh-CN" });
    expect(invoke).toHaveBeenCalledWith("configure_caption_menu", { state: expect.objectContaining({ chinese: true }) });
    unmount();
    expect(remove).toHaveBeenCalledOnce();
  });
});
