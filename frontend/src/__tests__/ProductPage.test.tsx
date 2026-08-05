import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductPage } from "../site/ProductPage";
import {
  fallbackEditionAvailability,
  type EditionAvailabilityDocument,
} from "../site/editionAvailability";
import { fallbackRelease } from "../site/release";

function publishedSimAvailability(): EditionAvailabilityDocument {
  const document = structuredClone(fallbackEditionAvailability);
  const sim = document.editions.find(({ id }) => id === "sim");
  if (!sim) throw new Error("Missing Sim edition fixture");
  sim.releaseStatus = "published";
  sim.downloadUrl = "/downloads/DroneDream-Sim-1.0.0.exe";
  sim.checksumUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sha256";
  sim.signatureUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sig";
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
        currentRelease={fallbackRelease}
        locale="en"
      />,
    );

    expect(screen.getByRole("heading", { name: "Choose the workspace built for your flight." }))
      .toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "DroneDream Sim" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream Lab" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream Field" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Coming soon" })).toHaveLength(3);
    expect(container.querySelector('a[href*="DroneDream-Sim-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Lab-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Field-1.0.0.exe"]')).toBeNull();
    expect(container.querySelector('a[href*="DroneDream-Universal-1.0.0.exe"]')).toBeNull();
    expect(screen.getByRole("link", { name: "Download current preview" }))
      .toHaveAttribute("href", fallbackRelease.downloadUrl);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("enables only a product whose complete published artifact binding is present", () => {
    render(
      <ProductPage
        availability={publishedSimAvailability()}
        currentRelease={fallbackRelease}
        locale="en"
      />,
    );

    expect(screen.getByRole("link", { name: "DroneDream-Sim-1.0.0.exe" }))
      .toHaveAttribute("href", "/downloads/DroneDream-Sim-1.0.0.exe");
    expect(screen.getByRole("link", { name: "DroneDream-Sim-1.0.0.exe" }))
      .toHaveAttribute("download", "DroneDream-Sim-1.0.0.exe");
    expect(screen.getAllByRole("button", { name: "Coming soon" })).toHaveLength(2);
  });

  it("authors the Simplified Chinese product page independently", () => {
    render(
      <ProductPage
        availability={fallbackEditionAvailability}
        currentRelease={fallbackRelease}
        locale="zh-CN"
      />,
    );

    expect(screen.getByRole("heading", { name: "选择适合你的飞行工作空间" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream 仿真版" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream 实验室版" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "DroneDream 真机版" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "即将推出" })).toHaveLength(3);
  });
});
