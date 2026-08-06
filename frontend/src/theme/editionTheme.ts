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

export type EditionTheme = Readonly<{
  id: BrandEditionId;
  productName: string;
  gradientStops: readonly [string, string, string];
  lightSurface: string;
  darkSurface: string;
  presentationOnly: true;
  grantsHardwareAuthority: false;
  three: EditionTheme3D;
}>;

function hexColorNumber(value: string): number {
  if (!/^#[0-9a-f]{6}$/iu.test(value)) {
    throw new Error(`Invalid canonical brand color: ${value}`);
  }
  return Number.parseInt(value.slice(1), 16);
}

function createTheme(id: BrandEditionId): EditionTheme {
  const token = EDITION_BRAND_TOKENS[id];
  const [primary, secondary, tertiary] = token.gradientStops;
  const darkSurface = hexColorNumber(token.darkSurface);
  return Object.freeze({
    id,
    productName: token.productName,
    gradientStops: token.gradientStops,
    lightSurface: token.lightSurface,
    darkSurface: token.darkSurface,
    presentationOnly: BRAND_PRESENTATION_ONLY,
    grantsHardwareAuthority: BRAND_GRANTS_HARDWARE_AUTHORITY,
    three: Object.freeze({
      primary: hexColorNumber(primary),
      secondary: hexColorNumber(secondary),
      tertiary: hexColorNumber(tertiary),
      darkSurface,
      fog: darkSurface,
      gridMinor: hexColorNumber(secondary),
    }),
  });
}

export const EDITION_THEMES = Object.freeze({
  universal: createTheme("universal"),
  sim: createTheme("sim"),
  lab: createTheme("lab"),
  field: createTheme("field"),
}) satisfies Readonly<Record<BrandEditionId, EditionTheme>>;

export function editionTheme(id: BrandEditionId): EditionTheme {
  return EDITION_THEMES[id];
}
