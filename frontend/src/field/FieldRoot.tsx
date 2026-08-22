import { Settings } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { DroneLaunchSceneCore } from "../components/DroneLaunchScene";
import { FieldAuthControl } from "./FieldAuthControl";
import { FieldBrandLockup } from "./FieldBrandLockup";
import { useFieldLocale } from "./FieldLocaleProvider";
import { FieldSettingsDialog } from "./FieldSettingsDialog";
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
    settings: "Open settings",
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
    settings: "打开设置",
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
  settingsOpen,
  onSettingsOpen,
  onSettingsClose,
}: {
  locale: FieldLocale;
  progress: number;
  onEnter: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
  settingsOpen: boolean;
  onSettingsOpen: () => void;
  onSettingsClose: () => void;
}) {
  const copy = COPY[locale];
  const ready = progress === 100;
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);
  const closeSettings = () => {
    onSettingsClose();
    window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
  };
  return (
    <div
      className="app-shell app-shell-launcher field-launcher"
      data-authority="false"
      data-launch-ready={ready ? "true" : "false"}
    >
      <header className="launcher-chrome">
        <div className="launcher-brand" aria-label={copy.brand}>
          <FieldBrandLockup />
        </div>
        <div className="launcher-chrome-actions">
          <span className={`launcher-runtime-indicator${ready ? " is-checked" : ""}`}>
            <span aria-hidden="true" />
            {ready ? copy.ready : copy.loading}
          </span>
          <button
            ref={settingsButtonRef}
            className="launcher-settings-button"
            type="button"
            aria-label={copy.settings}
            aria-haspopup="dialog"
            aria-expanded={settingsOpen}
            onClick={onSettingsOpen}
          >
            <Settings aria-hidden="true" strokeWidth={1.85} />
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
      {settingsOpen ? (
        <div
          className="launcher-settings-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeSettings();
          }}
        >
          <FieldSettingsDialog
            closeRef={settingsCloseRef}
            locale={locale}
            onClose={closeSettings}
            onLocaleChange={onLocaleChange}
          />
        </div>
      ) : null}
    </div>
  );
}

export function FieldRoot() {
  const { locale, setLocale } = useFieldLocale();
  const [entered, setEntered] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    let active = true;
    const minimumStageDurationMs = 600;
    const wait = (milliseconds: number) => new Promise<void>((resolve) => {
      window.setTimeout(resolve, milliseconds);
    });
    const nextFrame = () => new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => resolve());
    });
    const advance = async (percent: number, check: () => Promise<void> | void) => {
      const startedAt = performance.now();
      await check();
      await wait(Math.max(0, minimumStageDurationMs - (performance.now() - startedAt)));
      if (!active) throw new DOMException("Field readiness cancelled", "AbortError");
      setProgress(percent);
    };
    const run = async () => {
      setProgress(0);
      await advance(8, async () => {
        await nextFrame();
        await nextFrame();
      });
      await advance(20, async () => {
        if ("fonts" in document) await document.fonts.ready;
      });
      let loadedModule: typeof import("./FieldApp") | null = null;
      await advance(38, async () => {
        loadedModule = await import("./FieldApp");
      });
      await advance(54, () => {
        if (!loadedModule || typeof loadedModule.FieldApp !== "function") {
          throw new Error("FIELD_WORKSPACE_MODULE_INVALID");
        }
      });
      await advance(68, () => {
        if (document.documentElement.dataset.brandEdition !== "field") {
          throw new Error("FIELD_BRAND_CONTRACT_MISSING");
        }
      });
      await advance(80, () => {
        const style = getComputedStyle(document.documentElement);
        if (!style.getPropertyValue("--dd-brand-start").trim()) {
          throw new Error("FIELD_THEME_CONTRACT_MISSING");
        }
      });
      await advance(91, () => {
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
        if (!context) throw new Error("FIELD_3D_RUNTIME_UNAVAILABLE");
        context.getExtension("WEBGL_lose_context")?.loseContext();
      });
      await advance(100, nextFrame);
    };
    void run().catch((reason: unknown) => {
      if (active && !(reason instanceof DOMException && reason.name === "AbortError")) {
        // Readiness fails closed at 0%. The launcher never reveals a sign-in
        // action until every product, localization, theme and 3D gate passes.
        setProgress(0);
      }
    });
    return () => {
      active = false;
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
      settingsOpen={settingsOpen}
      onSettingsOpen={() => setSettingsOpen(true)}
      onSettingsClose={() => setSettingsOpen(false)}
    />
  );
}
