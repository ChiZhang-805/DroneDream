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

  it("offers Universal and all integrated workspaces in a checked popup menu", () => {
    const onChange = vi.fn();
    const { container } = render(
      <UniversalModeSwitch
        mode="sim"
        activeEdition="universal"
        locale="en"
        onChange={onChange}
      />,
    );

    const region = container.querySelector(".universal-mode-switch");
    expect(region).toHaveAttribute("data-presentation-only", "true");
    expect(region).toHaveAttribute("data-grants-hardware-authority", "false");
    const trigger = screen.getByRole("button", { name: "Switch DroneDream edition" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(screen.getAllByRole("menuitemradio")).toHaveLength(4);
    expect(screen.getByRole("menuitemradio", { name: "DroneDream" }))
      .toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("menuitemradio", { name: "DroneDream · LAB" }));
    expect(onChange).toHaveBeenCalledWith("lab");

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "DroneDream" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("switches back to Universal from an integrated workspace", () => {
    const onChange = vi.fn();
    render(
      <UniversalModeSwitch
        mode="sim"
        locale="en"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch DroneDream edition" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "DroneDream" }));
    expect(onChange).toHaveBeenCalledWith("universal");
  });

  it("provides an independently authored Chinese switch label", () => {
    render(<UniversalModeSwitch mode="sim" locale="zh-CN" onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "切换 DroneDream 版本" })).toBeInTheDocument();
  });
});
