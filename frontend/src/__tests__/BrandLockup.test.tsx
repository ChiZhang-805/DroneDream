import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import fieldLockup from "../../../brand/commercial/field-lockup.png";
import labLockup from "../../../brand/commercial/lab-lockup.png";
import simLockup from "../../../brand/commercial/sim-lockup.png";
import universalLockup from "../../../brand/commercial/universal-lockup.png";
import { BrandLockup } from "../components/BrandLockup";

describe("BrandLockup", () => {
  it.each([
    ["universal", universalLockup],
    ["sim", simLockup],
    ["lab", labLockup],
    ["field", fieldLockup],
  ] as const)("renders the %s natural-width asset from the frontend build context", (
    edition,
    source,
  ) => {
    const { container } = render(<BrandLockup edition={edition} />);
    const image = container.querySelector("img");

    expect(image).not.toBeNull();
    expect(image).toHaveAttribute("src", source);
    expect(image).toHaveClass("brand-lockup", "brand-lockup-primary");
    expect(image).toHaveAttribute("aria-hidden", "true");
    expect(image).toHaveAttribute("data-brand-edition", edition);
  });

  it("keeps Universal as the canonical backwards-compatible default", () => {
    const { container } = render(<BrandLockup />);

    expect(container.querySelector("img")).toHaveAttribute("src", universalLockup);
    expect(container.querySelector("img")).toHaveAttribute("data-brand-edition", "universal");
  });
});
