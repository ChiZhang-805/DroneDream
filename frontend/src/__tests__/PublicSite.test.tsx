import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { PricingPage } from "../site/PricingPage";
import { SiteApp } from "../site/SiteApp";
import {
  compareReleaseVersions,
  fallbackRelease,
  formatBinarySize,
  isReleaseCandidateNonDowngrade,
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
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.stubEnv("VITE_BILLING_CHECKOUT_URL", "https://billing.test/functions/v1/billing-checkout");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline test")));
  });

  it("renders the one-screen landing page, direct Universal download, and mission gallery", async () => {
    const { container } = renderSite();

    expect(document.title).toBe("DroneDream");
    expect(screen.getByRole("heading", { name: "Give Every Mission a Flight Agent." })).toBeVisible();
    expect(screen.getByText(/Turn everyday language into complete drone missions/i)).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute("href", "/product/");
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/pricing/");
    expect(screen.getByRole("link", { name: "Manual" })).toHaveAttribute("href", "/manual/");
    expect(screen.getByRole("link", { name: "Community" })).toHaveAttribute("href", "/community/");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeVisible();
    expect(container.querySelector(".site-account-avatar")).toBeVisible();
    expect(container.querySelector(".site-footer")).toBeNull();
    expect(container.querySelectorAll(".site-home-card")).toHaveLength(11);
    expect(screen.getByRole("region", { name: "Mission examples" })).toBeVisible();
    expectContentLinksToUseIcons(container);

    expect(screen.getByRole("link", { name: "Download Universal" })).toHaveAttribute(
      "href",
      fallbackRelease.downloadUrl,
    );
    expect(screen.getByRole("button", { name: /Forest conservation, card 6 of 11/i }))
      .toHaveAttribute("aria-current", "true");
    fireEvent.keyDown(screen.getByRole("region", { name: "Mission examples" }), { key: "ArrowRight" });
    expect(screen.getByRole("button", { name: /Warehouse inventory, card 7 of 11/i }))
      .toHaveAttribute("aria-current", "true");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/downloads/latest.json",
      expect.objectContaining({ cache: "no-cache" }),
    ));
  });

  it("selects a mission card without tilting or navigating away", () => {
    renderSite();

    const card = screen.getByRole("button", { name: /Emergency search, card 9 of 11/i });
    fireEvent.click(card);
    expect(card).toHaveAttribute("aria-current", "true");
  });

  it("renders the production manual reader with its chapter sidebar and offline editions", () => {
    window.history.replaceState(null, "", "/manual/");

    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: "DroneDream 1.0.0 User Manual" })).toBeVisible();
    expect(screen.getByRole("complementary", { name: "DroneDream manual contents" })).toBeVisible();
    expect(screen.getByRole("searchbox", { name: "Search chapters" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Markdown" })).toHaveAttribute(
      "href",
      "/docs/downloads/DroneDream-Manual-en.md",
    );
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute(
      "href",
      "/docs/downloads/DroneDream-Manual-en.pdf",
    );
    expect(container.querySelector(".manual-sidebar")).not.toBeNull();
    expect(container.querySelector(".manual-reader")).not.toBeNull();
    expect(screen.queryByRole("dialog", { name: /manual/i })).toBeNull();
    expect(container.querySelector(".site-footer")).toBeNull();
  });

  it("routes Products to the five-product family without the retired mission preview", () => {
    window.history.replaceState(null, "", "/product/");

    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: "Hey! Get Your Flight Agent." })).toBeVisible();
    expect(container.querySelectorAll(".site-products-card")).toHaveLength(5);
    expect(screen.getByAltText("DroneDream Universal")).toBeVisible();
    expect(screen.getByAltText("DroneDream SIM")).toBeVisible();
    expect(screen.getByAltText("DroneDream LAB")).toBeVisible();
    expect(screen.getByAltText("DroneDream FIELD")).toBeVisible();
    expect(screen.getByAltText("DroneDream AGENT")).toBeVisible();
    expect(container.querySelector(".site-product-flight-board")).toBeNull();
    expect(screen.getAllByRole("button", { name: /download unavailable/i })).toHaveLength(4);
    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute("aria-current", "page");
    expect(container.querySelector(".site-footer")).toBeNull();
  });

  it("renders three directly comparable plans with the same ordered feature rows", async () => {
    window.history.replaceState(null, "", "/pricing/");

    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: "Choose the optimization depth for every flight." })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Free" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Plus" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Pro" })).toBeVisible();
    expect(container.querySelector(".site-footer")).toBeNull();
    expect(screen.getByRole("tab", { name: "Individual" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Business" }));
    expect(screen.getByRole("tab", { name: "Business" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText(/300,000 managed AI credits/i)).toBeVisible();
    expect(screen.getByText(/3,000,000 managed AI credits/i)).toBeVisible();
    expect(screen.getByText(/15,000,000 managed AI credits/i)).toBeVisible();
    expect(screen.getAllByText(
      "Team AURORA optimization Harness",
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

    fireEvent.click(screen.getByRole("button", { name: "Choose Plus" }));

    expect(screen.getByRole("dialog", { name: "Payment" })).toBeVisible();
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
    await waitFor(() => {
      expect(screen.queryByText(/Merchant payment activation/i)).toBeNull();
    });
    expect(screen.queryByText(/Review the selected plan/i)).toBeNull();
  });

  it("requires an account before a visitor can publish a community topic", () => {
    window.history.replaceState(null, "", "/community/");

    const { container } = renderSite();

    expect(screen.getByRole("heading", { name: "DRONEDREAM COMMUNITY" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Recent topics" })).toBeVisible();
    expect(container.querySelector(".community-feed")).not.toBeNull();
    expect(container.querySelector(".community-topic-grid")).not.toBeNull();
    expect(container.querySelector(".site-footer")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign in to publish" }));
    expect(screen.getByRole("dialog", { name: "Sign in" })).toBeVisible();
  });

  it("keeps the public website in English when a Chinese preference was stored", () => {
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    const { container } = renderSite();

    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(document.title).toBe("DroneDream");
    expect(screen.queryByRole("button", { name: /Switch to Simplified Chinese/i })).toBeNull();
    expect(screen.getByRole("heading", { name: "Give Every Mission a Flight Agent." })).toBeVisible();
    expect(screen.getByText("Products")).toBeVisible();
    expect(screen.getByRole("link", { name: "Download Universal" })).toBeVisible();
    expect(container.querySelectorAll(".site-home-card")).toHaveLength(11);
    expectContentLinksToUseIcons(container);
  });

  it("continues rendering when an external URL contains a malformed hash", () => {
    window.history.replaceState(null, "", "/#%E0%A4%A");

    expect(() => renderSite()).not.toThrow();
    expect(screen.getByRole("heading", { name: /Give Every Mission a Flight Agent/i })).toBeVisible();
  });

  it("keeps the full mission gallery available when the operating system requests reduced motion", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    renderSite();

    expect(screen.queryByRole("button", { name: /begin a starflight/i })).toBeNull();
    expect(document.querySelectorAll(".site-home-card")).toHaveLength(11);
  });

  it("validates release metadata and formats binary sizes", () => {
    expect(fallbackRelease).toMatchObject({
      edition: "universal",
      buildNumber: 1853,
      version: "1.0.0",
      fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
      sha256: "c9201779115a2008e2d8882ce621b4e62ec806ff681a59da2131531a5d71c554",
      sizeBytes: 153_800_039,
      publishedAt: "2026-09-28",
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
    const editionRelease = {
      ...fallbackRelease,
      edition: "sim" as const,
      buildNumber: 805,
      fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
      downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-805/DroneDream-Sim_1.0.0_x64-setup.exe",
      checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-805/DroneDream-Sim_1.0.0_x64-setup.exe.sha256",
    };
    expect(isWebsiteRelease(editionRelease)).toBe(true);
    const autonomyRelease = {
      ...editionRelease,
      edition: "autonomy" as const,
      fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
      downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-805/DroneDream-Agent_1.0.0_x64-setup.exe",
      checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-805/DroneDream-Agent_1.0.0_x64-setup.exe.sha256",
    };
    expect(isWebsiteRelease(autonomyRelease)).toBe(true);
    expect(isWebsiteRelease({
      ...editionRelease,
      fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    })).toBe(false);
    expect(isWebsiteRelease({ ...editionRelease, buildNumber: 806 })).toBe(false);
    expect(isWebsiteRelease({ ...editionRelease, edition: undefined })).toBe(false);
    const olderEditionBuild = {
      ...editionRelease,
      buildNumber: 804,
      downloadUrl: editionRelease.downloadUrl.replace("build-805", "build-804"),
      checksumUrl: editionRelease.checksumUrl.replace("build-805", "build-804"),
    };
    const newerEditionBuild = {
      ...editionRelease,
      buildNumber: 806,
      downloadUrl: editionRelease.downloadUrl.replace("build-805", "build-806"),
      checksumUrl: editionRelease.checksumUrl.replace("build-805", "build-806"),
    };
    expect(isWebsiteRelease(olderEditionBuild)).toBe(true);
    expect(isWebsiteRelease(newerEditionBuild)).toBe(true);
    expect(isReleaseCandidateNonDowngrade(olderEditionBuild, editionRelease)).toBe(false);
    expect(isReleaseCandidateNonDowngrade(editionRelease, editionRelease)).toBe(true);
    expect(isReleaseCandidateNonDowngrade(newerEditionBuild, editionRelease)).toBe(true);
    expect(isReleaseCandidateNonDowngrade(
      { ...newerEditionBuild, edition: "field" },
      editionRelease,
    )).toBe(false);
    expect(isReleaseCandidateNonDowngrade(fallbackRelease, fallbackRelease)).toBe(true);
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
      fileName: "DroneDream-Universal_1.0.1_x64-setup.exe",
      downloadUrl: "/downloads/DroneDream-Universal_1.0.1_x64-setup.exe",
      checksumUrl: "/downloads/DroneDream-Universal_1.0.1_x64-setup.exe.sha256",
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
      fileName: "DroneDream-Universal_1.0.1_x64-setup.exe",
      downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.1-build-1853/DroneDream-Universal_1.0.1_x64-setup.exe",
      checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.1-build-1853/DroneDream-Universal_1.0.1_x64-setup.exe.sha256",
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
