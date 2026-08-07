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
