import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FieldLocaleProvider } from "../field/FieldLocaleProvider";

vi.mock("../components/LauncherFlightIllustration", () => ({
  LauncherFlightIllustration: ({
    active,
    progress,
    description,
    title,
  }: {
    active: boolean;
    progress: number;
    description: string;
    title: string;
  }) => (
    <div
      data-testid="field-drone-scene"
      data-active={String(active)}
      data-progress={progress}
      data-title={title}
      data-description={description}
    />
  ),
}));

const fieldAuth = vi.hoisted(() => ({ account: { id: "field-test" } as { id: string } | null }));
vi.mock("../features/auth/AuthContext", () => ({ useAuthOrLocal: () => ({ account: fieldAuth.account }) }));
vi.mock("../components/LauncherAccountForm", () => ({ LauncherAccountForm: ({ onAuthenticated }: { onAuthenticated: () => void }) => <form aria-label="Email account"><button type="button" onClick={() => { fieldAuth.account = { id: "new-field-account" }; onAuthenticated(); }}>Complete authentication</button></form> }));

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
    fieldAuth.account = { id: "field-test" };
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

  it("shows the email form immediately when signed out", () => {
    fieldAuth.account = null;
    render(<FieldLocaleProvider><FieldRoot /></FieldLocaleProvider>);
    expect(screen.getByRole("form", { name: "Email account" })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("automatically opens the Field Chatbot after authentication and readiness", async () => {
    vi.useFakeTimers();
    fieldAuth.account = null;
    render(<FieldLocaleProvider><FieldRoot /></FieldLocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Complete authentication" }));
    expect(screen.queryByTestId("field-workspace")).not.toBeInTheDocument();
    await finishLoading();
    expect(screen.getByTestId("field-workspace")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enter workspace" })).not.toBeInTheDocument();
  });

  it("loads the lightweight launch screen to 100 percent before offering entry", async () => {
    vi.useFakeTimers();
    const { container } = render(
      <FieldLocaleProvider>
        <FieldRoot />
      </FieldLocaleProvider>,
    );

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.queryByRole("button", {
      name: "Enter workspace",
    })).toBeDisabled();

    await finishLoading();

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Enter workspace",
    })).toBeEnabled();
    expect(screen.getByTestId("field-drone-scene")).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("field-drone-scene"))
      .toHaveAttribute("data-title", "Ready for takeoff");
    expect(container.firstChild).toHaveAttribute("data-authority", "false");
    expect(container).not.toHaveTextContent(/PX4|Gazebo|SITL|HITL/i);

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    const quickSettings = screen.getByRole("dialog", { name: "Settings" });
    expect(quickSettings).toHaveAttribute("data-settings-consumer", "field");
    expect(quickSettings.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(container.querySelector(".launcher-chrome")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".launcher-main")).toHaveAttribute("aria-hidden", "true");
    expect((container.querySelector(".launcher-main") as HTMLElement).inert).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "All settings" }));
    const settingsWorkspace = screen.getByRole("region", { name: "Settings" });
    expect(settingsWorkspace).toHaveAttribute("data-settings-consumer", "field");
    expect(screen.getByRole("tablist", { name: "Settings" }))
      .toHaveAttribute("aria-orientation", "vertical");
    expect(container.querySelector(".launcher-chrome")).toHaveAttribute("aria-hidden", "true");
    expect((container.querySelector(".launcher-main") as HTMLElement).inert).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    expect(container.querySelector(".launcher-chrome")).not.toHaveAttribute("aria-hidden");
    expect((container.querySelector(".launcher-main") as HTMLElement).inert).toBe(false);
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

    const enter = screen.getByRole("button", { name: "进入工作区" });
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
