import { describe, expect, it } from "vitest";

import {
  BRAND_GRANTS_HARDWARE_AUTHORITY,
  BRAND_PRESENTATION_ONLY,
  EDITION_BRAND_TOKENS,
} from "../brand/edition-brand.generated";
import { EDITION_THEMES } from "../theme/editionTheme";

describe("canonical Edition theme contract", () => {
  it("derives every CSS and 3D palette from the generated canonical manifest", () => {
    for (const [edition, expected] of Object.entries(EDITION_BRAND_TOKENS)) {
      const theme = EDITION_THEMES[edition as keyof typeof EDITION_THEMES];
      expect(theme.gradientStops).toEqual(expected.gradientStops);
      expect(theme.lightSurface).toBe(expected.lightSurface);
      expect(theme.darkSurface).toBe(expected.darkSurface);
      expect(theme.three.primary).toBe(Number.parseInt(expected.gradientStops[0].slice(1), 16));
      expect(theme.three.secondary).toBe(Number.parseInt(expected.gradientStops[1].slice(1), 16));
      expect(theme.three.tertiary).toBe(Number.parseInt(expected.gradientStops[2].slice(1), 16));
      expect(theme.three.darkSurface).toBe(Number.parseInt(expected.darkSurface.slice(1), 16));
    }
  });

  it("makes the entire theme system presentation-only and incapable of granting hardware authority", () => {
    expect(BRAND_PRESENTATION_ONLY).toBe(true);
    expect(BRAND_GRANTS_HARDWARE_AUTHORITY).toBe(false);
    for (const theme of Object.values(EDITION_THEMES)) {
      expect(theme.presentationOnly).toBe(true);
      expect(theme.grantsHardwareAuthority).toBe(false);
    }
  });
});
