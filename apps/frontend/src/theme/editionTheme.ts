import {
  BRAND_GRANTS_HARDWARE_AUTHORITY,
  BRAND_PRESENTATION_ONLY,
  EDITION_BRAND_TOKENS,
  type BrandEditionId,
} from "../brand/edition-brand.generated";

export type EditionTheme3D = Readonly<{
  primary: number;
  secondary: number;
  tertiary: number;
  darkSurface: number;
  fog: number;
  gridMinor: number;
}>;

export type AppearanceMode = "dark" | "light";

export type EditionTheme = Readonly<{
  id: BrandEditionId;
  productName: string;
  gradientStops: readonly [string, string, string];
  lightSurface: string;
  darkSurface: string;
  appearance: AppearanceMode;
  presentationOnly: true;
  grantsHardwareAuthority: false;
  three: EditionTheme3D;
}>;

/** Convert a validated six-digit canonical color to the integer format expected by Three.js. */
function hexColorNumber(value: string): number {
  if (!/^#[0-9a-f]{6}$/iu.test(value)) {
    throw new Error(`Invalid canonical brand color: ${value}`);
  }
  return Number.parseInt(value.slice(1), 16);
}

/** Derive one immutable display palette, keeping runtime objects separate from generated source tokens. */
function createTheme(id: BrandEditionId, appearance: AppearanceMode = "dark"): EditionTheme {
  const token = EDITION_BRAND_TOKENS[id];
  const [primary, secondary, tertiary] = token.gradientStops;
  const sceneSurface = hexColorNumber(
    appearance === "dark" ? token.darkSurface : token.lightSurface,
  );
  return Object.freeze({
    id,
    productName: token.productName,
    gradientStops: Object.freeze([...token.gradientStops] as [string, string, string]),
    lightSurface: token.lightSurface,
    darkSurface: token.darkSurface,
    appearance,
    presentationOnly: BRAND_PRESENTATION_ONLY,
    grantsHardwareAuthority: BRAND_GRANTS_HARDWARE_AUTHORITY,
    three: Object.freeze({
      primary: hexColorNumber(primary),
      secondary: hexColorNumber(secondary),
      tertiary: hexColorNumber(tertiary),
      darkSurface: sceneSurface,
      fog: sceneSurface,
      gridMinor: hexColorNumber(secondary),
    }),
  });
}

export const EDITION_THEMES = Object.freeze({
  universal: createTheme("universal"),
  sim: createTheme("sim"),
  lab: createTheme("lab"),
  field: createTheme("field"),
  autonomy: createTheme("autonomy"),
}) satisfies Readonly<Record<BrandEditionId, EditionTheme>>;

/** Return a cached dark palette; it contains no model, subscription, or hardware permissions. */
export function editionTheme(id: BrandEditionId): EditionTheme {
  return EDITION_THEMES[id];
}

/** Recompute light/dark scene surfaces from the same canonical edition colors. */
export function editionThemeForAppearance(
  id: BrandEditionId,
  appearance: AppearanceMode,
): EditionTheme {
  return createTheme(id, appearance);
}
