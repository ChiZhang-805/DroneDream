import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    vi.stubGlobal("scrollTo", vi.fn());
  });

  it("renders a direct, versioned Windows download and the primary product sections", async () => {
    const { container } = renderSite();

    expect(document.title).toBe("DroneDream");
    expect(screen.getByRole("heading", { name: /Tune with evidence/i })).toBeVisible();
    expect(screen.getByText("WINDOWS PREVIEW")).toBeVisible();
    expect(screen.queryByText("WINDOWS RELEASE")).toBeNull();
    expect(screen.getByText(/This preview candidate is not Authenticode-signed/i)).toBeVisible();
    expect(screen.getByText(/Verify its SHA-256 before installation/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "Download Windows preview" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Download" })).toBeVisible();
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
      /Agentic PX4\/Gazebo parameter optimization · Windows 1\.0\.0\./i,
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

  it("keeps static downloads available while HTTP-mirror sensitive entries are disabled", () => {
    render(
      <I18nProvider>
        <SiteApp sensitiveCloudActionsEnabled={false} />
      </I18nProvider>,
    );

    expect(screen.getByRole("button", { name: "Console" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Login" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Download Windows preview" }))
      .toHaveAttribute("href", fallbackRelease.downloadUrl);
    expect(screen.getByRole("link", { name: "Download" }))
      .toHaveAttribute("href", fallbackRelease.downloadUrl);
  });

  it("renders a read-only account route on the HTTP mirror without credential fields", () => {
    window.history.replaceState(
      null,
      "",
      "/account/?source=website&mode=sign-in&returnTo=%2F",
    );

    render(
      <I18nProvider>
        <SiteApp sensitiveCloudActionsEnabled={false} />
      </I18nProvider>,
    );

    expect(document.querySelector('[data-auth-source="website"]')).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "This HTTP mirror is read-only; secure account and console actions are disabled.",
    );
    expect(screen.queryByLabelText("Email address")).toBeNull();
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(document.querySelector(".site-auth-form")).toBeNull();
    expect(screen.getByRole("link", { name: "Download" }))
      .toHaveAttribute("href", fallbackRelease.downloadUrl);
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

  it("renders the complete manual as native website content with downloadable editions", async () => {
    window.history.replaceState(null, "", "/manual/");
    const englishManual = `---
title: "DroneDream 1.0.0 User Manual"
---
# About this manual

DroneDream turns a bounded PX4 tuning study into reviewable evidence.

The manual explains where each control lives and which validation gate owns it.

> **Scope.** The result remains simulation evidence.

## How to read the field references

Each reference explains purpose, selection, default, and validation.

![Tuning Chat interface](manual-assets/en/tuning-chat.png)

| Field | Purpose |
| --- | --- |
| Vehicle | Selects the PX4 vehicle family. |

# 1. Installation and first launch

Complete the readiness gate before entering the tuning platform.

## 2.2 Account, cloud data, and local drafts

Account records and local drafts follow different storage boundaries.

# 4. Step 1 — Flight Setup

## 4.1 Vehicle

# 5. Step 2 — Parameters

## 5.1 Parameter families

# 6. Step 3 — Scenarios

## 6.1 Holdout cases

# 7. Step 4 — Constraints & Budget

## 7.1 Trial budget

# 8. Step 5 — Review

## 8.1 Final validation
`;
    const chineseManual = `---
title: "DroneDream 1.0.0 用户说明书"
---
# 关于本说明书

本说明书把完整的字段解释、软件截图和校验边界直接排成网站原生正文。

## 字段说明的阅读方式

每一项都会解释作用、选择方式、默认值和校验规则。
`;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("DroneDream-Manual-en.md")) {
        return {
          ok: true,
          text: async () => englishManual,
        } as Response;
      }
      if (url.endsWith("DroneDream-Manual-zh-CN.md")) {
        return {
          ok: true,
          text: async () => chineseManual,
        } as Response;
      }
      throw new Error("offline test");
    });

    const { container } = renderSite();

    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "DroneDream 1.0.0 User Manual" })).toBeVisible();
    const manualContents = screen.getByRole("complementary", {
      name: "DroneDream manual contents",
    });
    expect(manualContents).toBeVisible();
    expect(within(manualContents).queryByText("English edition")).toBeNull();
    expect(await screen.findByRole("heading", { name: "About this manual" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "How to read the field references" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Tuning Chat interface" })).toHaveAttribute(
      "src",
      "/docs/downloads/manual-assets/en/tuning-chat.png",
    );
    expect(screen.getByRole("table")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "PDF" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute(
      "href",
      "/docs/downloads/DroneDream-Manual-en.pdf",
    );
    expect(screen.getByRole("link", { name: "Markdown" })).toHaveAttribute(
      "href",
      "/docs/downloads/DroneDream-Manual-en.md",
    );
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector(".site-footer")).toBeNull();
    expect(screen.queryByText(/complete field-by-field guide/i)).toBeNull();
    expect(container.querySelectorAll(".manual-markdown > h1:first-child + p")).toHaveLength(1);
    expect(container.querySelector(".manual-markdown > h1:first-child + p")).toHaveTextContent(
      /reviewable evidence\. The manual explains/u,
    );

    const firstChapterToggle = within(manualContents).getByRole("button", {
      name: "Expand chapter: About this manual",
    });
    const secondChapterToggle = within(manualContents).getByRole("button", {
      name: "Expand chapter: Installation and first launch",
    });
    const workflowToggle = within(manualContents).getByRole("button", {
      name: "Expand chapter: Five-step workflow",
    });
    expect(firstChapterToggle).toHaveAttribute("aria-expanded", "false");
    expect(secondChapterToggle).toHaveAttribute("aria-expanded", "false");
    expect(workflowToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(manualContents).queryByText("1. Installation and first launch")).toBeNull();
    expect(within(manualContents).queryByRole("link", {
      name: "How to read the field references",
    })).toBeNull();

    fireEvent.click(firstChapterToggle);
    expect(firstChapterToggle).toHaveAttribute("aria-expanded", "true");
    expect(secondChapterToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(manualContents).getByRole("link", {
      name: "How to read the field references",
    })).toBeVisible();

    fireEvent.click(secondChapterToggle);
    expect(firstChapterToggle).toHaveAttribute("aria-expanded", "true");
    expect(secondChapterToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(manualContents).getByRole("link", {
      name: "Accounts and data",
    })).toBeVisible();
    expect(within(manualContents).queryByText(
      "2.2 Account, cloud data, and local drafts",
    )).toBeNull();

    fireEvent.click(workflowToggle);
    expect(workflowToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(manualContents).getByRole("link", {
      name: "Step 1 — Flight Setup",
    })).toBeVisible();
    expect(within(manualContents).queryByText("4. Step 1 — Flight Setup")).toBeNull();

    fireEvent.click(firstChapterToggle);
    expect(firstChapterToggle).toHaveAttribute("aria-expanded", "false");
    expect(secondChapterToggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("button", { name: "Switch to Simplified Chinese" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "关于本说明书" })).toBeVisible();
    });
    expect(screen.getByRole("complementary", { name: "DroneDream 说明书目录" })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      "/docs/downloads/DroneDream-Manual-zh-CN.md",
      expect.objectContaining({ cache: "force-cache" }),
    );
  });

  it.each([
    ["/pricing/", undefined],
    ["/community/", "recent"],
    ["/community/?view=all", "all"],
  ])("keeps the homepage footer off the standalone route %s", (route, communityView) => {
    window.history.replaceState(null, "", route);
    const { container } = renderSite();

    expect(container.querySelector(".site-footer")).toBeNull();
    const site = container.querySelector(".dd-site");
    if (communityView) {
      expect(site).toHaveAttribute("data-community-view", communityView);
    }
  });

  it("renders three directly comparable plans with the same ordered feature rows", async () => {
    window.history.replaceState(null, "", "/pricing/");

    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: "Choose the optimization depth for every flight." })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Free" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Plus" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Pro" })).toBeVisible();
    const individualTab = screen.getByRole("tab", { name: "Individual" });
    const businessTab = screen.getByRole("tab", { name: "Business" });
    expect(individualTab).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(individualTab).toHaveAttribute("tabindex", "0");
    expect(businessTab).toHaveAttribute("tabindex", "-1");
    individualTab.focus();
    fireEvent.keyDown(individualTab, { key: "ArrowRight" });
    expect(businessTab).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(businessTab).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveAttribute(
      "aria-labelledby",
      "pricing-audience-business",
    );
    fireEvent.keyDown(businessTab, { key: "Home" });
    expect(individualTab).toHaveAttribute("aria-selected", "true");
    expect(individualTab).toHaveFocus();
    fireEvent.keyDown(individualTab, { key: "End" });
    expect(businessTab).toHaveAttribute("aria-selected", "true");
    expect(businessTab).toHaveFocus();
    expect(screen.getByText(/300,000 managed AI credits/i)).toBeVisible();
    expect(screen.getByText(/3,000,000 managed AI credits/i)).toBeVisible();
    expect(screen.getByText(/15,000,000 managed AI credits/i)).toBeVisible();
    expect(screen.getAllByText(
      "Core AURORA optimization Harness",
    )).toHaveLength(3);
    const expectedFeatureOrder = [
      "workflow",
      "harness",
      "allowance",
      "byok",
      "reports",
      "comparisonWorkspace",
      "watermarkFree",
      "premiumRouting",
      "advancedHarness",
    ];
    container.querySelectorAll<HTMLElement>(".pricing-card").forEach((card) => {
      expect(
        Array.from(card.querySelectorAll<HTMLElement>("[data-feature]")).map(
          (feature) => feature.dataset.feature,
        ),
      ).toEqual(expectedFeatureOrder);
    });
    expect(
      container.querySelector('[data-plan="free"] [data-feature="watermarkFree"]'),
    ).toHaveAttribute("data-available", "false");
    expect(
      container.querySelector('[data-plan="plus"] [data-feature="watermarkFree"]'),
    ).toHaveAttribute("data-available", "true");
    expect(
      container.querySelector('[data-plan="pro"] [data-feature="watermarkFree"]'),
    ).toHaveAttribute("data-available", "true");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/billing-checkout/availability"),
        expect.any(Object),
      );
    });
  });

  it("shows honest inactive payment options without simulating a purchase", async () => {
    const { container } = render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Choose Plus" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: "Payment" })).toBeVisible();
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Close payment dialog" }),
    ).toHaveFocus());
    const enabledDialogButtons = within(
      screen.getByRole("dialog", { name: "Payment" }),
    ).getAllByRole("button").filter((button) => !button.hasAttribute("disabled"));
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(enabledDialogButtons.at(-1)).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Close payment dialog" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "WeChat Pay" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      container.querySelector('[data-brand-mark="wechat-pay"]'),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Alipay" })).toBeVisible();
    expect(
      container.querySelector('[data-brand-mark="alipay"]'),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Payment methods are temporarily unavailable.",
    );
    expect(screen.getByRole("button", { name: "WeChat Pay" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Alipay" })).toBeDisabled();
    await waitFor(() => {
      expect(screen.queryByText(/Merchant payment activation/i)).toBeNull();
    });
    expect(screen.queryByText(/Review the selected plan/i)).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Payment" })).toBeNull();
      expect(trigger).toHaveFocus();
      expect(document.body.style.overflow).toBe("");
    });
  });

  it("routes a community visitor to the website account page without opening a dialog", () => {
    window.history.replaceState(null, "", "/community/");

    renderSite();

    expect(screen.getByRole("heading", { name: "Share questions. Compare flight evidence." })).toBeVisible();
    const trigger = screen.getByRole("button", { name: "Sign in to publish" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(window.location.pathname).toBe("/account/");
    expect(new URLSearchParams(window.location.search).get("source")).toBe("website");
    expect(new URLSearchParams(window.location.search).get("returnTo"))
      .toBe("/community/");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
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
    expect(screen.getByText("WINDOWS 预览版")).toBeVisible();
    expect(screen.queryByText("WINDOWS 正式版")).toBeNull();
    expect(screen.getByText(/当前为未签名的预览候选版本/)).toBeVisible();
    expect(screen.getByText(/Windows 可能显示“未知发布者”警告/)).toBeVisible();
    expect(screen.getByText(/请务必确认下载文件与本页记录一致后再安装/)).toBeVisible();
    expect(screen.getByRole("link", { name: "下载 Windows 预览版" })).toBeVisible();
    expect(screen.getByRole("link", { name: "下载" })).toBeVisible();
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
      sha256: "9f44f79821dd27b283afcc57b3d4d194341a6cef655ce309c3609d1c834b3b8b",
      sizeBytes: 10_387_042,
      publishedAt: "2026-07-29",
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
