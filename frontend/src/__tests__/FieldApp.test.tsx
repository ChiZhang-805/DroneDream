import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import postcss from "postcss";
import { beforeEach, describe, expect, it } from "vitest";

import { FieldApp } from "../field/FieldApp";

describe("FieldApp", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders a Field-only navigation and fail-closed overview", () => {
    const { container } = render(<FieldApp initialLocale="en" />);

    expect(container.querySelector(".field-brand")).toHaveAttribute(
      "aria-label",
      "DroneDream · FIELD",
    );
    expect(screen.getByRole("navigation", { name: "Field navigation" }))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("heading", { name: "Real-device operations and autonomous tuning" }))
      .toBeInTheDocument();
    expect(screen.getByText("0 / 7")).toBeInTheDocument();
    expect(container.querySelector(".field-brand-lockup")).toHaveAttribute(
      "data-brand-edition",
      "field",
    );
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-validated-pack-count='0']")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in to DroneDream · FIELD" }))
      .toBeDisabled();
  });

  it("moves launcher entry focus to the workspace title without granting authority", () => {
    const { container } = render(<FieldApp initialLocale="en" focusOnMount />);
    const heading = screen.getByRole("heading", {
      name: "Real-device operations and autonomous tuning",
    });

    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
  });

  it("updates only the visual navigation selection", () => {
    const { container } = render(<FieldApp initialLocale="en" />);

    fireEvent.click(screen.getByRole("link", { name: "Preflight" }));

    expect(screen.getByRole("link", { name: "Preflight" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();
  });

  it("exposes observation fixtures without enabling hardware commands", () => {
    render(<FieldApp initialLocale="en" />);

    fireEvent.change(screen.getByRole("combobox", { name: "Observation state" }), {
      target: { value: "unknown-device" },
    });

    expect(screen.getByText("demo:unknown-controller")).toBeInTheDocument();
    expect(screen.getByText("Unknown controller")).toBeInTheDocument();
    expect(screen.getByText("The observed identity is absent from the source-bound registry."))
      .toBeInTheDocument();
    for (const name of [
      "Save snapshot",
      "Compare drift",
      "Prepare rollback",
      "Request takeover",
      "Emergency stop",
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it.each([
    ["offline", "Offline mode has no cached device observation."],
    ["device-missing", "No device is present in the read-only observation."],
    ["firmware-drift", "The observed firmware is outside the compatibility contract."],
    [
      "recognized-unvalidated",
      "Identity and firmware matches do not satisfy the validation tier.",
    ],
  ] as const)("renders the %s negative observation reason", (state, reason) => {
    render(<FieldApp initialLocale="en" initialObservationState={state} />);

    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
  });

  it("renders all seven Field-compatible packs and no authority action", () => {
    render(<FieldApp initialLocale="en" />);

    const table = within(screen.getByRole("table", { name: "Vehicle Pack registry" }));
    expect(table.getAllByRole("row")).toHaveLength(8);
    expect(table.getByText("Holybro X500 v2 with Pixhawk 6")).toBeInTheDocument();
    expect(table.getByText("Bitcraze Crazyflie 2.1+")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /arm|flight/i })).not.toBeInTheDocument();
  });

  it("shows protocol choices without granting authority in browser preview", () => {
    const { container } = render(<FieldApp initialLocale="en" />);
    const table = within(screen.getByRole("table", { name: "Protocol adapters" }));

    expect(table.getAllByRole("row")).toHaveLength(12);
    expect(table.getByText("MAVLink Common")).toBeInTheDocument();
    expect(table.getByText("Betaflight / INAV MSP")).toBeInTheDocument();
    expect(table.getByText("DroneCAN v1")).toBeInTheDocument();
    expect(table.getByText("Tello SDK State")).toBeInTheDocument();
    expect(table.getByText("DJI Enterprise SDK")).toBeInTheDocument();
    expect(screen.getByText(/support offline inspection/i)).toBeInTheDocument();
    expect(screen.getByText(/one bounded, operator-confirmed read-only serial probe/i))
      .toBeInTheDocument();
    expect(container.querySelector("#adapters[data-authority='false']")).toBeTruthy();
    expect(table.getAllByRole("button", { name: "Install" })
      .every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  });

  it("keeps compatibility selections local and fail-closed", () => {
    const { container } = render(<FieldApp initialLocale="en" />);

    fireEvent.change(screen.getByRole("combobox", { name: "Selected Vehicle Pack" }), {
      target: { value: "bitcraze-crazyflie-2-1-plus" },
    });

    expect(screen.getByRole("combobox", { name: "Selected controller" })).toHaveValue(
      "Bitcraze::Crazyflie 2.1+",
    );
    expect(screen.getByText("No signed compatibility evidence")).toBeInTheDocument();
    expect(container.querySelector(".field-compatibility-draft[data-authority='false']"))
      .toBeTruthy();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
  });

  it("keeps local operator acknowledgement outside the authority path", () => {
    const { container } = render(<FieldApp initialLocale="en" />);

    fireEvent.click(screen.getByRole("checkbox", {
      name: /I acknowledge the Field preview safety boundary/,
    }));

    expect(screen.getByText("Local only")).toBeInTheDocument();
    expect(screen.getByText(/not signed evidence/)).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Prepare rollback" })).toBeDisabled();
  });

  it("provides independent Simplified Chinese safety copy", () => {
    render(<FieldApp initialLocale="zh-CN" initialObservationState="firmware-drift" />);

    expect(screen.getByRole("heading", { name: "真机操作与自主调参" })).toBeInTheDocument();
    expect(within(screen.getByRole("status")).getByText("固件漂移"))
      .toBeInTheDocument();
    expect(screen.getByText("当前没有达到硬件验证层级的机型包。设备观察结果不能解锁控制权限。"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "准备回滚" })).toBeDisabled();
  });

  it("keeps the Field entry independent from the unified app routes", () => {
    const sources = [
      "src/field/FieldApp.tsx",
      "src/field/FieldSettingsDialog.tsx",
      "src/field/FieldRecoveryWorkspace.tsx",
      "src/field/FieldTuningWorkspace.tsx",
      "src/field/FieldRoot.tsx",
      "src/field/catalog.ts",
      "src/field/main.tsx",
      "src/field/safety.ts",
      "src/field/tuning.ts",
    ].map((path) => readFileSync(resolve(process.cwd(), path), "utf8")).join("\n");

    expect(sources).not.toMatch(/AppShell|react-router|\/assistant|\/scenarios/);
    expect(sources).not.toMatch(/gazebo|sitl|hitl|SimulatorAdapter|simulation\.execute/i);
    expect(sources).toContain("EditionThemeProvider");
    expect(sources).toContain("EditionSettingsSurface");
    expect(sources).toContain("DroneLaunchScene");
    expect(sources).toContain('consumerProfile="field-lightweight"');
  });

  it("opens the shared Field settings surface without changing authority", () => {
    const { container } = render(<FieldApp initialLocale="en" />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const dialog = screen.getByRole("dialog", { name: "Field settings" });
    expect(dialog).toHaveAttribute("data-brand-edition", "field");
    expect(dialog).toHaveAttribute("data-settings-consumer", "field-lightweight");
    expect(dialog).toHaveAttribute("data-presentation-only", "true");
    expect(dialog).toHaveAttribute("data-grants-hardware-authority", "false");
    expect(container.querySelector("[data-validated-pack-count='0']")).toBeTruthy();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("tab", { name: "Safety" }));
    expect(within(dialog).getByText("field-lightweight")).toBeInTheDocument();
    expect(within(dialog).getByText("Denied")).toBeInTheDocument();
    expect(within(dialog).getByText("0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
  });

  it("switches EN/ZH inside Settings and closes with Escape", () => {
    render(<FieldApp initialLocale="en" />);
    const trigger = screen.getByRole("button", { name: "Settings" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Simplified Chinese" }));

    expect(screen.getByRole("dialog", { name: "Field 设置" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("consumes canonical theme tokens without redefining a Field palette", () => {
    const fieldSource = readFileSync(resolve(process.cwd(), "src/field/field.css"), "utf8");
    const generatedSource = readFileSync(
      resolve(process.cwd(), "src/brand/edition-brand.generated.css"),
      "utf8",
    );
    const root = postcss.parse(`${generatedSource}\n${fieldSource}`, { from: "field.css" });
    const defined = new Set<string>();
    const referenced = new Set<string>();

    root.walkDecls((declaration) => {
      if (declaration.prop.startsWith("--")) defined.add(declaration.prop);
      for (const match of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
        if (match[1]) referenced.add(match[1]);
      }
    });

    expect([...referenced].filter((name) => !defined.has(name))).toEqual([]);
    expect(fieldSource).not.toMatch(/--field-(yellow|coral|pink|surface|dark)/);
    expect(fieldSource).not.toMatch(/#ffc247|#ff754b|#d746a5|#fff8ef|#28140d/i);
    for (const token of [
      "--dd-brand-start",
      "--dd-brand-middle",
      "--dd-brand-end",
      "--dd-brand-light-surface",
      "--dd-brand-dark-surface",
    ]) {
      expect(fieldSource).toContain(`var(${token})`);
    }
    expect(fieldSource).toContain("@media (max-width: 920px)");
    expect(fieldSource).toContain("@media (max-width: 560px)");
    expect(fieldSource).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
