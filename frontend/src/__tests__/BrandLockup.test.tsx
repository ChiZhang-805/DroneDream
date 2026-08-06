import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import fieldPrimaryLockup from "../assets/brand/field-lockup-primary.png";
import labPrimaryLockup from "../assets/brand/lab-lockup-primary.png";
import simCompactLockup from "../assets/brand/sim-lockup-compact.png";
import universalPrimaryLockup from "../assets/brand/universal-lockup-primary.png";
import { BrandLockup } from "../components/BrandLockup";

describe("BrandLockup", () => {
  it.each([
    ["universal", "primary", universalPrimaryLockup],
    ["sim", "compact", simCompactLockup],
    ["lab", "primary", labPrimaryLockup],
    ["field", "primary", fieldPrimaryLockup],
  ] as const)("renders the %s %s asset from the frontend build context", (
    edition,
    variant,
    source,
  ) => {
    const { container } = render(<BrandLockup edition={edition} variant={variant} />);
    const image = container.querySelector("img");

    expect(image).not.toBeNull();
    expect(image).toHaveAttribute("src", source);
    expect(image).toHaveClass("brand-lockup", `brand-lockup-${variant}`);
    expect(image).toHaveAttribute("aria-hidden", "true");
    expect(image).toHaveAttribute("data-brand-edition", edition);
  });

  it("keeps Universal as the canonical backwards-compatible default", () => {
    const { container } = render(<BrandLockup />);

    expect(container.querySelector("img")).toHaveAttribute("src", universalPrimaryLockup);
    expect(container.querySelector("img")).toHaveAttribute("data-brand-edition", "universal");
  });
});
