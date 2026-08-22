import { FieldLocaleProvider, useFieldLocale } from "./FieldLocaleProvider";

const COPY = {
  en: {
    "launcher.tagline": "Let Every Flight Flow Like a Dream",
    "launcher.telemetry.system": "REAL DEVICE DOMAIN",
    "launcher.telemetry.linkActive": "SAFETY GATES ACTIVE",
    "launcher.telemetry.standby": "SAFE STANDBY",
    "launcher.telemetry.attitude": "ATTITUDE",
    "launcher.telemetry.hold": "HOLD",
    "launcher.telemetry.cruise": "STARFLIGHT",
  },
  "zh-CN": {
    "launcher.tagline": "蝶 梦 水 云 乡",
    "launcher.telemetry.system": "真机工作域",
    "launcher.telemetry.linkActive": "安全门已启用",
    "launcher.telemetry.standby": "安全待机",
    "launcher.telemetry.attitude": "飞行姿态",
    "launcher.telemetry.hold": "悬停",
    "launcher.telemetry.cruise": "星际巡航",
  },
} as const;

type FieldLaunchTranslationKey = keyof typeof COPY.en;
const HAN_PATTERN = /\p{Script=Han}/u;

export { FieldLocaleProvider as I18nProvider };

// This profile shim satisfies the shared 3D launcher's translation interface
// without pulling simulation and Runtime dictionaries into the Field bundle.
// eslint-disable-next-line react-refresh/only-export-components
export function useI18n() {
  const { locale, setLocale } = useFieldLocale();
  return {
    locale,
    setLocale,
    t: (key: FieldLaunchTranslationKey) => COPY[locale][key],
  };
}

// FIELD is built as an intentionally small standalone bundle and aliases the
// full console I18n provider to this file. Keep the shared error-localization
// contract available here as well so hardware diagnostics never leak Chinese
// into the English UI (or arbitrary English prose into the Chinese UI).
// eslint-disable-next-line react-refresh/only-export-components
export function localeSafeError(
  value: unknown,
  locale: "en" | "zh-CN",
  fallback: { zh: string; en: string },
): string {
  const raw = value instanceof Error ? value.message : String(value ?? "");
  const normalized = raw.trim();
  const english = locale === "en";
  const localizedFallback = english ? fallback.en : fallback.zh;
  if (!normalized) return localizedFallback;

  const technicalCode = /^[A-Z0-9_.:-]+$/u.test(normalized);
  if (english) {
    if (HAN_PATTERN.test(normalized)) return localizedFallback;
    return technicalCode ? `${localizedFallback} (${normalized})` : normalized;
  }
  if (HAN_PATTERN.test(normalized)) return normalized;
  return technicalCode ? `${localizedFallback}（${normalized}）` : localizedFallback;
}
