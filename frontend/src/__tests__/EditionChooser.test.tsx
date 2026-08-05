import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditionChooser } from "../site/EditionChooser";
import {
  fallbackEditionAvailability,
  type EditionAvailabilityDocument,
} from "../site/editionAvailability";
import { fallbackRelease } from "../site/release";

const noopRef = () => undefined;

function renderChooser(
  availability: EditionAvailabilityDocument = fallbackEditionAvailability,
  onClose = vi.fn(),
) {
  const result = render(
    <EditionChooser
      availability={availability}
      currentRelease={fallbackRelease}
      locale="en"
      onClose={onClose}
      open
      setCloseButtonRef={noopRef}
      setDialogRef={noopRef}
    />,
  );
  return { ...result, onClose };
}

function publishedAvailability() {
  const document = structuredClone(fallbackEditionAvailability);
  const sim = document.editions[0]!;
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

describe("EditionChooser", () => {
  it("keeps all planned editions disabled without inventing download links", () => {
    const { container } = renderChooser();
    const dialog = screen.getByRole("dialog", { name: "Choose your edition" });

    expect(within(dialog).getAllByRole("radio")).toHaveLength(3);
    expect(within(dialog).getAllByRole("button", { name: "Coming soon" })).toHaveLength(4);
    expect(within(dialog).getByText(
      "Not sure which fits? DroneDream Universal lets you switch workspaces later.",
    )).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "Download current preview" }))
      .toHaveAttribute("href", fallbackRelease.downloadUrl);
    expect(container.querySelector(`a[href*="DroneDream-Sim-1.0.0.exe"]`)).toBeNull();
    expect(container.querySelector(`a[href*="DroneDream-Lab-1.0.0.exe"]`)).toBeNull();
    expect(container.querySelector(`a[href*="DroneDream-Field-1.0.0.exe"]`)).toBeNull();
    expect(container.querySelector(`a[href*="DroneDream-Universal-1.0.0.exe"]`)).toBeNull();
  });

  it("supports roving arrow, Home, and End keyboard selection", () => {
    renderChooser();
    const radios = screen.getAllByRole("radio");

    radios[0]!.focus();
    fireEvent.keyDown(radios[0]!, { key: "ArrowRight" });
    expect(radios[1]).toHaveFocus();
    expect(radios[1]).toHaveAttribute("aria-checked", "true");

    fireEvent.keyDown(radios[1]!, { key: "End" });
    expect(radios[2]).toHaveFocus();
    expect(radios[2]).toHaveAttribute("aria-checked", "true");

    fireEvent.keyDown(radios[2]!, { key: "Home" });
    expect(radios[0]).toHaveFocus();
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("requires selection before exposing the exact confirm-download action", () => {
    renderChooser(publishedAvailability());
    const dialog = screen.getByRole("dialog", { name: "Choose your edition" });

    expect(within(dialog).queryByRole("link", { name: "Confirm download" })).toBeNull();
    fireEvent.click(within(dialog).getAllByRole("radio")[0]!);
    expect(within(dialog).getByRole("link", { name: "Confirm download" }))
      .toHaveAttribute("href", "/downloads/DroneDream-Sim-1.0.0.exe");
    expect(within(dialog).getByRole("link", { name: "Confirm download" }))
      .toHaveAttribute("download", "DroneDream-Sim-1.0.0.exe");
  });

  it("keeps Universal outside the three-card grid and requires explicit confirmation", () => {
    const document = structuredClone(fallbackEditionAvailability);
    const universal = document.editions.find(({ id }) => id === "universal")!;
    universal.releaseStatus = "published";
    universal.downloadUrl = "/downloads/DroneDream-Universal-1.0.0.exe";
    universal.checksumUrl = "/downloads/DroneDream-Universal-1.0.0.exe.sha256";
    universal.signatureUrl = "/downloads/DroneDream-Universal-1.0.0.exe.sig";
    universal.sizeBytes = 12_345_678;
    universal.sha256 = "c".repeat(64);
    universal.sourceCommit = "d".repeat(40);
    universal.publishedAt = "2026-08-05";

    renderChooser(document);
    const dialog = screen.getByRole("dialog", { name: "Choose your edition" });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(3);
    expect(within(dialog).queryByRole("link", { name: "Confirm download" })).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Choose Universal" }));
    expect(within(dialog).getByRole("link", { name: "Confirm download" }))
      .toHaveAttribute("href", "/downloads/DroneDream-Universal-1.0.0.exe");
    expect(within(dialog).getByRole("link", { name: "Confirm download" }))
      .toHaveAttribute("download", "DroneDream-Universal-1.0.0.exe");
  });

  it("closes only when the backdrop itself is clicked", () => {
    const onClose = vi.fn();
    const { container } = renderChooser(fallbackEditionAvailability, onClose);
    const dialog = screen.getByRole("dialog", { name: "Choose your edition" });

    fireEvent.mouseDown(dialog);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(container.querySelector(".site-edition-backdrop")!);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
