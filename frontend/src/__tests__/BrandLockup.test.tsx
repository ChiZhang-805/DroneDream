import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import compactLockup from "../assets/drone-dream-lockup-compact.png";
import primaryLockup from "../assets/drone-dream-lockup-primary.png";
import labDotLockup from "../../../distribution/editions/lab/assets/dronedream-lab-dot-lockup-v2.png";
import { BrandLockup } from "../components/BrandLockup";
import { resolveBrandLockupSource } from "../components/brandAssets";

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

  it.each(["primary", "compact"] as const)(
    "uses the approved Lab dot lockup for the %s variant",
    (variant) => {
      expect(resolveBrandLockupSource("lab", variant)).toBe(labDotLockup);
    },
  );
});
