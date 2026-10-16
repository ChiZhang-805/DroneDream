import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductPage } from "../site/ProductPage";
import {
  fallbackEditionAvailability,
  isEditionAvailabilityDocument,
  type EditionAvailabilityDocument,
} from "../site/editionAvailability";

function publishedSim(): EditionAvailabilityDocument {
  const availability = structuredClone(fallbackEditionAvailability);
  availability.editions[0] = {
    id: "sim",
    status: "published",
    version: "1.0.0",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/four-edition-v1.0.0/DroneDream-Sim_1.0.0_x64-setup.exe",
    checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/four-edition-v1.0.0/DroneDream-Sim_1.0.0_x64-setup.exe.sha256",
    signatureUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/four-edition-v1.0.0/DroneDream-Sim_1.0.0_x64-setup.exe.sig",
    receiptUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/four-edition-v1.0.0/DroneDream-Sim_1.0.0_x64-setup.exe.receipt.json",
    sizeBytes: 12_107_808,
    sha256: "8a266e55fd669ca74da76ac0b5aa69bca9f966590a11be12df4bff06363a4af9",
    sourceCommit: "3a5ff7733588c01a730e2e0ed35cac6ea4fb0b0c",
    publishedAt: "2026-08-11",
  };
  return availability;
}

describe("ProductPage", () => {
  it("shows exactly SIM, LAB, and FIELD with fail-closed download actions", () => {
    const { container } = render(
      <ProductPage availability={fallbackEditionAvailability} locale="en" />,
    );

    expect(container.querySelectorAll(".site-product-edition")).toHaveLength(3);
    expect(screen.getByText("Scenario setup")).toBeVisible();
    expect(screen.getByText("Hardware-in-the-loop")).toBeVisible();
    expect(screen.getByText("Vehicle setup")).toBeVisible();
    expect(container.querySelectorAll(".site-product-edition li")).toHaveLength(9);
    expect(container.querySelectorAll(".site-product-family-strip article")).toHaveLength(5);
    expect(container.querySelector(".site-product-route-line")).not.toBeNull();
    expect(container.querySelector(".site-product-map-aircraft")).not.toBeNull();
    expect(container).not.toHaveTextContent(/System requirements|Evidence and history|Who it is for|Validation workflow/i);
    expect(screen.getAllByRole("button", { name: /Download unavailable/i })).toHaveLength(3);
    expect(screen.queryByRole("link", { name: /DroneDream .* Download/i })).toBeNull();
  });

  it("enables only an edition backed by a complete validated release record", () => {
    const availability = publishedSim();
    expect(isEditionAvailabilityDocument(availability)).toBe(true);

    render(<ProductPage availability={availability} locale="en" />);

    expect(screen.getByRole("link", { name: "DroneDream · SIM Download" }))
      .toHaveAttribute("href", availability.editions[0].downloadUrl);
    expect(screen.getByRole("button", { name: "DroneDream · LAB Download unavailable" }))
      .toBeDisabled();
    expect(screen.getByRole("button", { name: "DroneDream · FIELD Download unavailable" }))
      .toBeDisabled();
  });

  it("rejects incomplete or cross-family release metadata", () => {
    const invalid = publishedSim();
    invalid.editions[0].checksumUrl = invalid.editions[0].checksumUrl?.replace(
      "four-edition-v1.0.0",
      "wrong-family",
    ) ?? null;

    expect(isEditionAvailabilityDocument(invalid)).toBe(false);
  });

  it("accepts the edition-scoped formal release filename and receipt", () => {
    const availability = publishedSim();
    const releaseFamily = "desktop-sim-v1.0.0-build-42";
    const fileName = "DroneDream-Sim-1.0.0.exe";
    availability.editions[0] = {
      ...availability.editions[0],
      fileName,
      downloadUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}`,
      checksumUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.sha256`,
      signatureUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.sig`,
      receiptUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.receipt.json`,
    };

    expect(isEditionAvailabilityDocument(availability)).toBe(true);
  });

  it("accepts AUTONOMY availability but keeps it hidden until a release is published", () => {
    const availability = structuredClone(fallbackEditionAvailability);

    expect(isEditionAvailabilityDocument(availability)).toBe(true);
    const { container, rerender } = render(<ProductPage availability={availability} locale="en" />);
    expect(container.querySelectorAll(".site-product-edition")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "DroneDream · AGENT" })).toBeNull();

    const releaseFamily = "desktop-autonomy-v1.0.0-build-1";
    const fileName = "DroneDream-Agent-1.0.0.exe";
    availability.editions[3] = {
      id: "autonomy",
      status: "published",
      version: "1.0.0",
      fileName,
      downloadUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}`,
      checksumUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.sha256`,
      signatureUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.sig`,
      receiptUrl: `https://github.com/ChiZhang-805/DroneDream/releases/download/${releaseFamily}/${fileName}.receipt.json`,
      sizeBytes: 12_000_000,
      sha256: "a".repeat(64),
      sourceCommit: "b".repeat(40),
      publishedAt: "2026-08-20",
    };

    expect(isEditionAvailabilityDocument(availability)).toBe(true);
    rerender(<ProductPage availability={availability} locale="en" />);
    expect(container.querySelectorAll(".site-product-edition")).toHaveLength(4);
    expect(screen.getByText("Natural-language planning")).toBeVisible();
    expect(screen.getByRole("link", { name: "DroneDream · AGENT Download" }))
      .toHaveAttribute("href", availability.editions[3].downloadUrl);
  });

  it("keeps the public product surface in English for every stored interface locale", () => {
    render(<ProductPage availability={fallbackEditionAvailability} locale="zh-CN" />);

    expect(screen.getByRole("heading", { name: /Describe the mission/i })).toBeVisible();
    expect(screen.getByText("Scenario setup")).toBeVisible();
    expect(screen.queryByText(/选择你的/)).toBeNull();
  });
});
