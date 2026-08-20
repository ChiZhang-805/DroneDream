import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UniversalModeSwitch } from "../components/UniversalModeSwitch";
import {
  applyUniversalMode,
  loadUniversalMode,
  parseUniversalMode,
  persistUniversalMode,
  UNIVERSAL_MODE_STORAGE_KEY,
} from "../features/distribution/universalMode";

describe("UniversalModeSwitch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.brandEdition;
    delete document.documentElement.dataset.productMode;
    delete document.documentElement.dataset.themePresentationOnly;
    delete document.documentElement.dataset.themeGrantsHardwareAuthority;
  });

  it("fails unknown persisted values back to the SIM workspace", () => {
    expect(parseUniversalMode("unknown")).toBe("sim");
    expect(parseUniversalMode("autonomy")).toBe("autonomy");
    expect(loadUniversalMode()).toBe("sim");
  });

  it("persists and applies a presentation-only mode without changing install selection", () => {
    window.localStorage.setItem("dronedream:distribution-selection:v1", "frozen-selection");
    persistUniversalMode("field");
    applyUniversalMode("field");

    expect(window.localStorage.getItem(UNIVERSAL_MODE_STORAGE_KEY)).toBe("field");
    expect(window.localStorage.getItem("dronedream:distribution-selection:v1"))
      .toBe("frozen-selection");
    expect(document.documentElement.dataset.brandEdition).toBe("field");
    expect(document.documentElement.dataset.productMode).toBe("field");
    expect(document.documentElement.dataset.themePresentationOnly).toBe("true");
    expect(document.documentElement.dataset.themeGrantsHardwareAuthority).toBe("false");
  });

  it("offers Universal and four integrated product workspaces without granting authority", () => {
    const onChange = vi.fn();
    const onOpenUniversal = vi.fn();
    const { container } = render(
      <UniversalModeSwitch
        mode="sim"
        activeEdition="universal"
        locale="en"
        onChange={onChange}
        onOpenUniversal={onOpenUniversal}
      />,
    );

    const region = container.querySelector(".universal-mode-switch");
    expect(region).toHaveAttribute("data-presentation-only", "true");
    expect(region).toHaveAttribute("data-grants-hardware-authority", "false");
    expect(screen.getAllByRole("option")).toHaveLength(5);
    expect(screen.getByRole("option", { name: "DroneDream" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "DroneDream · AUTONOMY" }))
      .toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Workspace mode" })).toHaveValue("universal");

    fireEvent.change(screen.getByRole("combobox", { name: "Workspace mode" }), {
      target: { value: "lab" },
    });
    expect(onChange).toHaveBeenCalledWith("lab");

    fireEvent.change(screen.getByRole("combobox", { name: "Workspace mode" }), {
      target: { value: "autonomy" },
    });
    expect(onChange).toHaveBeenCalledWith("autonomy");

    fireEvent.change(screen.getByRole("combobox", { name: "Workspace mode" }), {
      target: { value: "universal" },
    });
    expect(onOpenUniversal).toHaveBeenCalledOnce();
  });

  it("authors the Chinese safety boundary independently", () => {
    render(<UniversalModeSwitch mode="sim" locale="zh-CN" onChange={() => undefined} />);
    expect(screen.getByText(/这里只切换工作区/)).toBeInTheDocument();
    expect(screen.getByText(/不会启动 Model \+ Harness/)).toBeInTheDocument();
  });
});
