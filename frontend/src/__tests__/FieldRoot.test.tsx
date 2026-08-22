import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FieldLocaleProvider } from "../field/FieldLocaleProvider";

vi.mock("../components/DroneLaunchScene", () => ({
  DroneLaunchSceneCore: ({
    active,
    progress,
    labels,
  }: {
    active: boolean;
    progress: number;
    labels: {
      active: string;
      standby: string;
      system: string;
    };
  }) => (
    <div
      data-testid="field-drone-scene"
      data-active={String(active)}
      data-progress={progress}
      data-telemetry-active={labels.active}
      data-telemetry-standby={labels.standby}
      data-telemetry-system={labels.system}
    />
  ),
}));

vi.mock("../field/FieldAuthControl", () => ({
  FieldAuthControl: ({
    locale,
    launcherReady,
    onAuthenticated,
  }: {
    locale: "en" | "zh-CN";
    launcherReady: boolean;
    onAuthenticated: () => void;
  }) => (
    <button type="button" disabled={!launcherReady} onClick={onAuthenticated}>
      {locale === "en"
        ? "Sign in and enter the tuning platform"
        : "登录并进入调优平台"}
    </button>
  ),
}));

vi.mock("../field/FieldApp", () => ({
  FieldApp: ({
    initialLocale,
    focusOnMount,
  }: {
    initialLocale: string;
    focusOnMount: boolean;
  }) => (
    <div
      data-testid="field-workspace"
      data-locale={initialLocale}
      data-focus-on-mount={String(focusOnMount)}
    />
  ),
}));

import { FieldRoot } from "../field/FieldRoot";

async function finishLoading(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5_000);
  });
}

describe("FieldRoot", () => {
  beforeEach(() => {
    document.documentElement.dataset.brandEdition = "field";
    document.documentElement.style.setProperty("--dd-brand-start", "#ff9f3f");
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => ({
      getExtension: () => ({ loseContext: vi.fn() }),
    }) as unknown as RenderingContext);
  });

  afterEach(() => {
    delete document.documentElement.dataset.brandEdition;
    document.documentElement.style.removeProperty("--dd-brand-start");
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads the shared 3D launch scene to 100 percent before offering entry", async () => {
    vi.useFakeTimers();
    const { container } = render(
      <FieldLocaleProvider>
        <FieldRoot />
      </FieldLocaleProvider>,
    );

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.queryByRole("button", {
      name: "Sign in and enter the tuning platform",
    })).not.toBeInTheDocument();

    await finishLoading();

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Sign in and enter the tuning platform",
    })).toBeEnabled();
    expect(screen.getByTestId("field-drone-scene")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("field-drone-scene"))
      .toHaveAttribute("data-telemetry-system", "REAL DEVICE DOMAIN");
    expect(container.firstChild).toHaveAttribute("data-authority", "false");
    expect(container).not.toHaveTextContent(/PX4|Gazebo|SITL|HITL/i);

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" }))
      .toHaveAttribute("data-settings-consumer", "field");
  });

  it("keeps language inside settings and enters the localized Field workspace after auth", async () => {
    vi.useFakeTimers();
    render(
      <FieldLocaleProvider>
        <FieldRoot />
      </FieldLocaleProvider>,
    );
    expect(screen.queryByRole("button", { name: "Switch to Simplified Chinese" }))
      .not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    fireEvent.click(screen.getByRole("button", { name: "简体中文" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭设置" }));
    await finishLoading();

    const enter = screen.getByRole("button", { name: "登录并进入调优平台" });
    expect(enter).toBeEnabled();
    await act(async () => {
      fireEvent.click(enter);
      await Promise.resolve();
    });

    expect(screen.getByTestId("field-workspace"))
      .toHaveAttribute("data-locale", "zh-CN");
    expect(screen.getByTestId("field-workspace"))
      .toHaveAttribute("data-focus-on-mount", "true");
  });
});
