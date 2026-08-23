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
    "updater.current": "DroneDream is up to date. Click to check again.",
    "updater.checking": "Checking for updates…",
    "updater.available": "Version {{version}} is available. Click to update.",
    "updater.installing": "Installing the update and restarting DroneDream…",
    "updater.error": "The update failed. Click to retry.",
    "updater.engine": "Updating the DroneDream engine…",
    "updater.engineDeferred": "The engine update will resume after active experiments finish.",
    "updater.components": "Updating DroneDream workflows and assets…",
    "updater.runtimeBaseRequired": "A one-time Runtime Base upgrade is required before Engine Pack updates can be used.",
    "settings.updates.title": "Software updates",
    "settings.updates.description": "Application, Runtime, Engine Pack, workflow, and asset updates.",
    "settings.updates.checkNow": "Check for updates",
    "settings.updates.currentHint": "Runtime and signed packs were checked with this application.",
    "settings.updates.checkingHint": "Checking each update layer in dependency order.",
    "settings.updates.required": "Required",
    "settings.updates.recommended": "Recommended",
    "settings.updates.optional": "Optional",
    "settings.updates.automatic": "Automatic",
    "settings.updates.requiredHint": "This update must finish before the workspace can open.",
    "settings.updates.recommendedHint": "Install when convenient; it does not block your work.",
    "settings.updates.optionalHint": "Choose whether to install this signed update.",
    "settings.updates.automaticHint": "DroneDream applies this signed update automatically when the Runtime is idle.",
    "settings.updates.deferredHint": "Finish active experiments, then retry.",
    "settings.updates.retryHint": "No changes were applied. Check the connection and retry.",
    "settings.updates.inProgressHint": "Keep DroneDream open until this step finishes.",
    "settings.updates.downloading": "Downloading the application update…",
    "settings.updates.engineError": "The Engine Pack update could not finish.",
    "settings.updates.packsAvailable": "Workflow and asset updates are ready.",
    "settings.updates.packsDeferred": "Pack updates are waiting for the Runtime.",
    "settings.updates.packsError": "Pack updates could not finish.",
    "settings.updates.runtimeBaseHint": "Install the compatible Runtime Base, then return here.",
    "settings.updates.installApp": "Install update",
    "settings.updates.installPacks": "Install pack updates",
    "settings.updates.retry": "Retry",
    "settings.updates.openRuntimeBase": "Upgrade Runtime Base",
    "settings.updates.progressLabel": "Update progress",
    "settings.updates.packList": "Available pack updates",
    "settings.updates.capabilityPack": "Workflow pack",
    "settings.updates.assetPack": "Asset pack",
  },
  "zh-CN": {
    "launcher.tagline": "蝶 梦 水 云 乡",
    "launcher.telemetry.system": "真机工作域",
    "launcher.telemetry.linkActive": "安全门已启用",
    "launcher.telemetry.standby": "安全待机",
    "launcher.telemetry.attitude": "飞行姿态",
    "launcher.telemetry.hold": "悬停",
    "launcher.telemetry.cruise": "星际巡航",
    "updater.current": "DroneDream 已是最新版本，点击可再次检查。",
    "updater.checking": "正在检查更新……",
    "updater.available": "发现新版本 {{version}}，点击即可更新。",
    "updater.installing": "正在安装更新并重新启动 DroneDream……",
    "updater.error": "更新失败，点击可重试。",
    "updater.engine": "正在更新 DroneDream 引擎…",
    "updater.engineDeferred": "当前实验结束后将继续引擎更新。",
    "updater.components": "正在更新 DroneDream 工作流与资源……",
    "updater.runtimeBaseRequired": "使用 Engine Pack 更新前，需要进行一次 Runtime Base 升级。",
    "settings.updates.title": "软件更新",
    "settings.updates.description": "集中查看软件、Runtime、Engine Pack、工作流与资源更新。",
    "settings.updates.checkNow": "检查更新",
    "settings.updates.currentHint": "已按当前软件版本检查 Runtime 与签名组件包。",
    "settings.updates.checkingHint": "正在按依赖顺序检查各层更新。",
    "settings.updates.required": "必需",
    "settings.updates.recommended": "建议",
    "settings.updates.optional": "可选",
    "settings.updates.automatic": "自动",
    "settings.updates.requiredHint": "必须完成此更新，才能进入工作区。",
    "settings.updates.recommendedHint": "可在方便时安装，不会阻断当前工作。",
    "settings.updates.optionalHint": "可自行决定是否安装此签名更新。",
    "settings.updates.automaticHint": "Runtime 空闲时，DroneDream 会自动应用此签名更新。",
    "settings.updates.deferredHint": "请先结束当前实验，再重试。",
    "settings.updates.retryHint": "未应用任何更改，请检查连接后重试。",
    "settings.updates.inProgressHint": "请保持 DroneDream 打开，直至此步骤完成。",
    "settings.updates.downloading": "正在下载软件更新……",
    "settings.updates.engineError": "Engine Pack 更新未能完成。",
    "settings.updates.packsAvailable": "工作流与资源更新已就绪。",
    "settings.updates.packsDeferred": "组件包更新正在等待 Runtime 空闲。",
    "settings.updates.packsError": "组件包更新未能完成。",
    "settings.updates.runtimeBaseHint": "请安装兼容的 Runtime Base，然后返回此处。",
    "settings.updates.installApp": "安装更新",
    "settings.updates.installPacks": "安装组件包更新",
    "settings.updates.retry": "重试",
    "settings.updates.openRuntimeBase": "升级 Runtime Base",
    "settings.updates.progressLabel": "更新进度",
    "settings.updates.packList": "可用的组件包更新",
    "settings.updates.capabilityPack": "工作流包",
    "settings.updates.assetPack": "资源包",
  },
} as const;

type FieldTranslationKey = keyof typeof COPY.en;
type FieldTranslationValues = Record<string, string | number>;
const HAN_PATTERN = /\p{Script=Han}/u;

export { FieldLocaleProvider as I18nProvider };

function interpolate(template: string, values: FieldTranslationValues = {}): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{{${key}}}`, String(value)),
    template,
  );
}

// This profile shim keeps the Field launcher and shared update center bilingual
// without pulling the full console dictionary into the standalone bundle.
// eslint-disable-next-line react-refresh/only-export-components
export function useI18n() {
  const { locale, setLocale } = useFieldLocale();
  return {
    locale,
    setLocale,
    t: (key: FieldTranslationKey, values?: FieldTranslationValues) =>
      interpolate(COPY[locale][key], values),
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
