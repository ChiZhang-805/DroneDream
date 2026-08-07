import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";

vi.mock("../components/DroneLaunchScene", () => ({
  DroneLaunchScene: ({
    active,
    progress,
    telemetryActiveLabel,
    telemetryStandbyLabel,
    telemetrySystemLabel,
  }: {
    active: boolean;
    progress: number;
    telemetryActiveLabel: string;
    telemetryStandbyLabel: string;
    telemetrySystemLabel: string;
  }) => (
    <div
      data-testid="field-drone-scene"
      data-active={String(active)}
      data-progress={progress}
      data-telemetry-active={telemetryActiveLabel}
      data-telemetry-standby={telemetryStandbyLabel}
      data-telemetry-system={telemetrySystemLabel}
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
    await vi.advanceTimersByTimeAsync(1_100);
  });
}

describe("FieldRoot", () => {
  it("loads the shared 3D launch scene to 100 percent before offering entry", async () => {
    vi.useFakeTimers();
    const { container } = render(
      <I18nProvider>
        <FieldRoot />
      </I18nProvider>,
    );

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "8");
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
  });

  it("switches the launcher to Chinese and enters the Field workspace after auth", async () => {
    vi.useFakeTimers();
    render(
      <I18nProvider>
        <FieldRoot />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to Simplified Chinese" }));
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
