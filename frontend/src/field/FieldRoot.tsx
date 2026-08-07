import { lazy, Suspense, useEffect, useState } from "react";

import { DroneLaunchSceneCore } from "../components/DroneLaunchScene";
import { FieldAuthControl } from "./FieldAuthControl";
import { FieldBrandLockup } from "./FieldBrandLockup";
import { useFieldLocale } from "./FieldLocaleProvider";
import type { FieldLocale } from "./catalog";

const FieldApp = lazy(async () => {
  const module = await import("./FieldApp");
  return { default: module.FieldApp };
});

const COPY = {
  en: {
    brand: "DroneDream · FIELD",
    loading: "Preparing the real-device tuning workspace",
    ready: "Field workspace ready",
    system: "REAL DEVICE DOMAIN",
    active: "SAFETY GATES ACTIVE",
    standby: "SAFE STANDBY",
    language: "Switch to Simplified Chinese",
    tagline: "Let Every Flight Flow Like a Dream",
    attitude: "ATTITUDE",
    hold: "HOLD",
    cruise: "STARFLIGHT",
  },
  "zh-CN": {
    brand: "DroneDream · FIELD",
    loading: "正在准备真机调优工作区",
    ready: "Field 工作区已就绪",
    system: "真机工作域",
    active: "安全门已启用",
    standby: "安全待机",
    language: "切换到 English",
    tagline: "蝶 梦 水 云 乡",
    attitude: "飞行姿态",
    hold: "悬停",
    cruise: "星际巡航",
  },
} as const;

function FieldLaunchScreen({
  locale,
  progress,
  onEnter,
  onLocaleChange,
}: {
  locale: FieldLocale;
  progress: number;
  onEnter: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
}) {
  const copy = COPY[locale];
  const ready = progress === 100;
  return (
    <div
      className="app-shell-launcher field-launcher"
      data-authority="false"
      data-launch-ready={ready ? "true" : "false"}
    >
      <header className="launcher-chrome">
        <div className="launcher-brand" aria-label={copy.brand}>
          <FieldBrandLockup variant="compact" />
        </div>
        <div className="launcher-chrome-actions">
          <span className={`launcher-runtime-indicator${ready ? " is-checked" : ""}`}>
            <span aria-hidden="true" />
            {ready ? copy.ready : copy.loading}
          </span>
          <button
            className="field-launcher-language"
            type="button"
            aria-label={copy.language}
            title={copy.language}
            onClick={() => onLocaleChange(locale === "en" ? "zh-CN" : "en")}
          >
            {locale === "en" ? "中" : "EN"}
          </button>
        </div>
      </header>
      <main className="launcher-main">
        <div className="desktop-launcher">
          <div className="launcher-hero">
            <div className="launcher-hero-visual">
              <DroneLaunchSceneCore
                active={ready}
                progress={progress}
                labels={{
                  locale,
                  tagline: copy.tagline,
                  system: copy.system,
                  active: copy.active,
                  standby: copy.standby,
                  attitude: copy.attitude,
                  hold: copy.hold,
                  cruise: copy.cruise,
                }}
              />
            </div>
            {ready ? (
              <div className="launcher-ready-actions">
                <FieldAuthControl
                  launcher
                  launcherReady
                  locale={locale}
                  onAuthenticated={onEnter}
                />
              </div>
            ) : null}
            <div className="launcher-progress-panel" role="status" aria-live="polite">
              <div
                className="launcher-progress-track"
                role="progressbar"
                aria-label={copy.loading}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress}
              >
                <span style={{ width: `${progress}%` }} />
              </div>
              <div className="launcher-progress-footer">
                <strong className="launcher-compact-status">
                  {ready ? copy.ready : copy.loading}
                </strong>
                <span className="launcher-progress-percent">{progress}%</span>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export function FieldRoot() {
  const { locale, setLocale } = useFieldLocale();
  const [progress, setProgress] = useState(8);
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    let active = true;
    const timers = [
      window.setTimeout(() => active && setProgress(36), 180),
      window.setTimeout(() => active && setProgress(68), 460),
      window.setTimeout(() => active && setProgress(88), 760),
    ];
    const fontsReady = "fonts" in document
      ? document.fonts.ready.catch(() => undefined)
      : Promise.resolve();
    void Promise.all([
      fontsReady,
      import("./FieldApp"),
      new Promise<void>((resolve) => window.setTimeout(resolve, 1_050)),
    ]).then(() => {
      if (active) setProgress(100);
    });
    return () => {
      active = false;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  if (entered) {
    return (
      <Suspense fallback={null}>
        <FieldApp initialLocale={locale} focusOnMount />
      </Suspense>
    );
  }
  return (
    <FieldLaunchScreen
      locale={locale}
      progress={progress}
      onEnter={() => setEntered(true)}
      onLocaleChange={setLocale}
    />
  );
}
