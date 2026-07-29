import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import compactLockup from "../assets/drone-dream-lockup-compact.png";
import primaryLockup from "../assets/drone-dream-lockup-primary.png";
import { BrandLockup } from "../components/BrandLockup";

describe("BrandLockup", () => {
  it.each([
    ["primary", primaryLockup],
    ["compact", compactLockup],
  ] as const)("renders the %s asset from the frontend build context", (variant, source) => {
    const { container } = render(<BrandLockup variant={variant} />);
    const image = container.querySelector("img");

    expect(image).not.toBeNull();
    expect(image).toHaveAttribute("src", source);
    expect(image).toHaveClass("brand-lockup", `brand-lockup-${variant}`);
    expect(image).toHaveAttribute("aria-hidden", "true");
  });
});
