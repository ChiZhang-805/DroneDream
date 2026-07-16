import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { SiteApp } from "../site/SiteApp";
import {
  compareReleaseVersions,
  fallbackRelease,
  formatBinarySize,
  isWebsiteRelease,
} from "../site/release";

function renderSite() {
  return render(
    <I18nProvider>
      <SiteApp />
    </I18nProvider>,
  );
}

describe("DroneDream public website", () => {
  afterEach(() => vi.unstubAllGlobals());

  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline test")));
  });

  it("renders a direct, versioned Windows download and the primary product sections", async () => {
    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: /Tune with evidence/i })).toBeVisible();
    expect(screen.queryByText("LAB")).toBeNull();
    const starflightButton = screen.getByRole("button", { name: /begin a starflight/i });
    expect(starflightButton).not.toHaveTextContent("+");
    expect(container.querySelector(".site-starflight-icon")).not.toBeNull();
    expect(screen.queryByText(/Select the parameters that matter/i)).toBeNull();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    expect(screen.getByRole("heading", { name: /defensible result/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: /Three steps from download/i })).toBeVisible();

    const downloads = screen.getAllByRole("link", { name: /Download/i });
    expect(downloads.some((link) => link.getAttribute("href") === fallbackRelease.downloadUrl)).toBe(true);
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: "Read the full manual" }));
    expect(screen.getByRole("dialog", { name: /quick-start manual/i })).toBeVisible();
    expect(screen.getByText("4 · Create the first experiment")).toBeVisible();
    const closeManual = screen.getByRole("button", { name: "Close manual" });
    expect(closeManual).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeManual).toHaveFocus();
    fireEvent.click(closeManual);
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/downloads/latest.json",
      expect.objectContaining({ cache: "no-cache" }),
    ));
  });

  it("switches the entire website to Simplified Chinese", () => {
    renderSite();

    fireEvent.click(screen.getByRole("button", { name: "Switch to Simplified Chinese" }));

    expect(document.documentElement).toHaveAttribute("lang", "zh-CN");
    expect(document.title).toBe("DroneDream — 无人机控制参数自动调优");
    expect(screen.getByRole("button", { name: "切换到英文" })).toBeVisible();
    expect(screen.getByRole("heading", { name: /让调优有章法/ })).toBeVisible();
    expect(screen.getByRole("heading", { name: /让飞行更加从容/ })).toBeVisible();
    expect(screen.queryByText("Product")).toBeNull();
  });

  it("removes the starflight control when the operating system requests reduced motion", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    renderSite();

    expect(screen.queryByRole("button", { name: /begin a starflight/i })).toBeNull();
  });

  it("validates release metadata and formats binary sizes", () => {
    expect(fallbackRelease).toMatchObject({
      version: "0.3.18",
      fileName: "DroneDream_0.3.18_x64-setup.exe",
      sha256: "5ce2247421a6c82d884d656c9e55dde7b24144b70a66dbdf71bb6d7197923a4e",
      sizeBytes: 5_363_093,
      publishedAt: "2026-07-15",
    });
    expect(isWebsiteRelease(fallbackRelease)).toBe(true);
    expect(isWebsiteRelease({ ...fallbackRelease, sha256: "unsafe" })).toBe(false);
    expect(isWebsiteRelease({ ...fallbackRelease, downloadUrl: "javascript:alert(1)" })).toBe(false);
    expect(isWebsiteRelease({ ...fallbackRelease, version: "0.3.12" })).toBe(false);
    expect(isWebsiteRelease({ ...fallbackRelease, publishedAt: "2026-99-99" })).toBe(false);
    expect(compareReleaseVersions("0.3.18", "0.3.18")).toBe(0);
    expect(compareReleaseVersions("0.4.0", "0.3.18")).toBe(1);
    expect(compareReleaseVersions("0.3.17", "0.3.18")).toBe(-1);
    expect(formatBinarySize(5_349_031)).toBe("5.10 MiB");
    expect(formatBinarySize(Number.NaN)).toBe("—");
    expect(formatBinarySize(0)).toBe("—");
  });

  it("uses a valid same-origin non-downgrade release manifest for every download link", async () => {
    const nextRelease = {
      ...fallbackRelease,
      version: "0.3.19",
      fileName: "DroneDream_0.3.19_x64-setup.exe",
      downloadUrl: "/downloads/DroneDream_0.3.19_x64-setup.exe",
      checksumUrl: "/downloads/DroneDream_0.3.19_x64-setup.exe.sha256",
      sha256: "a".repeat(64),
      sizeBytes: 5_400_000,
      publishedAt: "2026-07-16",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => nextRelease,
    }));

    renderSite();

    await waitFor(() => expect(
      screen.getAllByRole("link", { name: /Download/i })
        .some((link) => link.getAttribute("href") === nextRelease.downloadUrl),
    ).toBe(true));
  });

  it("does not replace the embedded release with stale metadata", async () => {
    const staleRelease = {
      ...fallbackRelease,
      version: "0.3.17",
      fileName: "DroneDream_0.3.17_x64-setup.exe",
      downloadUrl: "/downloads/DroneDream_0.3.17_x64-setup.exe",
      checksumUrl: "/downloads/DroneDream_0.3.17_x64-setup.exe.sha256",
      publishedAt: "2026-07-14",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => staleRelease,
    }));

    renderSite();

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.getAllByRole("link", { name: /Download/i })
      .every((link) => link.getAttribute("href") !== staleRelease.downloadUrl)).toBe(true);
  });
});
