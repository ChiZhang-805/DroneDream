import { Settings } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { LauncherFlightIllustration } from "../components/LauncherFlightIllustration";
import { LauncherAccountForm } from "../components/LauncherAccountForm";
import type { SettingsSurfaceTabId } from "../components/EditionSettingsSurface";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
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
    settings: "Open settings",
    illustrationTitle: "Ready for takeoff",
    illustrationDescription: "",
    cardKicker: "FIELD STARTUP",
    cardTitle: "Starting workspace",
    stages: ["Check system", "Start device services", "Connect services", "Open workspace"],
  },
  "zh-CN": {
    brand: "DroneDream · FIELD",
    loading: "正在启动工作区",
    ready: "Field 工作区已就绪",
    settings: "打开设置",
    illustrationTitle: "无人机校园插画",
    illustrationDescription: "",
    cardKicker: "FIELD 启动",
    cardTitle: "正在启动工作区",
    stages: ["检查系统", "启动设备服务", "连接服务", "进入工作区"],
  },
} as const;

function FieldLaunchScreen({
  backgroundInactive,
  locale,
  progress,
  onEnter,
  onAuthenticated,
  onLocaleChange,
  settingsOpen,
  onSettingsOpen,
  onSettingsClose,
  onOpenSettingsWorkspace,
}: {
  backgroundInactive: boolean;
  locale: FieldLocale;
  progress: number;
  onEnter: () => void;
  onAuthenticated: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
  settingsOpen: boolean;
  onSettingsOpen: () => void;
  onSettingsClose: () => void;
  onOpenSettingsWorkspace: (tab: SettingsSurfaceTabId) => void;
}) {
  const { account } = useAuthOrLocal();
  const copy = COPY[locale];
  const ready = progress === 100;
  const activeStage = ready ? 4 : progress < 25 ? 0 : progress < 60 ? 1 : progress < 95 ? 2 : 3;
  const launcherChromeRef = useRef<HTMLElement>(null);
  const launcherMainRef = useRef<HTMLElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);
  const closeSettings = useCallback(() => {
    onSettingsClose();
    window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
  }, [onSettingsClose]);
  useEffect(() => {
    if (!settingsOpen) return undefined;
    const frame = window.requestAnimationFrame(() => settingsCloseRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>(".quick-settings-dialog");
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      )];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeSettings, settingsOpen]);
  useEffect(() => {
    const inactive = settingsOpen || backgroundInactive;
    const surfaces = [launcherChromeRef.current, launcherMainRef.current].filter(
      (surface): surface is HTMLElement => Boolean(surface),
    );
    const previousOverflow = document.body.style.overflow;
    for (const surface of surfaces) surface.inert = inactive;
    if (inactive) document.body.style.overflow = "hidden";
    return () => {
      for (const surface of surfaces) surface.inert = false;
      document.body.style.overflow = previousOverflow;
    };
  }, [backgroundInactive, settingsOpen]);
  return (
    <div
      className="app-shell app-shell-launcher field-launcher"
      data-authority="false"
      data-launch-ready={ready ? "true" : "false"}
    >
      <header
        ref={launcherChromeRef}
        className="launcher-chrome"
        aria-hidden={settingsOpen || backgroundInactive || undefined}
      >
        <div className="launcher-brand" aria-label={copy.brand}>
          <FieldBrandLockup />
        </div>
        <div className="launcher-chrome-actions">
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
      <main
        ref={launcherMainRef}
        className="launcher-main"
        aria-hidden={settingsOpen || backgroundInactive || undefined}
      >
        <div className="desktop-launcher">
          <div className="launcher-hero">
            <div className="launcher-hero-visual">
              <LauncherFlightIllustration
                active={!ready}
                description={copy.illustrationDescription}
                progress={progress}
                title={copy.illustrationTitle}
              />
            </div>
            <div className="launcher-progress-panel">
              {!account ? <LauncherAccountForm locale={locale} onAuthenticated={onAuthenticated} /> : <>
              <div className="launcher-status-card-heading">
                <span>{copy.cardKicker}</span>
                <h2>{copy.cardTitle}</h2>
              </div>
              <ol className="launcher-stage-list" aria-label={copy.loading}>
                {copy.stages.map((stage, index) => (
                  <li
                    className={index < activeStage ? "is-complete" : index === activeStage ? "is-current" : ""}
                    aria-current={index === activeStage ? "step" : undefined}
                    key={stage}
                  >
                    <span aria-hidden="true">{index < activeStage ? "✓" : index + 1}</span>
                    <strong>{stage}</strong>
                  </li>
                ))}
              </ol>
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
              <div className="launcher-card-actions">
                <button className="btn btn-primary" disabled={!ready} onClick={onEnter}>
                  {locale === "zh-CN" ? "进入工作区" : "Enter workspace"}
                </button>
              </div>
              </>}
            </div>
          </div>
        </div>
      </main>
      {settingsOpen ? (
        <div
          className="launcher-settings-backdrop quick-settings-backdrop"
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
            onOpenWorkspace={onOpenSettingsWorkspace}
            presentation="quick"
          />
        </div>
      ) : null}
    </div>
  );
}

export function FieldRoot() {
  const { locale, setLocale } = useFieldLocale();
  const { account } = useAuthOrLocal();
  const [entered, setEntered] = useState(false);
  const [authCompleted, setAuthCompleted] = useState(false);
  const [settingsPresentation, setSettingsPresentation] = useState<
    "closed" | "quick" | "workspace"
  >("closed");
  const [settingsInitialTab, setSettingsInitialTab] = useState<SettingsSurfaceTabId>("general");
  const [progress, setProgress] = useState(0);
  const settingsWorkspaceCloseRef = useRef<HTMLButtonElement>(null);
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
        // Readiness fails closed at 0%. Inline sign-in cannot open the workspace
        // until every product, localization, theme and 3D gate passes.
        setProgress(0);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  if (entered || (authCompleted && account && progress === 100)) {
    return (
      <Suspense fallback={null}>
        <FieldApp
          initialLocale={locale}
          focusOnMount
          onSignedOut={() => {
            setEntered(false);
            setAuthCompleted(false);
            setSettingsPresentation("closed");
          }}
        />
      </Suspense>
    );
  }
  const openSettingsWorkspace = (tab: SettingsSurfaceTabId) => {
    setSettingsInitialTab(tab);
    setSettingsPresentation("workspace");
  };
  const closeSettingsWorkspace = () => {
    setSettingsPresentation("closed");
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>(".launcher-settings-button")?.focus();
    });
  };
  return (
    <ModelAccessProvider accountScope={`field:${account?.id ?? "local"}`}>
      <FieldLaunchScreen
        backgroundInactive={settingsPresentation === "workspace"}
        locale={locale}
        progress={progress}
        onEnter={() => setEntered(true)}
        onAuthenticated={() => setAuthCompleted(true)}
        onLocaleChange={setLocale}
        settingsOpen={settingsPresentation === "quick"}
        onSettingsOpen={() => setSettingsPresentation("quick")}
        onSettingsClose={() => setSettingsPresentation("closed")}
        onOpenSettingsWorkspace={openSettingsWorkspace}
      />
      {settingsPresentation === "workspace" ? (
        <div className="app-shell field-settings-workspace-context">
          <div className="settings-workspace-host field-settings-workspace-host">
            <FieldSettingsDialog
              key={settingsInitialTab}
              closeRef={settingsWorkspaceCloseRef}
              initialTab={settingsInitialTab}
              locale={locale}
              onClose={closeSettingsWorkspace}
              onLocaleChange={setLocale}
              presentation="workspace"
            />
          </div>
        </div>
      ) : null}
    </ModelAccessProvider>
  );
}
