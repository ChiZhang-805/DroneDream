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

    expect(screen.getByText("· FIELD")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Field navigation" }))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("heading", { name: "Field readiness" }))
      .toBeInTheDocument();
    expect(screen.getByText("0 / 7")).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-validated-pack-count='0']")).toBeTruthy();
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
    for (const name of [
      "Create snapshot",
      "Apply rollback",
      "Request takeover",
      "Emergency stop",
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("renders all seven Field-compatible packs and no authority action", () => {
    render(<FieldApp initialLocale="en" />);

    expect(screen.getAllByRole("row")).toHaveLength(8);
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Holybro X500 v2 with Pixhawk 6")).toBeInTheDocument();
    expect(table.getByText("Bitcraze Crazyflie 2.1+")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /arm|flight/i })).not.toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Apply rollback" })).toBeDisabled();
  });

  it("provides independent Simplified Chinese safety copy", () => {
    render(<FieldApp initialLocale="zh-CN" initialObservationState="firmware-drift" />);

    expect(screen.getByRole("heading", { name: "真机就绪状态" })).toBeInTheDocument();
    expect(screen.getByText("固件漂移")).toBeInTheDocument();
    expect(screen.getByText("当前没有达到硬件验证层级的机型包。设备观察结果不能解锁控制权限。"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用回滚" })).toBeDisabled();
  });

  it("keeps the Field entry independent from the unified app routes", () => {
    const sources = [
      "src/field/FieldApp.tsx",
      "src/field/catalog.ts",
      "src/field/main.tsx",
      "src/field/safety.ts",
    ].map((path) => readFileSync(resolve(process.cwd(), path), "utf8")).join("\n");

    expect(sources).not.toMatch(/AppShell|react-router|\/assistant|\/scenarios/);
    expect(sources).not.toMatch(/gazebo|sitl|hitl|simulation/i);
  });

  it("parses the responsive Field stylesheet with complete custom properties", () => {
    const source = readFileSync(resolve(process.cwd(), "src/field/field.css"), "utf8");
    const root = postcss.parse(source, { from: "field.css" });
    const defined = new Set<string>();
    const referenced = new Set<string>();

    root.walkDecls((declaration) => {
      if (declaration.prop.startsWith("--")) defined.add(declaration.prop);
      for (const match of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
        if (match[1]) referenced.add(match[1]);
      }
    });

    expect([...referenced].filter((name) => !defined.has(name))).toEqual([]);
    expect(source).toContain("@media (max-width: 920px)");
    expect(source).toContain("@media (max-width: 560px)");
    expect(source).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
