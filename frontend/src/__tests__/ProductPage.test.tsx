import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductPage } from "../site/ProductPage";
import {
  fallbackEditionAvailability,
  type EditionAvailabilityDocument,
} from "../site/editionAvailability";

function publishedSimAvailability(): EditionAvailabilityDocument {
  const document = structuredClone(fallbackEditionAvailability);
  const sim = document.editions.find(({ id }) => id === "sim");
  if (!sim) throw new Error("Missing Sim edition fixture");
  sim.releaseStatus = "published";
  sim.availability = "downloadable";
  sim.signatureState = "signed";
  sim.downloadUrl = "/downloads/DroneDream-Sim-1.0.0.exe";
  sim.checksumUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sha256";
  sim.signatureUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sig";
  sim.receiptUrl = "/downloads/DroneDream-Sim-1.0.0.exe.receipt.json";
  sim.urlFamily = "/downloads";
  sim.sizeBytes = 12_345_678;
  sim.sha256 = "a".repeat(64);
  sim.sourceCommit = "b".repeat(40);
  sim.publishedAt = "2026-08-05";
  return document;
}

describe("ProductPage", () => {
  it("presents dense edition cards without inventing unavailable downloads", () => {
    const { container } = render(
      <ProductPage
        availability={fallbackEditionAvailability}
        locale="en"
      />,
    );

    expect(screen.getByRole("heading", { name: "Choose Your DroneDream Edition" }))
      .toBeVisible();
    expect(screen.getByText(
      "Three focused editions cover simulation search, lab validation, and controlled field tuning.",
    )).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "DroneDream · SIM" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · LAB" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · FIELD" })).toBeVisible();
    expect(screen.getByText("Simulation-only test loops")).toBeVisible();
    expect(screen.getByText("No real vehicle control")).toBeVisible();
    expect(screen.getByText("Sim-to-Real calibration")).toBeVisible();
    expect(screen.getByText("Qualification evidence review")).toBeVisible();
    expect(screen.getByText("Real vehicle setup flow")).toBeVisible();
    expect(screen.getByText("No simulation stage")).toBeVisible();
    expect(container.querySelectorAll(".site-product-edition li")).toHaveLength(18);

    const editionPictures = container.querySelectorAll(
      'picture.site-product-edition-picture'
      + '[data-brand-handoff="universal-canonical-brand-donor-v1.1.0"]'
      + '[data-brand-surface="product-card"]',
    );
    expect(editionPictures).toHaveLength(3);
    expect(container.querySelectorAll(
      'picture.site-product-edition-picture img[data-brand-asset="mark"]',
    )).toHaveLength(3);
    expect(container.querySelectorAll(
      'picture.site-product-edition-picture source[data-brand-asset="lockup"]',
    )).toHaveLength(3);
    expect(container.querySelector('[data-icon-donor="pending"]')).toBeNull();

    const downloadButtons = screen.getAllByRole("button", { name: /Download unavailable/i });
    expect(downloadButtons).toHaveLength(3);
    expect(downloadButtons.every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(container.querySelector('a[href*=".exe"]')).toBeNull();
    expect(screen.queryByText("In preparation")).toBeNull();
    expect(screen.queryByText("Coming soon")).toBeNull();

    expect(container.querySelectorAll(".site-product-screenshots")).toHaveLength(3);
    expect(screen.getByRole("img", { name: "SIM flight setup page" }))
      .toHaveAttribute("src", "/docs/en/flight-setup.png");
  });

  it("switches screenshots from the card controls", () => {
    render(
      <ProductPage
        availability={fallbackEditionAvailability}
        locale="en"
      />,
    );

    expect(screen.getByRole("img", { name: "SIM flight setup page" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", {
      name: "Next screenshot DroneDream · SIM",
    }));
    expect(screen.getByRole("img", { name: "SIM tuning chat page" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", {
      name: "Previous screenshot DroneDream · SIM",
    }));
    expect(screen.getByRole("img", { name: "SIM flight setup page" })).toBeVisible();
  });

  it.each([
    ["en", 1440, "Choose Your DroneDream Edition"],
    ["en", 760, "Choose Your DroneDream Edition"],
    ["en", 390, "Choose Your DroneDream Edition"],
    ["zh-CN", 1440, "选择你的 DroneDream 版本"],
    ["zh-CN", 760, "选择你的 DroneDream 版本"],
    ["zh-CN", 390, "选择你的 DroneDream 版本"],
  ] as const)(
    "keeps the %s download chooser fail-closed at %ipx",
    (locale, viewportWidth, title) => {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: viewportWidth,
      });
      const { container } = render(
        <ProductPage availability={fallbackEditionAvailability} locale={locale} />,
      );
      expect(screen.getByRole("heading", { name: title })).toBeVisible();
      expect(container.querySelectorAll(
        '[data-release-registry="exact-edition-exe-v1"][data-download-ready="false"]',
      )).toHaveLength(3);
      expect(screen.getAllByRole("button", { name: new RegExp(
        locale === "zh-CN" ? "暂不可下载" : "Download unavailable",
      ) })).toHaveLength(3);
    },
  );

  it("keeps published product bindings hidden while software downloads are closed", () => {
    render(
      <ProductPage
        availability={publishedSimAvailability()}
        locale="en"
      />,
    );

    expect(screen.queryByRole("link", { name: "DroneDream · SIM Download" }))
      .toBeNull();
    expect(screen.getByRole("button", { name: /DroneDream · SIM Download unavailable/i }))
      .toBeDisabled();
  });

  it("enables only a product whose complete published artifact binding is present when downloads are opened", () => {
    render(
      <ProductPage
        availability={publishedSimAvailability()}
        locale="en"
        softwareDownloadsEnabled
      />,
    );

    expect(screen.getByRole("link", { name: "DroneDream · SIM Download" }))
      .toHaveAttribute("href", "/downloads/DroneDream-Sim-1.0.0.exe");
    expect(screen.getByRole("link", { name: "DroneDream · SIM Download" }))
      .toHaveAttribute("download", "DroneDream-Sim-1.0.0.exe");
    expect(screen.getAllByRole("button", { name: /Download unavailable/i }))
      .toHaveLength(2);
  });

  it("authors the Simplified Chinese product page independently", () => {
    render(
      <ProductPage
        availability={fallbackEditionAvailability}
        locale="zh-CN"
      />,
    );

    expect(screen.getByRole("heading", { name: "选择你的 DroneDream 版本" })).toBeVisible();
    expect(screen.getByText("三个版本分别覆盖仿真搜索、实验验证和受控真机现场调参。")).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · SIM" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · LAB" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · FIELD" })).toBeVisible();
    expect(screen.getByText("纯仿真测试闭环")).toBeVisible();
    expect(screen.getByText("不连接控制真机")).toBeVisible();
    expect(screen.getByText("仿真到真机校准")).toBeVisible();
    expect(screen.getByText("真机到仿真更新")).toBeVisible();
    expect(screen.getByText("资格证据审核")).toBeVisible();
    expect(screen.getByText("真机接入设置")).toBeVisible();
    expect(screen.getByText("现场调参运行")).toBeVisible();
    expect(screen.getByText("实时遥测复核")).toBeVisible();
    expect(screen.queryByText("正在准备")).toBeNull();
    expect(screen.queryByText("当前内测预览版")).toBeNull();
  });
});
