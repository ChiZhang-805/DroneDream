import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ChevronUp,
  Download,
  Gauge,
  History,
  LogOut,
  PackageCheck,
  RadioTower,
  RefreshCw,
  Settings as SettingsIcon,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";

import type { SettingsSurfaceTabId } from "../components/EditionSettingsSurface";
import { UpdateBlockedDialog } from "../components/UpdateBlockedDialog";
import {
  discoverFieldDevices,
  isDesktopRuntime,
  type FieldDeviceDiscoveryReport,
  type FieldParameterSnapshot,
} from "../desktop/bridge";
import { useOptionalAuth } from "../features/auth/AuthContext";
import { useAppUpdaterState } from "../desktop/updaterContext";
import {
  getManagedModelUsage,
  remainingAllowanceRatio,
  type ManagedModelUsageSnapshot,
} from "../features/settings/cloudModelAccess";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import { localeSafeError } from "../i18n/I18nProvider";
import { FIELD_CATALOG, type FieldLocale } from "./catalog";
import {
  FieldAdapterCenter,
  type FieldReadOnlyProtocolEvidence,
} from "./FieldAdapterCenter";
import { FieldAssistantWorkspace } from "./FieldAssistantWorkspace";
import { FieldPreflightWorkspace } from "./FieldPreflightWorkspace";
import { FieldRecoveryWorkspace } from "./FieldRecoveryWorkspace";
import { FieldSettingsDialog } from "./FieldSettingsDialog";
import { FieldTuningWorkspace } from "./FieldTuningWorkspace";
import {
  evaluateFieldSafety,
  FIELD_OBSERVATION_FIXTURES,
  type FieldObservationState,
} from "./safety";
import { hardwareDomainEdition } from "./hardwareDomain";
import "./field.css";

export type FieldPageId = "assistant" | "device" | "compatibility" | "tuning" | "recovery" | "operations";

const COPY = {
  en: {
    skip: "Skip to workspace",
    navField: "Field operations navigation",
    navLab: "Hardware laboratory navigation",
    assistant: "Chatting",
    device: "Device",
    compatibility: "Compatibility",
    tuning: "Tuning",
    recovery: "Recovery",
    operations: "Operations",
    safetyActive: "Safety gates active",
    packs: "Validated packs",
    quorum: "Quorum",
    locked: "Locked",
    settings: "Settings",
    remainingAllowance: "Token",
    account: "Account",
    openAccountMenu: "Open account menu",
    signOut: "Sign out",
    signOutFailed: "Sign out failed. Try again.",
    updateAvailable: "Download update",
    updateProgress: "Updating",
    page: {
      device: "Device & adapters",
      compatibility: "Compatibility",
      tuning: "Autonomous tuning",
      recovery: "Snapshots & rollback",
      operations: "Preflight & control",
    },
    scan: "Discover",
    scanning: "Scanning",
    scanFailed: "Device discovery failed.",
    scanUnavailableField: "Available in the installed Field app",
    scanUnavailableLab: "Available in the installed Lab app",
    source: "Source",
    observation: "Observation",
    observedPorts: "Unopened serial ports",
    noPorts: "None observed",
    deviceId: "Device ID",
    controller: "Controller",
    firmware: "Firmware",
    pack: "Vehicle Pack",
    unavailable: "—",
    selectedPack: "Vehicle Pack",
    selectedController: "Controller",
    evidence: "Compatibility evidence",
    evidenceMissing: "Not available",
    registry: "Vehicle Pack registry",
    tier: "Tier",
    adapter: "Adapter",
    states: {
      offline: "Offline",
      "device-missing": "No device",
      "unknown-device": "Unknown device",
      "firmware-drift": "Firmware drift",
      "recognized-unvalidated": "Unvalidated",
    },
    catalogStatus: {
      validated: "Validated",
      "contract-only": "Contract only",
      planned: "Planned",
      "integrated-contract": "Integrated contract",
    },
  },
  "zh-CN": {
    skip: "跳到工作区",
    navField: "现场作业导航",
    navLab: "真机实验室导航",
    assistant: "调优对话",
    device: "设备",
    compatibility: "兼容性",
    tuning: "调优",
    recovery: "恢复",
    operations: "操作",
    safetyActive: "安全门已启用",
    packs: "已验证机型包",
    quorum: "仲裁",
    locked: "已锁定",
    settings: "设置",
    remainingAllowance: "Token",
    account: "账户",
    openAccountMenu: "打开账户菜单",
    signOut: "退出登录",
    signOutFailed: "退出登录失败，请重试。",
    updateAvailable: "下载更新",
    updateProgress: "正在更新",
    page: {
      device: "设备与适配器",
      compatibility: "兼容性",
      tuning: "自主调优",
      recovery: "快照与回滚",
      operations: "飞前与控制",
    },
    scan: "发现设备",
    scanning: "正在扫描",
    scanFailed: "设备发现失败。",
    scanUnavailableField: "仅在已安装的 Field 应用中可用",
    scanUnavailableLab: "仅在已安装的 Lab 应用中可用",
    source: "来源",
    observation: "观察状态",
    observedPorts: "未打开的串口",
    noPorts: "未发现",
    deviceId: "设备 ID",
    controller: "飞控",
    firmware: "固件",
    pack: "机型包",
    unavailable: "—",
    selectedPack: "机型包",
    selectedController: "飞控",
    evidence: "兼容性证据",
    evidenceMissing: "暂无",
    registry: "机型包注册表",
    tier: "层级",
    adapter: "适配器",
    states: {
      offline: "离线",
      "device-missing": "无设备",
      "unknown-device": "未知设备",
      "firmware-drift": "固件漂移",
      "recognized-unvalidated": "未验证",
    },
    catalogStatus: {
      validated: "已验证",
      "contract-only": "仅完成接口约定",
      planned: "计划中",
      "integrated-contract": "接口已集成",
    },
  },
} as const;

const NAVIGATION = [
  ["assistant", "assistant", Bot],
  ["device", "device", RadioTower],
  ["compatibility", "compatibility", PackageCheck],
  ["tuning", "tuning", SlidersHorizontal],
  ["recovery", "recovery", History],
  ["operations", "operations", ShieldCheck],
] as const;

const FIRST_FIELD_PACK = FIELD_CATALOG.vehiclePacks[0];
if (!FIRST_FIELD_PACK) throw new Error("Field catalog has no compatible Vehicle Pack");

function controllerKey(vendor: string, model: string): string {
  return `${vendor}::${model}`;
}

function savedLocale(): FieldLocale {
  try {
    return window.localStorage.getItem(`dronedream:${hardwareDomainEdition}-hardware-locale`) === "zh-CN"
      ? "zh-CN"
      : "en";
  } catch {
    return "en";
  }
}

function fieldPlanName(value: string | undefined): "Free" | "Plus" | "Pro" | null {
  const normalized = value?.trim().toLocaleLowerCase();
  if (normalized === "plus") return "Plus";
  if (normalized === "pro") return "Pro";
  if (normalized === "free") return "Free";
  return null;
}

export interface FieldAppProps {
  initialLocale?: FieldLocale;
  initialObservationState?: FieldObservationState;
  focusOnMount?: boolean;
  embeddedInLab?: boolean;
  embeddedInConsole?: boolean;
  activePageOverride?: FieldPageId;
}

function FieldPageHeading({
  icon: Icon,
  title,
}: {
  icon: typeof RadioTower;
  title: string;
}) {
  return (
    <header className="field-page-heading">
      <div>
        <Icon aria-hidden="true" />
        <h1>{title}</h1>
      </div>
    </header>
  );
}

function FieldWorkspace({
  initialLocale,
  initialObservationState = "device-missing",
  focusOnMount = false,
  embeddedInLab = false,
  embeddedInConsole = false,
  activePageOverride,
}: FieldAppProps) {
  const presentationEdition = embeddedInLab ? "lab" as const : hardwareDomainEdition;
  const [locale, setLocale] = useState<FieldLocale>(initialLocale ?? savedLocale);
  const [activePage, setActivePage] = useState<FieldPageId>("assistant");
  const [observationState, setObservationState] = useState<FieldObservationState>(initialObservationState);
  const [selectedPackId, setSelectedPackId] = useState(FIRST_FIELD_PACK.packId);
  const [selectedControllerKey, setSelectedControllerKey] = useState(
    controllerKey(
      FIRST_FIELD_PACK.controllers[0]?.vendor ?? "missing",
      FIRST_FIELD_PACK.controllers[0]?.model ?? "missing",
    ),
  );
  const [deviceReport, setDeviceReport] = useState<FieldDeviceDiscoveryReport | null>(null);
  const [deviceScanBusy, setDeviceScanBusy] = useState(false);
  const [deviceScanError, setDeviceScanError] = useState<string | null>(null);
  const [readOnlyEvidence, setReadOnlyEvidence] = useState<FieldReadOnlyProtocolEvidence | null>(null);
  const [latestSnapshot, setLatestSnapshot] = useState<FieldParameterSnapshot | null>(null);
  const [settingsWorkspaceOpen, setSettingsWorkspaceOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] = useState<SettingsSurfaceTabId>("general");
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [signOutPending, setSignOutPending] = useState(false);
  const [signOutError, setSignOutError] = useState(false);
  const [managedUsage, setManagedUsage] = useState<ManagedModelUsageSnapshot | null>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const applicationSurfaceRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);
  const auth = useOptionalAuth();
  const updater = useAppUpdaterState();
  const copy = COPY[locale];
  const navigationLabel = embeddedInLab ? copy.navLab : copy.navField;
  const scanUnavailable = embeddedInLab
    ? copy.scanUnavailableLab
    : copy.scanUnavailableField;
  const observation = FIELD_OBSERVATION_FIXTURES[observationState];
  const decision = useMemo(() => evaluateFieldSafety(observation), [observation]);
  const selectedPack = FIELD_CATALOG.vehiclePacks.find((pack) => pack.packId === selectedPackId)
    ?? FIRST_FIELD_PACK;
  const selectedController = selectedPack.controllers.find(
    (controller) => controllerKey(controller.vendor, controller.model) === selectedControllerKey,
  ) ?? selectedPack.controllers[0];
  const tokenPercent = managedUsage
    ? Math.round(remainingAllowanceRatio(
        managedUsage.usage.remaining_ai_credits,
        managedUsage.plan.included_ai_credits,
      ))
    : null;
  const accountPlan = auth?.account
    ? fieldPlanName(managedUsage?.plan.id)
    : "Local";
  const updateVisible = isDesktopRuntime() && [
    "available",
    "downloading",
    "installing",
  ].includes(updater.status);
  const updateBusy = updater.status === "downloading" || updater.status === "installing";
  const updateProgress = updateBusy
    ? Math.max(0, Math.min(100, Math.round(updater.progress ?? 0)))
    : null;

  useEffect(() => {
    if (!auth?.account) {
      setManagedUsage(null);
      return undefined;
    }
    let active = true;
    void getManagedModelUsage().then((usage) => {
      if (active) setManagedUsage(usage);
    }).catch(() => {
      if (active) setManagedUsage(null);
    });
    return () => {
      active = false;
    };
  }, [auth?.account]);

  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      window.localStorage.setItem(`dronedream:${hardwareDomainEdition}-hardware-locale`, locale);
    } catch {
      // Language persistence has no safety meaning.
    }
  }, [locale]);

  useEffect(() => {
    if (initialLocale) setLocale(initialLocale);
  }, [initialLocale]);

  useEffect(() => {
    if (activePageOverride) setActivePage(activePageOverride);
  }, [activePageOverride]);

  useEffect(() => {
    if (focusOnMount) pageRef.current?.focus({ preventScroll: true });
  }, [focusOnMount]);

  useEffect(() => {
    const applicationSurface = applicationSurfaceRef.current;
    if (!applicationSurface) return undefined;
    const previousInert = applicationSurface.inert;
    applicationSurface.inert = settingsWorkspaceOpen;
    return () => {
      applicationSurface.inert = previousInert;
    };
  }, [settingsWorkspaceOpen]);

  useEffect(() => {
    if (!accountMenuOpen) return undefined;
    const frame = window.requestAnimationFrame(() => {
      accountMenuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    });
    const closeOnOutsidePointer = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (accountMenuRef.current?.contains(target) || settingsButtonRef.current?.contains(target)) return;
      setAccountMenuOpen(false);
      setSignOutError(false);
      window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setAccountMenuOpen(false);
      setSignOutError(false);
      window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
    };
    document.addEventListener("mousedown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("mousedown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [accountMenuOpen]);

  const selectPage = (page: FieldPageId) => {
    setActivePage(page);
    requestAnimationFrame(() => pageRef.current?.focus({ preventScroll: true }));
  };

  const openSettingsWorkspace = (tab: SettingsSurfaceTabId = "general") => {
    setAccountMenuOpen(false);
    setSignOutError(false);
    setSettingsInitialTab(tab);
    setSettingsWorkspaceOpen(true);
  };

  const closeSettingsWorkspace = () => {
    setSettingsWorkspaceOpen(false);
    window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
  };

  const signOut = async () => {
    if (!auth?.account || signOutPending) return;
    setSignOutPending(true);
    setSignOutError(false);
    try {
      await auth.signOut();
      setAccountMenuOpen(false);
      window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
    } catch {
      setSignOutError(true);
    } finally {
      setSignOutPending(false);
    }
  };

  const scanDevices = useCallback(async () => {
    setDeviceScanBusy(true);
    setDeviceScanError(null);
    try {
      setDeviceReport(await discoverFieldDevices());
    } catch (error) {
      setDeviceScanError(localeSafeError(error, locale, {
        zh: COPY["zh-CN"].scanFailed,
        en: COPY.en.scanFailed,
      }));
    } finally {
      setDeviceScanBusy(false);
    }
  }, [locale]);

  const renderDevicePage = () => {
    const title = copy.page.device;
    return (
      <div className="field-page field-device-page">
        <FieldPageHeading icon={RadioTower} title={title} />
        <div className="field-device-dashboard">
          <section className="field-compact-panel field-device-observation-panel">
            <div className="field-panel-toolbar">
              <label>
                <span>{copy.observation}</span>
                <select value={observationState} onChange={(event) => setObservationState(event.target.value as FieldObservationState)}>
                  {Object.keys(FIELD_OBSERVATION_FIXTURES).map((state) => (
                    <option key={state} value={state}>{copy.states[state as FieldObservationState]}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="field-primary-command"
                disabled={!isDesktopRuntime() || deviceScanBusy}
                title={!isDesktopRuntime() ? scanUnavailable : copy.scan}
                onClick={() => void scanDevices()}
              >
                <RefreshCw className={deviceScanBusy ? "field-auth-spinner" : undefined} aria-hidden="true" />
                {deviceScanBusy ? copy.scanning : copy.scan}
              </button>
            </div>
            <dl className="field-device-grid">
              <div><dt>{copy.deviceId}</dt><dd>{observation.deviceId ?? copy.unavailable}</dd></div>
              <div><dt>{copy.controller}</dt><dd>{observation.controller ?? copy.unavailable}</dd></div>
              <div><dt>{copy.firmware}</dt><dd>{observation.firmwareVersion ?? copy.unavailable}</dd></div>
              <div><dt>{copy.pack}</dt><dd>{observation.vehiclePackId ?? copy.unavailable}</dd></div>
            </dl>
            <div className="field-device-port-list" role="status">
              <span>{copy.observedPorts}</span>
              <strong>{deviceReport?.devices.length
                ? deviceReport.devices.map((device) => device.portName).join(" · ")
                : copy.noPorts}</strong>
            </div>
            {deviceScanError ? <p className="field-device-scan-error" role="alert">{deviceScanError}</p> : null}
          </section>
          <div className="field-page-component"><FieldAdapterCenter locale={locale} devices={deviceReport?.devices} onReadOnlyEvidence={setReadOnlyEvidence} /></div>
        </div>
      </div>
    );
  };

  const renderCompatibilityPage = () => {
    const title = copy.page.compatibility;
    return (
      <div className="field-page field-compatibility-page">
        <FieldPageHeading icon={PackageCheck} title={title} />
        <section className="field-compact-panel field-compatibility-controls" data-authority="false">
          <label><span>{copy.selectedPack}</span><select value={selectedPackId} onChange={(event) => {
            const pack = FIELD_CATALOG.vehiclePacks.find((candidate) => candidate.packId === event.target.value) ?? FIRST_FIELD_PACK;
            const controller = pack.controllers[0];
            setSelectedPackId(pack.packId);
            setSelectedControllerKey(controller ? controllerKey(controller.vendor, controller.model) : "missing");
          }}>{FIELD_CATALOG.vehiclePacks.map((pack) => <option key={pack.packId} value={pack.packId}>{pack.displayName[locale]}</option>)}</select></label>
          <label><span>{copy.selectedController}</span><select value={selectedControllerKey} onChange={(event) => setSelectedControllerKey(event.target.value)}>{selectedPack.controllers.map((controller) => <option key={controllerKey(controller.vendor, controller.model)} value={controllerKey(controller.vendor, controller.model)}>{controller.vendor} {controller.model}</option>)}</select></label>
          <div><span>{copy.evidence}</span><strong>{copy.evidenceMissing}</strong></div>
        </section>
        <section className="field-compact-panel field-registry-panel">
          <header><strong>{copy.registry}</strong><span>{FIELD_CATALOG.vehiclePacks.length}</span></header>
          <div className="field-table-scroll"><table aria-label={copy.registry}><thead><tr><th>{copy.pack}</th><th>{copy.controller}</th><th>{copy.tier}</th><th>{copy.adapter}</th></tr></thead><tbody>{FIELD_CATALOG.vehiclePacks.map((pack) => <tr key={pack.packId}><td><strong>{pack.displayName[locale]}</strong><small>{pack.manufacturer}</small></td><td>{pack.controllers.map((controller) => controller.model).join(", ")}</td><td><span className="field-status-pill">{copy.catalogStatus[pack.validationTier as keyof typeof copy.catalogStatus] ?? pack.validationTier}</span></td><td>{copy.catalogStatus[pack.adapterStatus as keyof typeof copy.catalogStatus] ?? pack.adapterStatus}</td></tr>)}</tbody></table></div>
        </section>
      </div>
    );
  };

  const renderActivePage = () => {
    if (activePage === "assistant") {
      return <FieldAssistantWorkspace locale={locale} selectedPackName={selectedPack.displayName[locale]} selectedControllerName={selectedController ? `${selectedController.vendor} ${selectedController.model}` : copy.unavailable} onOpenTuning={() => selectPage("tuning")} />;
    }
    if (activePage === "device") return renderDevicePage();
    if (activePage === "compatibility") return renderCompatibilityPage();
    if (activePage === "tuning") {
      const title = copy.page.tuning;
      return <div className="field-page"><FieldPageHeading icon={SlidersHorizontal} title={title} /><div className="field-page-component"><FieldTuningWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} snapshot={latestSnapshot ?? undefined} /></div></div>;
    }
    if (activePage === "recovery") {
      const title = copy.page.recovery;
      return <div className="field-page"><FieldPageHeading icon={History} title={title} /><div className="field-page-component"><FieldRecoveryWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} device={deviceReport?.devices[0]} evidence={readOnlyEvidence ?? undefined} onSnapshotCreated={setLatestSnapshot} /></div></div>;
    }
    const title = copy.page.operations;
    return <div className="field-page"><FieldPageHeading icon={ShieldCheck} title={title} /><div className="field-page-component"><FieldPreflightWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} snapshot={latestSnapshot ?? undefined} /></div></div>;
  };

  return (
    <div
      className={`field-app${embeddedInLab ? " field-app-embedded-lab" : ""}${embeddedInConsole ? " field-app-embedded-console" : ""}`}
      data-brand-edition={presentationEdition}
      data-authority="false"
      data-validated-pack-count={decision.validatedPackCount}
      data-quorum={decision.threeLayerQuorum}
    >
      <div
        ref={applicationSurfaceRef}
        className="field-application-surface"
        aria-hidden={settingsWorkspaceOpen || undefined}
      >
        <a className="field-skip-link" href="#field-page">{copy.skip}</a>
        <div className="field-layout">
          <aside className="field-sidebar">
            {!embeddedInConsole ? (
              <nav aria-label={navigationLabel}>{NAVIGATION.map(([id, label, Icon]) => <button key={id} type="button" title={copy[label]} aria-label={copy[label]} aria-current={activePage === id ? "page" : undefined} onClick={() => selectPage(id)}><Icon aria-hidden="true" /><span>{copy[label]}</span></button>)}</nav>
            ) : null}
            <div className="field-sidebar-footer">
              <div className="field-sidebar-status" title={`${copy.packs}: 0`}><Wrench aria-hidden="true" /><div><span>{copy.packs}</span><strong>0</strong></div><small>{copy.locked}</small></div>
              {!embeddedInLab && !embeddedInConsole ? (
                <>
                  <button
                    ref={settingsButtonRef}
                    type="button"
                    className="field-sidebar-settings"
                    aria-label={copy.openAccountMenu}
                    title={copy.openAccountMenu}
                    aria-haspopup="menu"
                    aria-expanded={accountMenuOpen}
                    onClick={() => {
                      setSignOutError(false);
                      setAccountMenuOpen((open) => !open);
                    }}
                  >
                    {auth?.account?.avatarUrl ? (
                      <img src={auth.account.avatarUrl} alt="" />
                    ) : (
                      <span className="field-sidebar-settings-avatar" aria-hidden="true">
                        {auth?.account?.displayName?.trim().charAt(0).toUpperCase() || <SettingsIcon />}
                      </span>
                    )}
                    <span className="field-sidebar-account-copy">
                      <strong>{auth?.account?.displayName || copy.settings}</strong>
                      <small>{accountPlan ?? "—"}</small>
                    </span>
                    <ChevronUp aria-hidden="true" />
                  </button>
                  {updateVisible ? (
                    <button
                      type="button"
                      className={`field-sidebar-update${updateBusy ? " is-busy" : ""}`}
                      aria-label={updateProgress === null
                        ? copy.updateAvailable
                        : `${copy.updateProgress} ${updateProgress}%`}
                      title={updateProgress === null
                        ? copy.updateAvailable
                        : `${copy.updateProgress} ${updateProgress}%`}
                      disabled={updateBusy}
                      onClick={() => void updater.installAvailableUpdate()}
                    >
                      {updateProgress === null
                        ? <Download aria-hidden="true" />
                        : <span>{updateProgress}%</span>}
                    </button>
                  ) : null}
                  {accountMenuOpen ? (
                    <div
                      ref={accountMenuRef}
                      className="account-menu-popover"
                      role="menu"
                      aria-label={copy.account}
                    >
                      <button
                        type="button"
                        className="account-menu-row"
                        role="menuitem"
                        onClick={() => openSettingsWorkspace("model")}
                      >
                        <Gauge aria-hidden="true" strokeWidth={1.8} />
                        <span>{copy.remainingAllowance}</span>
                        <strong>{tokenPercent === null ? "—" : `${tokenPercent}%`}</strong>
                      </button>
                      <button
                        type="button"
                        className="account-menu-row"
                        role="menuitem"
                        onClick={() => openSettingsWorkspace("general")}
                      >
                        <SettingsIcon aria-hidden="true" strokeWidth={1.8} />
                        <span>{copy.settings}</span>
                      </button>
                      {auth?.account ? (
                        <button
                          type="button"
                          className="account-menu-row"
                          role="menuitem"
                          disabled={signOutPending}
                          onClick={() => void signOut()}
                        >
                          <LogOut aria-hidden="true" strokeWidth={1.8} />
                          <span>{copy.signOut}</span>
                        </button>
                      ) : null}
                      {signOutError ? <p role="alert">{copy.signOutFailed}</p> : null}
                    </div>
                  ) : null}
                </>
              ) : null}
            </div>
          </aside>
          <main className="field-main" id="field-page">
            <div ref={pageRef} className="field-active-page" tabIndex={-1} data-page={activePage}>{renderActivePage()}</div>
          </main>
        </div>
      </div>
      {settingsWorkspaceOpen ? (
        <div className="app-shell field-settings-workspace-context">
          <div className="settings-workspace-host field-settings-workspace-host">
            <FieldSettingsDialog
              key={settingsInitialTab}
              closeRef={settingsCloseRef}
              initialTab={settingsInitialTab}
              locale={locale}
              onClose={closeSettingsWorkspace}
              onLocaleChange={setLocale}
              presentation="workspace"
            />
          </div>
        </div>
      ) : null}
      <UpdateBlockedDialog
        block={updater.blockedActivity}
        locale={locale}
        onClose={updater.dismissBlockedActivity}
      />
    </div>
  );
}

export function FieldApp(props: FieldAppProps) {
  const auth = useOptionalAuth();
  return (
    <ModelAccessProvider accountScope={`${props.embeddedInLab ? "lab" : hardwareDomainEdition}:${auth?.account?.id ?? "local"}`}>
      <FieldWorkspace {...props} />
    </ModelAccessProvider>
  );
}
