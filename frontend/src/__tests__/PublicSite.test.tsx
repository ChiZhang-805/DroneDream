import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { PricingPage } from "../site/PricingPage";
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

function expectContentLinksToUseIcons(container: HTMLElement) {
  const contentLinks = Array.from(container.querySelectorAll<HTMLAnchorElement>("a[href]"))
    .filter((link) => !link.matches(".site-skip-link, .site-nav a"));
  contentLinks.forEach((link) => {
    expect(link.querySelector("svg, img"), `Expected an icon in ${link.className || link.href}`).not.toBeNull();
    expect(link).toHaveAccessibleName();
  });
}

describe("DroneDream public website", () => {
  afterEach(() => vi.unstubAllGlobals());

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline test")));
  });

  it("renders a direct, versioned Windows download and the primary product sections", async () => {
    const { container } = renderSite();

    expect(document.title).toBe("DroneDream");
    expect(screen.getByRole("heading", { name: /Tune with evidence/i })).toBeVisible();
    expect(screen.queryByText("LAB")).toBeNull();
    const starflightButton = screen.getByRole("button", { name: /begin a starflight/i });
    expect(starflightButton).not.toHaveTextContent("+");
    expect(container.querySelector(".site-starflight-icon")).not.toBeNull();
    expect(screen.queryByText(/Select the parameters that matter/i)).toBeNull();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    expect(screen.getByRole("heading", { name: /defensible result/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: /Tune in (?:three|3) steps/i })).toBeVisible();
    expect(screen.getByRole("figure", { name: /automated closed loop/i })).toBeVisible();
    expect(container.querySelectorAll(".site-workflow-visual animateMotion")).toHaveLength(2);
    expect(container.querySelectorAll(".site-workflow-step-icon")).toHaveLength(4);
    expect(container.querySelector(".site-workflow-steps")).not.toHaveTextContent("01");
    expect(container.querySelectorAll(".site-phase-description")).toHaveLength(3);
    container.querySelectorAll(".site-phase-description").forEach((description) => {
      expect(description.querySelectorAll(":scope > span")).toHaveLength(6);
    });
    expect(container.querySelectorAll(".site-release-card dl > div")).toHaveLength(4);
    expect(container.querySelector(".site-checksum")).toBeNull();
    expect(container.querySelector(".site-release-card details")).toBeNull();
    expect(container).not.toHaveTextContent("Copy checksum");
    expect(container).not.toHaveTextContent("Before installing");
    expect(container).not.toHaveTextContent("↗");
    expect(container.querySelectorAll(".site-manual-links svg")).toHaveLength(2);
    expect(container.querySelector(".site-footer a svg")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Code signing policy" })).toHaveAttribute(
      "href",
      "https://github.com/ChiZhang-805/DroneDream/blob/main/CODE_SIGNING_POLICY.md",
    );
    expect(screen.getByRole("link", { name: "Privacy policy" })).toHaveAttribute(
      "href",
      "https://github.com/ChiZhang-805/DroneDream/blob/main/PRIVACY.md",
    );
    expect(screen.getByText(
      /Version 1\.0\.0 is published while code signing is being prepared\./i,
    )).toBeVisible();
    expect(screen.getByRole("link", { name: "Product" })).toHaveAttribute("href", "/pricing/");
    expect(screen.getByRole("link", { name: "Workflow" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Manual" })).toHaveAttribute("href", "/manual/");
    expect(screen.getByRole("link", { name: "Community" })).toHaveAttribute("href", "/community/");
    expect(screen.getByRole("button", { name: "Console" })).toBeVisible();
    expectContentLinksToUseIcons(container);

    const downloads = screen.getAllByRole("link", { name: /Download/i });
    expect(downloads.some((link) => link.getAttribute("href") === fallbackRelease.downloadUrl)).toBe(true);
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Choose the next candidate" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Full manual" })).toHaveAttribute("href", "/manual/");
    expectContentLinksToUseIcons(container);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/downloads/latest.json",
      expect.objectContaining({ cache: "no-cache" }),
    ));
  });

  it("flips capability cards and browses their localized detail carousel", async () => {
    renderSite();

    const open = screen.getByRole("button", { name: "Open details for Selective tuning" });
    fireEvent.click(open);

    expect(screen.getAllByText("MPC_XY_P").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Next detail" }));
    expect(screen.getAllByText("MPC_XY_VEL_P_ACC").length).toBeGreaterThan(0);

    const back = screen.getByRole("button", { name: "Return to overview: Selective tuning" });
    fireEvent.click(back);
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("renders the full manual as a dedicated documentation page", () => {
    window.history.replaceState(null, "", "/manual/");

    renderSite();

    expect(screen.getByRole("heading", { name: "Build explainable tuning experiments." })).toBeVisible();
    expect(screen.getByRole("complementary", { name: "On this page" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Complete the five-step experiment" })).toBeVisible();
    expect(screen.queryByRole("dialog", { name: /manual/i })).toBeNull();
  });

  it("renders exactly three plans whose capabilities differ only by allowance", () => {
    window.history.replaceState(null, "", "/pricing/");

    renderSite();

    expect(screen.getByRole("heading", { name: "The same complete product. More included AI." })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Free" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Plus" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Pro" })).toBeVisible();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByText(/Business Plus/i)).toBeNull();
    expect(screen.getByText("100,000")).toBeVisible();
    expect(screen.getByText("1,000,000")).toBeVisible();
    expect(screen.getByText("5,000,000")).toBeVisible();
    expect(screen.getAllByText(
      "The same Harness, optimizers, simulation, and reports",
    )).toHaveLength(3);
  });

  it("shows honest inactive payment options without simulating a purchase", async () => {
    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose Plus" }));

    expect(screen.getByRole("dialog", { name: "Choose a payment method" })).toBeVisible();
    expect(screen.getByRole("button", { name: "WeChat Pay" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Alipay" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    expect(
      await screen.findByText("Merchant payment activation is still required."),
    ).toBeVisible();
  });

  it("requires an account before a visitor can publish a community topic", () => {
    window.history.replaceState(null, "", "/community/");

    renderSite();

    expect(screen.getByRole("heading", { name: "Share questions. Compare flight evidence." })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sign in to publish" }));
    expect(screen.getByRole("dialog", { name: "Sign in" })).toBeVisible();
  });

  it("switches the entire website to Simplified Chinese", () => {
    const { container } = renderSite();

    const workflowBefore = screen.getByRole("heading", { name: "Define" }).closest("li") as HTMLElement;
    const capabilityBefore = screen.getByRole("heading", { name: "Selective tuning" }).closest("article") as HTMLElement;
    const manualStepBefore = screen.getByRole("heading", { name: "Install the app" }).closest("li") as HTMLElement;
    expect(workflowBefore).toHaveClass("is-visible");
    expect(capabilityBefore).toHaveClass("is-visible");
    expect(manualStepBefore).toHaveClass("is-visible");

    fireEvent.click(screen.getByRole("button", { name: "Switch to Simplified Chinese" }));

    expect(document.documentElement).toHaveAttribute("lang", "zh-CN");
    expect(document.title).toBe("DroneDream");
    expect(screen.getByRole("button", { name: "切换到英文" })).toBeVisible();
    expect(screen.getByRole("heading", { name: /让调优有章法/ })).toBeVisible();
    expect(screen.getByRole("heading", { name: /让飞行更加从容/ })).toBeVisible();
    expect(screen.getByRole("heading", { name: "三步开始调优。" })).toBeVisible();
    expect(screen.getByRole("figure", { name: "从飞行任务到证据决策的自动闭环工作流" })).toBeVisible();
    expect(screen.queryByText("Product")).toBeNull();
    expect(screen.getByRole("heading", { name: "定义任务" }).closest("li")).toBe(workflowBefore);
    expect(screen.getByRole("heading", { name: "按需选择参数" }).closest("article")).toBe(capabilityBefore);
    expect(screen.getByRole("heading", { name: "安装桌面程序" }).closest("li")).toBe(manualStepBefore);
    expect(screen.getByRole("link", { name: "代码签名政策" })).toBeVisible();
    expect(screen.getByRole("link", { name: "隐私政策" })).toBeVisible();
    expect(workflowBefore).toHaveClass("is-visible");
    expect(capabilityBefore).toHaveClass("is-visible");
    expect(manualStepBefore).toHaveClass("is-visible");
    expect(container.querySelectorAll("[data-reveal]:not(.is-visible)")).toHaveLength(0);
    expectContentLinksToUseIcons(container);
  });

  it("continues rendering when an external URL contains a malformed hash", () => {
    window.history.replaceState(null, "", "/#%E0%A4%A");

    expect(() => renderSite()).not.toThrow();
    expect(screen.getByRole("heading", { name: /Tune with evidence/i })).toBeVisible();
  });

  it("removes the starflight control when the operating system requests reduced motion", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    renderSite();

    expect(screen.queryByRole("button", { name: /begin a starflight/i })).toBeNull();
    expect(document.querySelectorAll(".site-workflow-visual animateMotion")).toHaveLength(0);
  });

  it("validates release metadata and formats binary sizes", () => {
    expect(fallbackRelease).toMatchObject({
      version: "1.0.0",
      fileName: "DroneDream_1.0.0_x64-setup.exe",
      sha256: "c2018379a21fb72a7cf3c4a7f6381d3fa49cf54a03c167a196d950fd651225a4",
      sizeBytes: 6_605_457,
      publishedAt: "2026-07-25",
    });
    expect(isWebsiteRelease(fallbackRelease)).toBe(true);
    expect(isWebsiteRelease({ ...fallbackRelease, sha256: "unsafe" })).toBe(false);
    expect(isWebsiteRelease({ ...fallbackRelease, downloadUrl: "javascript:alert(1)" })).toBe(false);
    expect(isWebsiteRelease({
      ...fallbackRelease,
      downloadUrl: fallbackRelease.downloadUrl.replace("https://", "http://"),
    })).toBe(false);
    expect(isWebsiteRelease({
      ...fallbackRelease,
      downloadUrl: fallbackRelease.downloadUrl.replace("ChiZhang-805/DroneDream", "other/project"),
    })).toBe(false);
    expect(isWebsiteRelease({
      ...fallbackRelease,
      downloadUrl: `${fallbackRelease.downloadUrl}?unexpected=1`,
    })).toBe(false);
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
      version: "1.0.1",
      fileName: "DroneDream_1.0.1_x64-setup.exe",
      downloadUrl: "/downloads/DroneDream_1.0.1_x64-setup.exe",
      checksumUrl: "/downloads/DroneDream_1.0.1_x64-setup.exe.sha256",
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

  it("uses a valid GitHub Release manifest for every global download link", async () => {
    const nextRelease = {
      ...fallbackRelease,
      version: "1.0.1",
      fileName: "DroneDream_1.0.1_x64-setup.exe",
      downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/desktop-v1.0.1/DroneDream_1.0.1_x64-setup.exe",
      checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/desktop-v1.0.1/DroneDream_1.0.1_x64-setup.exe.sha256",
      sha256: "b".repeat(64),
      sizeBytes: 5_500_000,
      publishedAt: "2026-07-22",
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
