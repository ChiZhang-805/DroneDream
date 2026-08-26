import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "../components/EditionSettingsSurface";
import { FieldSettingsDialog } from "../field/FieldSettingsDialog";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

const tabs = [
  { id: "general", label: "General" },
  { id: "memory", label: "Memory" },
  { id: "model", label: "Model" },
  { id: "runtime", label: "Runtime" },
] as const;

function FieldSettingsFixture({
  onClose = () => undefined,
  presentation = "dialog",
  settingsTabs = tabs,
}: {
  onClose?: () => void;
  presentation?: "dialog" | "workspace";
  settingsTabs?: readonly SettingsSurfaceTab[];
}) {
  const [activeTab, setActiveTab] = useState<SettingsSurfaceTabId>("general");
  return (
    <EditionThemeProvider edition="field">
      <EditionSettingsSurface
        activeTab={activeTab}
        closeLabel="Close settings"
        edition="field"
        onClose={onClose}
        onTabChange={setActiveTab}
        tabs={settingsTabs}
        title="Settings"
        consumerProfile="field"
        presentation={presentation}
        backLabel="Back to app"
      >
        {settingsTabs.map((tab) => (
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

    expect(dialog).toHaveAttribute("data-settings-consumer", "field");
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

  it("renders a dedicated workspace with vertical categories, disabled-tab skipping, and a back action", async () => {
    const onClose = vi.fn();
    const workspaceTabs: readonly SettingsSurfaceTab[] = [
      { id: "general", label: "General" },
      { id: "memory", label: "Memory" },
      { id: "model", label: "Models & allowance", disabled: true },
      { id: "runtime", label: "Runtime & updates" },
    ];
    render(
      <FieldSettingsFixture
        onClose={onClose}
        presentation="workspace"
        settingsTabs={workspaceTabs}
      />,
    );

    const workspace = screen.getByRole("region", { name: "Settings" });
    const tablist = within(workspace).getByRole("tablist", { name: "Settings" });
    expect(tablist).toHaveAttribute("aria-orientation", "vertical");
    expect(workspace).not.toHaveAttribute("aria-modal");
    expect(workspace).toHaveAttribute("data-presentation-only", "true");
    expect(workspace).toHaveAttribute("data-grants-hardware-authority", "false");
    expect(screen.getAllByRole("heading", { name: "Settings" })).toHaveLength(1);
    expect(within(workspace).getByRole("heading", { name: "General" })).toBeVisible();

    const general = within(tablist).getByRole("tab", { name: "General" });
    const memory = within(tablist).getByRole("tab", { name: "Memory" });
    const model = within(tablist).getByRole("tab", { name: "Models & allowance" });
    const runtime = within(tablist).getByRole("tab", { name: "Runtime & updates" });
    expect(model).toBeDisabled();
    expect(model).toHaveAttribute("aria-disabled", "true");
    await waitFor(() => expect(general).toHaveFocus());

    fireEvent.keyDown(general, { key: "ArrowDown" });
    expect(memory).toHaveFocus();
    expect(memory).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(memory, { key: "ArrowDown" });
    expect(runtime).toHaveFocus();
    expect(runtime).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(runtime, { key: "ArrowUp" });
    expect(memory).toHaveFocus();
    fireEvent.keyDown(memory, { key: "End" });
    expect(runtime).toHaveFocus();
    fireEvent.keyDown(runtime, { key: "Home" });
    expect(general).toHaveFocus();
    expect(general).toHaveAttribute("aria-selected", "true");

    fireEvent.click(memory);
    expect(within(workspace).getByRole("heading", { name: "Memory" })).toBeVisible();
    expect(within(workspace).getByRole("tabpanel", { name: "Memory" })).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(workspace).toBeInTheDocument();
  });

  it("keeps ECE498BH inside the standalone Field settings surface", () => {
    render(
      <EditionThemeProvider edition="field">
        <ModelAccessProvider accountScope="field:test">
          <FieldSettingsDialog
            closeRef={createRef<HTMLButtonElement>()}
            locale="en"
            onClose={() => undefined}
            onLocaleChange={() => undefined}
            presentation="workspace"
          />
        </ModelAccessProvider>
      </EditionThemeProvider>,
    );

    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(screen.getByRole("tab", { name: "Models" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "General" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Memory" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "ECE498BH" })).toBeEnabled();
    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    expect(screen.getByLabelText("Model profile")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "ECE498BH" }));
    expect(screen.getByRole("link", { name: "Open course" })).toHaveAttribute(
      "href",
      "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
    );
  });
});
