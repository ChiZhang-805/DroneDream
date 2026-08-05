import { render, screen } from "@testing-library/react";
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
  it("presents exactly three focused products without inventing planned downloads", () => {
    const { container } = render(
      <ProductPage
        availability={fallbackEditionAvailability}
        locale="en"
      />,
    );

    expect(screen.getByRole("heading", { name: "DroneDream Editions" }))
      .toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "DroneDream · SIM" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · LAB" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · FIELD" })).toBeVisible();
    const editionMarks = container.querySelectorAll(
      'img.site-product-edition-icon[data-brand-handoff="commander-approved-brand-handoff-v2"]',
    );
    expect(editionMarks).toHaveLength(3);
    expect([...editionMarks].map((image) => image.getAttribute("src"))).toEqual([
      expect.stringContaining("dronedream-sim-mark.png"),
      expect.stringContaining("dronedream-lab-mark.png"),
      expect.stringContaining("dronedream-field-mark.png"),
    ]);
    expect(container.querySelector('[data-icon-donor="pending"]')).toBeNull();
    expect(container.querySelector(".site-product-edition-visual")).toBeNull();
    expect(container.querySelector(".site-product-current")).toBeNull();
    expect(screen.queryByText("In preparation")).toBeNull();
    expect(screen.queryByText("Coming soon")).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Sim-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Lab-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Field-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Universal-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream_1.0.0_x64-setup.exe"]')).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    ["en", 1440, "DroneDream Editions"],
    ["en", 760, "DroneDream Editions"],
    ["en", 390, "DroneDream Editions"],
    ["zh-CN", 1440, "DroneDream 专业版本"],
    ["zh-CN", 760, "DroneDream 专业版本"],
    ["zh-CN", 390, "DroneDream 专业版本"],
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
      expect(container.querySelectorAll(".site-product-edition-action")).toHaveLength(0);
    },
  );

  it("enables only a product whose complete published artifact binding is present", () => {
    render(
      <ProductPage
        availability={publishedSimAvailability()}
        locale="en"
      />,
    );

    expect(screen.getByRole("link", { name: "DroneDream-Sim-1.0.0.exe" }))
      .toHaveAttribute("href", "/downloads/DroneDream-Sim-1.0.0.exe");
    expect(screen.getByRole("link", { name: "DroneDream-Sim-1.0.0.exe" }))
      .toHaveAttribute("download", "DroneDream-Sim-1.0.0.exe");
    expect(screen.queryByRole("button", { name: "Coming soon" })).toBeNull();
  });

  it("authors the Simplified Chinese product page independently", () => {
    render(
      <ProductPage
        availability={fallbackEditionAvailability}
        locale="zh-CN"
      />,
    );

    expect(screen.getByRole("heading", { name: "DroneDream 专业版本" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · SIM" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · LAB" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream · FIELD" })).toBeVisible();
    expect(screen.queryByText("正在准备")).toBeNull();
    expect(screen.queryByText("当前内测预览版")).toBeNull();
  });
});
