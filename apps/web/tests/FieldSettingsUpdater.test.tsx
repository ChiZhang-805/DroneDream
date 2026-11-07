import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComponentUpdateReport } from "../src/desktop/bridge";
import type { AppUpdateStatus } from "../src/desktop/updater";

const updaterState = vi.hoisted(() => ({
  current: {
    status: "current" as AppUpdateStatus,
    availableVersion: null as string | null,
    updateRequired: false,
    progress: null as number | null,
    error: null as string | null,
    enginePack: null,
    componentUpdates: null as ComponentUpdateReport | null,
    desktopRuntime: true,
    checkForUpdates: vi.fn(async () => undefined),
    installAvailableUpdate: vi.fn(async () => undefined),
    installRuntimeBaseUpdate: vi.fn(async () => undefined),
    installComponentUpdates: vi.fn(async () => undefined),
    reconcileEnginePack: vi.fn(async () => undefined),
    reconcileComponentPacks: vi.fn(async () => undefined),
  },
}));

vi.mock("../src/desktop/updaterContext", () => ({
  AppUpdaterProvider: ({ children }: { children: ReactNode }) => children,
  useAppUpdaterState: () => updaterState.current,
}));

vi.mock("../src/i18n/I18nProvider", async () => (
  await import("../src/field/FieldI18nShim")
));

import { FieldLocaleProvider } from "../src/field/FieldLocaleProvider";
import { FieldSettingsDialog } from "../src/field/FieldSettingsDialog";
import { EditionThemeProvider } from "../src/theme/EditionThemeProvider";
import { ModelAccessProvider } from "../src/features/settings/ModelAccessProvider";

function renderSettings(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("dronedream:field:locale", locale);
  return render(
    <EditionThemeProvider edition="field">
      <ModelAccessProvider accountScope="field:test">
        <FieldLocaleProvider>
          <FieldSettingsDialog
            closeRef={createRef<HTMLButtonElement>()}
            locale={locale}
            onClose={() => undefined}
            onLocaleChange={() => undefined}
            presentation="workspace"
          />
        </FieldLocaleProvider>
      </ModelAccessProvider>
    </EditionThemeProvider>,
  );
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  updaterState.current = {
    ...updaterState.current,
    status: "current",
    availableVersion: null,
    updateRequired: false,
    progress: null,
    error: null,
    componentUpdates: null,
  };
});

describe("Field settings update center", () => {
  it("shows the actual Engine Pack conflict instead of hiding it in a tooltip", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "engineError",
      error: "Different Engine Packs share the same source timestamp; refusing an ambiguous update.",
    };
    renderSettings();
    fireEvent.click(screen.getByRole("tab", { name: "Runtime" }));
    expect(screen.getByRole("status", { name: "software version state: Engine Pack check failed" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("existing Runtime was preserved");
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("never exposes an Engine Pack traceback in the settings panel", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "engineError",
      error: "Traceback (most recent call last):\n  File \"/mnt/c/Users/example/engine-pack-manager.py\", line 404, in install_pack\nEnginePackError: incompatible payload",
    };
    renderSettings();
    fireEvent.click(screen.getByRole("tab", { name: "Runtime" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The update could not be completed. Retry, or update Runtime Base if the problem continues.",
    );
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
    expect(screen.queryByText(/engine-pack-manager\.py/)).not.toBeInTheDocument();
  });

  it("reports a signed application update without installing it from settings", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.1",
      updateRequired: true,
    };
    renderSettings();

    fireEvent.click(screen.getByRole("tab", { name: "Runtime" }));
    expect(screen.getByRole("heading", { name: "Software updates" })).toBeVisible();
    expect(screen.getByRole("status", {
      name: "software version state: old-version · v1.0.1",
    })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));

    expect(updaterState.current.installAvailableUpdate).not.toHaveBeenCalled();
    expect(updaterState.current.checkForUpdates).toHaveBeenCalledOnce();
  });

  it("reports a routine Engine Pack update without installing it from settings", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "engineAvailable",
      updateRequired: false,
    };
    renderSettings();
    fireEvent.click(screen.getByRole("tab", { name: "Runtime" }));

    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));

    expect(updaterState.current.reconcileEnginePack).not.toHaveBeenCalled();
    expect(updaterState.current.checkForUpdates).toHaveBeenCalledOnce();
  });

  it("reports a Runtime Base upgrade in Simplified Chinese without installing it", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "runtimeBaseRequired",
      updateRequired: true,
    };
    renderSettings("zh-CN");

    fireEvent.click(screen.getByRole("tab", { name: "Runtime" }));
    expect(screen.getByRole("heading", { name: "软件更新" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));

    expect(updaterState.current.checkForUpdates).toHaveBeenCalledOnce();
  });
});
