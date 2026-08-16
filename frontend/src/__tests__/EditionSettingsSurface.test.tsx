import { fireEvent, render, screen } from "@testing-library/react";
import { createRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTabId,
} from "../components/EditionSettingsSurface";
import { FieldSettingsDialog } from "../field/FieldSettingsDialog";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

const tabs = [
  { id: "general", label: "General" },
  { id: "memory", label: "Memory" },
  { id: "model", label: "Model" },
  { id: "runtime", label: "Runtime" },
] as const;

function FieldSettingsFixture({ onClose = () => undefined }: { onClose?: () => void }) {
  const [activeTab, setActiveTab] = useState<SettingsSurfaceTabId>("general");
  return (
    <EditionThemeProvider edition="field">
      <EditionSettingsSurface
        activeTab={activeTab}
        closeLabel="Close settings"
        edition="field"
        onClose={onClose}
        onTabChange={setActiveTab}
        tabs={tabs}
        title="Settings"
        consumerProfile="field-lightweight"
      >
        {tabs.map((tab) => (
          <EditionSettingsPanel key={tab.id} active={activeTab === tab.id} id={tab.id}>
            <p>{tab.label} content</p>
          </EditionSettingsPanel>
        ))}
      </EditionSettingsSurface>
    </EditionThemeProvider>
  );
}

describe("EditionSettingsSurface", () => {
  it("is a shared Field-consumable presentation surface that grants no authority", () => {
    const onClose = vi.fn();
    const { container } = render(<FieldSettingsFixture onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Settings" });

    expect(dialog).toHaveAttribute("data-settings-consumer", "field-lightweight");
    expect(dialog).toHaveAttribute("data-brand-edition", "field");
    expect(dialog).toHaveAttribute("data-presentation-only", "true");
    expect(dialog).toHaveAttribute("data-grants-hardware-authority", "false");
    expect(container.querySelector('[data-settings-panel="general"]')).toBeVisible();
    expect(container.querySelector('[data-settings-panel="runtime"]')).not.toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("supports deterministic roving tab focus with arrow, Home, and End keys", () => {
    render(<FieldSettingsFixture />);
    const general = screen.getByRole("tab", { name: "General" });
    const memory = screen.getByRole("tab", { name: "Memory" });
    const runtime = screen.getByRole("tab", { name: "Runtime" });

    general.focus();
    fireEvent.keyDown(general, { key: "ArrowRight" });
    expect(memory).toHaveFocus();
    expect(memory).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Memory" })).toBeVisible();

    fireEvent.keyDown(memory, { key: "End" });
    expect(runtime).toHaveFocus();
    expect(runtime).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(runtime, { key: "Home" });
    expect(general).toHaveFocus();
    expect(general).toHaveAttribute("aria-selected", "true");
  });

  it("keeps ECE498BH inside the standalone Field settings surface", () => {
    render(
      <EditionThemeProvider edition="field">
        <FieldSettingsDialog
          closeRef={createRef<HTMLButtonElement>()}
          locale="en"
          onClose={() => undefined}
          onLocaleChange={() => undefined}
        />
      </EditionThemeProvider>,
    );

    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(screen.getByRole("tab", { name: "Models" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "General" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Memory" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "ECE498BH" })).toBeEnabled();
    fireEvent.click(screen.getByRole("tab", { name: "ECE498BH" }));
    expect(screen.getByRole("link", { name: "Open course" })).toHaveAttribute(
      "href",
      "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
    );
  });
});
