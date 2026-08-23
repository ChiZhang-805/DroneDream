import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComponentUpdateReport } from "../desktop/bridge";
import type { AppUpdateStatus } from "../desktop/updater";

const bridgeMocks = vi.hoisted(() => ({
  startRuntimeUpgrade: vi.fn(async () => undefined),
}));

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
    installComponentUpdates: vi.fn(async () => undefined),
    reconcileEnginePack: vi.fn(async () => undefined),
    reconcileComponentPacks: vi.fn(async () => undefined),
  },
}));

vi.mock("../desktop/bridge", async (importOriginal) => ({
  ...await importOriginal<typeof import("../desktop/bridge")>(),
  startRuntimeUpgrade: bridgeMocks.startRuntimeUpgrade,
}));

vi.mock("../desktop/updaterContext", () => ({
  AppUpdaterProvider: ({ children }: { children: ReactNode }) => children,
  useAppUpdaterState: () => updaterState.current,
}));

vi.mock("../i18n/I18nProvider", async () => (
  await import("../field/FieldI18nShim")
));

import { FieldLocaleProvider } from "../field/FieldLocaleProvider";
import { FieldSettingsDialog } from "../field/FieldSettingsDialog";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

function renderSettings(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("dronedream:field:locale", locale);
  return render(
    <EditionThemeProvider edition="field">
      <FieldLocaleProvider>
        <FieldSettingsDialog
          closeRef={createRef<HTMLButtonElement>()}
          locale={locale}
          onClose={() => undefined}
          onLocaleChange={() => undefined}
        />
      </FieldLocaleProvider>
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
  it("offers the signed application installer from the standalone Field surface", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.1",
      updateRequired: true,
    };
    renderSettings();

    fireEvent.click(screen.getByRole("tab", { name: "Safety" }));
    expect(screen.getByRole("heading", { name: "Software updates" })).toBeVisible();
    expect(screen.getByText("Version 1.0.1 is available. Click to update."))
      .toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Install update" }));

    expect(updaterState.current.installAvailableUpdate).toHaveBeenCalledOnce();
  });

  it("starts the native Runtime Base upgrade with Simplified Chinese feedback", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://updates.getdronedream.com/runtime/release-manifest.v1.json",
    );
    updaterState.current = {
      ...updaterState.current,
      status: "runtimeBaseRequired",
      updateRequired: true,
    };
    renderSettings("zh-CN");

    fireEvent.click(screen.getByRole("tab", { name: "安全" }));
    expect(screen.getByRole("heading", { name: "软件更新" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "升级 Runtime Base" }));

    await waitFor(() => {
      expect(bridgeMocks.startRuntimeUpgrade).toHaveBeenCalledWith({
        releaseManifestUrl:
          "https://updates.getdronedream.com/runtime/release-manifest.v1.json",
      });
    });
    expect(await screen.findByText("Runtime Base 升级已启动，请保持 DroneDream 打开。"))
      .toBeVisible();
  });
});
