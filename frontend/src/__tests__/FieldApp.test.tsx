import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import postcss from "postcss";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as cloudModels from "../features/settings/cloudModelAccess";
import { FieldApp } from "../field/FieldApp";
import type { FieldObservationState } from "../field/safety";

async function renderField(
  locale: "en" | "zh-CN" = "en",
  observationState: FieldObservationState = "device-missing",
  focusOnMount = false,
) {
  const result = render(
    <FieldApp
      initialLocale={locale}
      initialObservationState={observationState}
      focusOnMount={focusOnMount}
    />,
  );
  await waitFor(() => {
    expect(screen.getByRole("combobox", { name: locale === "en" ? "Model" : "模型" }))
      .toBeDisabled();
  });
  return result;
}

describe("FieldApp", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(cloudModels, "getManagedModelCatalog").mockResolvedValue({
      generated_at: "2026-08-08T00:00:00Z",
      models: [],
    });
  });

  it("opens Chatting first and exposes six true page controls", async () => {
    const { container } = await renderField();

    expect(container.querySelector(".field-brand")).toHaveAttribute(
      "aria-label",
      "DroneDream · FIELD",
    );
    const navigation = screen.getByRole("navigation", { name: "Field navigation" });
    expect(within(navigation).getAllByRole("button")).toHaveLength(6);
    expect(within(navigation).getByRole("button", { name: "Chatting" }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "What real-device experiment should we prepare?" }))
      .toBeInTheDocument();
    expect(container.querySelector(".field-sidebar nav a")).toBeNull();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-validated-pack-count='0']")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start controlled test" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("moves launcher focus to the active page without granting authority", async () => {
    const { container } = await renderField("en", "device-missing", true);

    expect(container.querySelector(".field-active-page")).toHaveFocus();
    expect(container.querySelector(".field-active-page")).toHaveAttribute("data-page", "assistant");
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
  });

  it("switches pages instead of scrolling to sections", async () => {
    const { container } = await renderField();

    fireEvent.click(screen.getByRole("button", { name: "Device" }));
    expect(screen.getByRole("heading", { name: "Device & adapters" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What real-device experiment should we prepare?" }))
      .not.toBeInTheDocument();
    expect(container.querySelector(".field-active-page")).toHaveAttribute("data-page", "device");

    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(screen.getByRole("heading", { name: "Preflight & control" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();
  });

  it("exposes read-only observations without verbose empty-state narration", async () => {
    const { container } = await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Device" }));

    fireEvent.change(screen.getByRole("combobox", { name: "Observation" }), {
      target: { value: "unknown-device" },
    });

    expect(screen.getByText("demo:unknown-controller")).toBeInTheDocument();
    expect(screen.getByText("Unknown controller")).toBeInTheDocument();
    expect(screen.queryByText("The observed identity is absent from the source-bound registry."))
      .not.toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
  });

  it("renders all seven Field-compatible packs on the compatibility page", async () => {
    await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Compatibility" }));

    const table = within(screen.getByRole("table", { name: "Vehicle Pack registry" }));
    expect(table.getAllByRole("row")).toHaveLength(8);
    expect(table.getByText("Holybro X500 v2 with Pixhawk 6")).toBeInTheDocument();
    expect(table.getByText("Bitcraze Crazyflie 2.1+")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(?:arm|flight)$/i })).not.toBeInTheDocument();
  });

  it("shows protocol choices only on the device page and never grants authority", async () => {
    const { container } = await renderField();
    expect(screen.queryByRole("table", { name: "Protocol adapters" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Device" }));

    const table = within(screen.getByRole("table", { name: "Protocol adapters" }));
    expect(table.getAllByRole("row")).toHaveLength(12);
    expect(table.getByText("MAVLink Common")).toBeInTheDocument();
    expect(table.getByText("Betaflight / INAV MSP")).toBeInTheDocument();
    expect(table.getByText("DroneCAN v1")).toBeInTheDocument();
    expect(table.getByText("DJI Enterprise SDK")).toBeInTheDocument();
    expect(container.querySelector("#adapters[data-authority='false']")).toBeTruthy();
    expect(table.getAllByRole("button", { name: "Install" })
      .every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  });

  it("keeps compatibility selections local and fail-closed", async () => {
    const { container } = await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Compatibility" }));

    fireEvent.change(screen.getByRole("combobox", { name: "Vehicle Pack" }), {
      target: { value: "bitcraze-crazyflie-2-1-plus" },
    });

    expect(screen.getByRole("combobox", { name: "Controller" }))
      .toHaveValue("Bitcraze::Crazyflie 2.1+");
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(container.querySelector(".field-compatibility-controls[data-authority='false']"))
      .toBeTruthy();
  });

  it("keeps operator acknowledgement outside the authority path", async () => {
    const { container } = await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Operations" }));

    fireEvent.click(screen.getByRole("checkbox", { name: /I confirm the declared zone/ }));

    expect(screen.getByText("Local only")).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
  });

  it("provides independent Simplified Chinese page navigation", async () => {
    await renderField("zh-CN", "firmware-drift");

    expect(screen.getByRole("button", { name: "Chatting" }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "想准备怎样的真机调优实验？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "设备" }));
    expect(screen.getByRole("heading", { name: "设备与适配器" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "观察状态" })).toHaveValue("firmware-drift");
  });

  it("keeps the Field entry independent and free of non-Field execution payloads", () => {
    const sources = [
      "src/field/FieldApp.tsx",
      "src/field/FieldAssistantWorkspace.tsx",
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
    expect(sources).toContain('data-authority="false"');
  });

  it("opens shared settings without changing authority", async () => {
    const { container } = await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const dialog = screen.getByRole("dialog", { name: "Field settings" });
    expect(dialog).toHaveAttribute("data-brand-edition", "field");
    expect(dialog).toHaveAttribute("data-settings-consumer", "field-lightweight");
    expect(dialog).toHaveAttribute("data-presentation-only", "true");
    expect(dialog).toHaveAttribute("data-grants-hardware-authority", "false");
    fireEvent.click(within(dialog).getByRole("tab", { name: "Safety" }));
    expect(within(dialog).getByText("field-lightweight")).toBeInTheDocument();
    expect(within(dialog).getByText("Denied")).toBeInTheDocument();
    expect(container.querySelector("[data-quorum='missing']")).toBeTruthy();
  });

  it("switches EN/ZH inside Settings and closes with Escape", async () => {
    await renderField();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Simplified Chinese" }));

    expect(screen.getByRole("dialog", { name: "Field 设置" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses canonical theme tokens and fixed viewport page layout", () => {
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
    expect(fieldSource).toContain("height: 100vh");
    expect(fieldSource).toContain("overflow: hidden");
    for (const token of [
      "--dd-brand-start",
      "--dd-brand-middle",
      "--dd-brand-end",
      "--dd-brand-light-surface",
      "--dd-brand-dark-surface",
    ]) expect(fieldSource).toContain(`var(${token})`);
  });
});
