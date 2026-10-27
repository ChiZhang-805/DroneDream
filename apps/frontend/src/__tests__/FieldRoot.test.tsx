import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FieldLocaleProvider } from "../field/FieldLocaleProvider";

const fieldAuth = vi.hoisted(() => ({
  account: { id: "field-pilot" } as { id: string } | null,
}));

vi.mock("../features/auth/AuthContext", async (importOriginal) => ({
  ...await importOriginal<typeof import("../features/auth/AuthContext")>(),
  useAuthOrLocal: () => ({
    account: fieldAuth.account,
    configured: true,
    signInWithPassword: async () => { fieldAuth.account = { id: "field-pilot" }; },
  }),
}));

vi.mock("../field/FieldApp", () => ({
  FieldApp: ({
    initialLocale,
    focusOnMount,
    onSignedOut,
  }: {
    initialLocale: string;
    focusOnMount: boolean;
    onSignedOut: () => void;
  }) => (
    <div data-testid="field-workspace" data-locale={initialLocale} data-focus-on-mount={String(focusOnMount)}>
      <button type="button" onClick={onSignedOut}>Sign out probe</button>
    </div>
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
    fieldAuth.account = { id: "field-pilot" };
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

  it("uses the shared raster illustration and four readiness steps before entry", async () => {
    vi.useFakeTimers();
    const { container } = render(
      <FieldLocaleProvider>
        <FieldRoot />
      </FieldLocaleProvider>,
    );

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("button", { name: "Enter workspace" })).toBeDisabled();
    expect(container.querySelector("img.launcher-flight-image"))
      .toHaveAttribute("src", expect.stringMatching(/launcher-campus(?:-(?:universal|sim|lab|field))?\.png/u));
    expect(container.querySelector("canvas, .drone-launch-scene")).toBeNull();
    expect([...container.querySelectorAll(".launcher-stage-list strong")].map((node) => node.textContent))
      .toEqual(["Check system", "Start device services", "Connect services", "Open workspace"]);
    expect(container.querySelector('.launcher-stage-list [aria-current="step"]'))
      .toHaveTextContent("Check system");

    await finishLoading();

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enter workspace" })).toBeEnabled();
    expect(container.querySelectorAll(".launcher-stage-list .is-complete")).toHaveLength(4);
    expect(container.querySelector('.launcher-stage-list [aria-current="step"]')).toBeNull();
    expect(container.firstChild).toHaveAttribute("data-authority", "false");
    expect(container).not.toHaveTextContent(/PX4|Gazebo|SITL|HITL/i);

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    const quickSettings = screen.getByRole("dialog", { name: "Settings" });
    expect(quickSettings).toHaveAttribute("data-settings-consumer", "field");
    expect(quickSettings.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(container.querySelector(".launcher-chrome")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".launcher-main")).toHaveAttribute("aria-hidden", "true");
    expect((container.querySelector(".launcher-main") as HTMLElement).inert).toBe(true);
    expect(screen.queryByRole("button", { name: "All settings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Runtime/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Models/ }));
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
    fieldAuth.account = null;
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
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "pilot@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-password" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "登录" }));
      await Promise.resolve();
    });
    // A successful account response cannot skip the workspace readiness checks.
    expect(screen.queryByTestId("field-workspace")).not.toBeInTheDocument();
    await finishLoading();

    expect(screen.getByTestId("field-workspace"))
      .toHaveAttribute("data-locale", "zh-CN");
    expect(screen.getByTestId("field-workspace"))
      .toHaveAttribute("data-focus-on-mount", "true");
  });

  it("keeps entry blocked when the Field brand contract fails", async () => {
    vi.useFakeTimers();
    delete document.documentElement.dataset.brandEdition;
    render(<FieldLocaleProvider><FieldRoot /></FieldLocaleProvider>);
    await finishLoading();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("button", { name: "Enter workspace" })).toBeDisabled();
    expect(screen.queryByTestId("field-workspace")).not.toBeInTheDocument();
  });

  it("returns to the Field launch screen after signing out", async () => {
    vi.useFakeTimers();
    render(<FieldLocaleProvider><FieldRoot /></FieldLocaleProvider>);
    await finishLoading();
    fireEvent.click(screen.getByRole("button", { name: "Enter workspace" }));
    expect(screen.getByTestId("field-workspace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sign out probe" }));
    expect(screen.queryByTestId("field-workspace")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enter workspace" })).toBeVisible();
  });

});
