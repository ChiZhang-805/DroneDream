import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  CircleOff,
  ClipboardCheck,
  FileClock,
  Gauge,
  PackageOpen,
  PackageCheck,
  RadioTower,
  RefreshCw,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import {
  discoverFieldDevices,
  isDesktopRuntime,
  type FieldDeviceDiscoveryReport,
  type FieldParameterSnapshot,
} from "../desktop/bridge";
import { FIELD_CATALOG, type FieldLocale } from "./catalog";
import {
  FieldAdapterCenter,
  type FieldReadOnlyProtocolEvidence,
} from "./FieldAdapterCenter";
import { FieldAuthControl } from "./FieldAuthControl";
import { FieldBrandLockup } from "./FieldBrandLockup";
import { FieldSettingsDialog } from "./FieldSettingsDialog";
import { FieldRecoveryWorkspace } from "./FieldRecoveryWorkspace";
import { FieldPreflightWorkspace } from "./FieldPreflightWorkspace";
import { FieldTuningWorkspace } from "./FieldTuningWorkspace";
import {
  evaluateFieldSafety,
  FIELD_OBSERVATION_FIXTURES,
  type FieldObservationState,
} from "./safety";

const COPY = {
  en: {
    skip: "Skip to Field overview",
    edition: "FIELD",
    preview: "Safety-gated field workspace",
    locale: "Language",
    settings: "Settings",
    nav: "Field navigation",
    overview: "Overview",
    devices: "Device",
    compatibility: "Compatibility",
    adapters: "Protocol adapters",
    tuning: "Autonomous tuning",
    recovery: "Snapshot & rollback",
    preflight: "Preflight",
    control: "Safety control",
    title: "Real-device operations and autonomous tuning",
    subtitle: "Connect, observe, tune, qualify, recover, and operate supported aircraft without a simulation stage.",
    zeroTitle: "Hardware authority unavailable",
    zeroBody: "No Vehicle Pack has a validated hardware tier. Device observations cannot unlock control.",
    validated: "Validated packs",
    quorum: "Three-layer quorum",
    source: "Observation source",
    sourceValue: "Built-in read-only fixture",
    scan: "Scan serial registry",
    scanning: "Scanning...",
    scanBoundary: "Read-only registry scan. Ports remain closed.",
    scanUnavailable: "Native scan is available only in the installed Field app.",
    observedPorts: "Observed unopened ports",
    noPorts: "No serial ports observed",
    observation: "Observation state",
    states: {
      offline: "Offline",
      "device-missing": "No device",
      "unknown-device": "Unknown device",
      "firmware-drift": "Firmware drift",
      "recognized-unvalidated": "Recognized, unvalidated",
    },
    stateDetail: {
      offline: "Offline mode has no cached device observation.",
      "device-missing": "No device is present in the read-only observation.",
      "unknown-device": "The observed identity is absent from the source-bound registry.",
      "firmware-drift": "The observed firmware is outside the compatibility contract.",
      "recognized-unvalidated": "Identity and firmware matches do not satisfy the validation tier.",
    },
    deviceTitle: "Device observation",
    deviceBody: "Observation is informational and never grants authority.",
    deviceId: "Device ID",
    controller: "Controller",
    firmware: "Firmware",
    pack: "Vehicle Pack",
    unavailable: "Unavailable",
    registryTitle: "Vehicle Pack registry",
    registryBody: "Field-compatible entries projected from the source-bound 8-pack registry.",
    compatibilityDraft: "Compatibility draft",
    selectedPack: "Selected Vehicle Pack",
    selectedController: "Selected controller",
    firmwareEvidence: "Firmware evidence",
    firmwareEvidenceMissing: "No signed compatibility evidence",
    draftBoundary: "Selection is local preview data and does not grant authority.",
    packName: "Vehicle Pack",
    controllers: "Controller contract",
    tier: "Validation tier",
    adapter: "Adapter",
    preflightTitle: "Preflight quorum",
    preflightBody: "Operator confirmation is one input. It cannot replace native, policy, or runtime approval.",
    zone: "Operating zone",
    confirmation: "Operator confirmation",
    nativeGate: "Native safety gate",
    runtimeGate: "Runtime gate",
    missing: "Missing",
    localOnly: "Local only",
    operatorAcknowledgement: "I acknowledge the Field preview safety boundary.",
    operatorBoundary: "This local acknowledgement is not signed evidence and cannot authorize hardware.",
    controlTitle: "Takeover & emergency",
    controlBody: "Control commands remain unavailable while the hardware safety contract is incomplete.",
    takeover: "Request takeover",
    emergency: "Emergency stop",
    actionMatrix: "Denied hardware actions",
    denied: "Denied",
    action: {
      "parameter-write": "Parameter write",
      "rollback-apply": "Rollback apply",
      takeover: "Takeover",
      "emergency-stop": "Emergency stop",
      arm: "Arm",
      flight: "Flight",
    },
    footer: "DroneDream · FIELD 1.0.0 · real-device workspace",
  },
  "zh-CN": {
    skip: "跳到 Field 概览",
    edition: "FIELD",
    preview: "安全门控真机工作区",
    locale: "语言",
    settings: "设置",
    nav: "Field 导航",
    overview: "概览",
    devices: "设备",
    compatibility: "兼容性",
    adapters: "协议适配器",
    tuning: "自主调参",
    recovery: "快照与回滚",
    preflight: "飞前检查",
    control: "安全控制",
    title: "真机操作与自主调参",
    subtitle: "在完全无仿真的工作流中连接、观察、调参、验证、恢复并操作受支持的无人机。",
    zeroTitle: "真机权限不可用",
    zeroBody: "当前没有达到硬件验证层级的机型包。设备观察结果不能解锁控制权限。",
    validated: "已验证机型包",
    quorum: "三层仲裁",
    source: "观察来源",
    sourceValue: "内置只读测试数据",
    scan: "扫描串口注册表",
    scanning: "正在扫描...",
    scanBoundary: "仅只读扫描注册表，所有端口保持关闭。",
    scanUnavailable: "原生扫描仅在已安装的 Field 应用中可用。",
    observedPorts: "观察到的未打开端口",
    noPorts: "未观察到串口",
    observation: "观察状态",
    states: {
      offline: "离线",
      "device-missing": "无设备",
      "unknown-device": "未知设备",
      "firmware-drift": "固件漂移",
      "recognized-unvalidated": "已识别，未验证",
    },
    stateDetail: {
      offline: "离线模式下没有可用的设备观察缓存。",
      "device-missing": "只读观察中没有设备。",
      "unknown-device": "观察到的设备身份不在源绑定注册表中。",
      "firmware-drift": "观察到的固件超出兼容性合同范围。",
      "recognized-unvalidated": "设备身份与固件匹配仍未达到验证层级。",
    },
    deviceTitle: "设备观察",
    deviceBody: "观察结果仅供查看，永远不授予控制权限。",
    deviceId: "设备 ID",
    controller: "飞控",
    firmware: "固件",
    pack: "机型包",
    unavailable: "不可用",
    registryTitle: "机型包注册表",
    registryBody: "来自源绑定 8-pack 注册表的 Field 兼容条目。",
    compatibilityDraft: "兼容性草稿",
    selectedPack: "所选机型包",
    selectedController: "所选飞控",
    firmwareEvidence: "固件证据",
    firmwareEvidenceMissing: "缺少签名兼容性证据",
    draftBoundary: "选择结果仅为本地预览数据，不授予任何控制权限。",
    packName: "机型包",
    controllers: "飞控合同",
    tier: "验证层级",
    adapter: "适配器",
    preflightTitle: "飞前仲裁",
    preflightBody: "操作者确认只是输入之一，不能替代原生、策略或运行时批准。",
    zone: "作业区域",
    confirmation: "操作者确认",
    nativeGate: "原生安全门",
    runtimeGate: "运行时安全门",
    missing: "缺失",
    localOnly: "仅本地",
    operatorAcknowledgement: "我已知悉 Field 预览版的安全边界。",
    operatorBoundary: "此本地确认不是签名证据，不能授权任何真机动作。",
    controlTitle: "接管与紧急操作",
    controlBody: "真机安全合同未闭合时，所有控制命令保持不可用。",
    takeover: "请求接管",
    emergency: "紧急停止",
    actionMatrix: "已拒绝真机动作",
    denied: "已拒绝",
    action: {
      "parameter-write": "写入参数",
      "rollback-apply": "应用回滚",
      takeover: "接管",
      "emergency-stop": "紧急停止",
      arm: "解锁",
      flight: "飞行",
    },
    footer: "DroneDream · FIELD 1.0.0 · 真机工作区",
  },
} as const;

const NAVIGATION = [
  ["overview", "overview", Gauge],
  ["device", "devices", RadioTower],
  ["compatibility", "compatibility", PackageCheck],
  ["adapters", "adapters", PackageOpen],
  ["tuning", "tuning", Sparkles],
  ["recovery", "recovery", FileClock],
  ["preflight", "preflight", ClipboardCheck],
  ["control", "control", ShieldAlert],
] as const;

const FIRST_FIELD_PACK = FIELD_CATALOG.vehiclePacks[0];
if (!FIRST_FIELD_PACK) throw new Error("Field catalog has no compatible Vehicle Pack");

function fieldControllerKey(vendor: string, model: string): string {
  return `${vendor}::${model}`;
}

interface FieldAppProps {
  initialLocale?: FieldLocale;
  initialObservationState?: FieldObservationState;
  focusOnMount?: boolean;
}

function savedLocale(): FieldLocale {
  try {
    return window.localStorage.getItem("dronedream:field-locale") === "zh-CN"
      ? "zh-CN"
      : "en";
  } catch {
    return "en";
  }
}

export function FieldApp({
  initialLocale,
  initialObservationState = "device-missing",
  focusOnMount = false,
}: FieldAppProps) {
  const [locale, setLocale] = useState<FieldLocale>(initialLocale ?? savedLocale);
  const [observationState, setObservationState] =
    useState<FieldObservationState>(initialObservationState);
  const [activeSection, setActiveSection] = useState("overview");
  const [selectedPackId, setSelectedPackId] = useState(FIRST_FIELD_PACK.packId);
  const [selectedControllerKey, setSelectedControllerKey] = useState(
    fieldControllerKey(
      FIRST_FIELD_PACK.controllers[0]?.vendor ?? "missing",
      FIRST_FIELD_PACK.controllers[0]?.model ?? "missing",
    ),
  );
  const [deviceReport, setDeviceReport] = useState<FieldDeviceDiscoveryReport | null>(null);
  const [deviceScanBusy, setDeviceScanBusy] = useState(false);
  const [deviceScanError, setDeviceScanError] = useState<string | null>(null);
  const [readOnlyEvidence, setReadOnlyEvidence] =
    useState<FieldReadOnlyProtocolEvidence | null>(null);
  const [latestSnapshot, setLatestSnapshot] = useState<FieldParameterSnapshot | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);
  const copy = COPY[locale];
  const observation = FIELD_OBSERVATION_FIXTURES[observationState];
  const decision = useMemo(() => evaluateFieldSafety(observation), [observation]);
  const selectedPack = FIELD_CATALOG.vehiclePacks.find(
    (pack) => pack.packId === selectedPackId,
  ) ?? FIRST_FIELD_PACK;

  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      window.localStorage.setItem("dronedream:field-locale", locale);
    } catch {
      // Locale persistence is optional and has no safety meaning.
    }
  }, [locale]);

  useEffect(() => {
    if (focusOnMount) titleRef.current?.focus({ preventScroll: true });
  }, [focusOnMount]);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    requestAnimationFrame(() => settingsButtonRef.current?.focus());
  }, []);

  const scanDevices = useCallback(async () => {
    setDeviceScanBusy(true);
    setDeviceScanError(null);
    try {
      setDeviceReport(await discoverFieldDevices());
    } catch (error) {
      setDeviceScanError(error instanceof Error ? error.message : String(error));
    } finally {
      setDeviceScanBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!settingsOpen) return;
    const previousOverflow = document.body.style.overflow;
    const inertTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".field-topbar, .field-layout, .field-skip-link",
    ));
    const previousInertStates = inertTargets.map((target) => target.inert);
    document.body.style.overflow = "hidden";
    inertTargets.forEach((target) => { target.inert = true; });
    const focusFrame = requestAnimationFrame(() => settingsCloseRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = settingsCloseRef.current?.closest<HTMLElement>('[role="dialog"]');
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), '
          + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("hidden"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      inertTargets.forEach((target, index) => { target.inert = previousInertStates[index] ?? false; });
    };
  }, [closeSettings, settingsOpen]);

  return (
    <div
      className="field-app"
      data-authority="false"
      data-validated-pack-count={decision.validatedPackCount}
      data-quorum={decision.threeLayerQuorum}
    >
      <a className="field-skip-link" href="#overview">{copy.skip}</a>
      <header className="field-topbar">
        <div className="field-brand" aria-label="DroneDream · FIELD">
          <FieldBrandLockup
            className="field-brand-lockup"
            variant="compact"
          />
        </div>
        <div className="field-topbar-actions">
          <span className="field-preview-badge"><ShieldCheck />{copy.preview}</span>
          <FieldAuthControl locale={locale} />
          <button
            ref={settingsButtonRef}
            className="field-settings-button"
            type="button"
            aria-label={copy.settings}
            title={copy.settings}
            aria-haspopup="dialog"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen(true)}
          >
            <Settings aria-hidden="true" />
          </button>
        </div>
      </header>

      {settingsOpen ? (
        <div
          className="launcher-settings-backdrop field-settings-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeSettings();
          }}
        >
          <FieldSettingsDialog
            closeRef={settingsCloseRef}
            locale={locale}
            onClose={closeSettings}
            onLocaleChange={setLocale}
          />
        </div>
      ) : null}

      <div className="field-layout">
        <aside className="field-sidebar">
          <nav aria-label={copy.nav}>
            {NAVIGATION.map(([id, label, Icon]) => (
              <a
                key={id}
                href={`#${id}`}
                aria-current={activeSection === id ? "page" : undefined}
                onClick={() => setActiveSection(id)}
              >
                <Icon aria-hidden="true" />
                <span>{copy[label]}</span>
                <ChevronRight className="field-nav-chevron" aria-hidden="true" />
              </a>
            ))}
          </nav>
          <div className="field-sidebar-status">
            <span>{copy.validated}</span>
            <strong>{decision.validatedPackCount}</strong>
            <small><CircleOff aria-hidden="true" />{copy.denied}</small>
          </div>
        </aside>

        <main className="field-main">
          <section id="overview" className="field-overview" aria-labelledby="field-title">
            <div>
              <p className="field-kicker">DroneDream · FIELD 1.0.0</p>
              <h1 ref={titleRef} id="field-title" tabIndex={-1}>{copy.title}</h1>
              <p>{copy.subtitle}</p>
            </div>
            <div className="field-overview-metrics" aria-label={copy.title}>
              <div><span>{copy.validated}</span><strong>0 / 7</strong></div>
              <div><span>{copy.quorum}</span><strong>{copy.missing}</strong></div>
            </div>
          </section>

          <div className="field-critical-banner" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div><strong>{copy.zeroTitle}</strong><p>{copy.zeroBody}</p></div>
          </div>

          <section id="device" className="field-section" aria-labelledby="field-device-title">
            <header><div><h2 id="field-device-title">{copy.deviceTitle}</h2><p>{copy.deviceBody}</p></div><RadioTower /></header>
            <div className="field-observation-toolbar">
              <div><span>{copy.source}</span><strong>{deviceReport?.source ?? copy.sourceValue}</strong></div>
              <label>
                <span>{copy.observation}</span>
                <select
                  value={observationState}
                  onChange={(event) => setObservationState(event.target.value as FieldObservationState)}
                >
                  {Object.keys(FIELD_OBSERVATION_FIXTURES).map((state) => (
                    <option key={state} value={state}>{copy.states[state as FieldObservationState]}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="field-device-scan"
                disabled={!isDesktopRuntime() || deviceScanBusy}
                title={!isDesktopRuntime() ? copy.scanUnavailable : copy.scanBoundary}
                onClick={() => void scanDevices()}
              >
                <RefreshCw className={deviceScanBusy ? "field-auth-spinner" : undefined} aria-hidden="true" />
                {deviceScanBusy ? copy.scanning : copy.scan}
              </button>
            </div>
            <p className="field-device-scan-boundary">{copy.scanBoundary}</p>
            {deviceScanError ? <p className="field-device-scan-error" role="alert">{deviceScanError}</p> : null}
            {deviceReport ? (
              <div className="field-device-observations" role="status" data-authority="false">
                <strong>{copy.observedPorts}</strong>
                {deviceReport.devices.length === 0
                  ? <span>{copy.noPorts}</span>
                  : deviceReport.devices.map((device) => (
                    <span key={device.observationId}><code>{device.portName}</code>{device.validationStatus}</span>
                  ))}
              </div>
            ) : null}
            <p className="field-observation-result" role="status">
              <CircleOff aria-hidden="true" />
              <strong>{copy.states[observationState]}</strong>
              <span>{copy.stateDetail[observationState]}</span>
            </p>
            <dl className="field-device-grid">
              <div><dt>{copy.deviceId}</dt><dd>{observation.deviceId ?? copy.unavailable}</dd></div>
              <div><dt>{copy.controller}</dt><dd>{observation.controller ?? copy.unavailable}</dd></div>
              <div><dt>{copy.firmware}</dt><dd>{observation.firmwareVersion ?? copy.unavailable}</dd></div>
              <div><dt>{copy.pack}</dt><dd>{observation.vehiclePackId ?? copy.unavailable}</dd></div>
            </dl>
          </section>

          <section id="compatibility" className="field-section" aria-labelledby="field-registry-title">
            <header><div><h2 id="field-registry-title">{copy.registryTitle}</h2><p>{copy.registryBody}</p></div><PackageCheck /></header>
            <div className="field-compatibility-draft" data-authority="false">
              <div className="field-draft-heading">
                <strong>{copy.compatibilityDraft}</strong>
                <span>{copy.draftBoundary}</span>
              </div>
              <label>
                <span>{copy.selectedPack}</span>
                <select
                  value={selectedPackId}
                  onChange={(event) => {
                    const pack = FIELD_CATALOG.vehiclePacks.find(
                      (candidate) => candidate.packId === event.target.value,
                    ) ?? FIRST_FIELD_PACK;
                    const controller = pack.controllers[0];
                    setSelectedPackId(pack.packId);
                    setSelectedControllerKey(controller
                      ? fieldControllerKey(controller.vendor, controller.model)
                      : "missing");
                  }}
                >
                  {FIELD_CATALOG.vehiclePacks.map((pack) => (
                    <option key={pack.packId} value={pack.packId}>
                      {pack.displayName[locale]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>{copy.selectedController}</span>
                <select
                  value={selectedControllerKey}
                  onChange={(event) => setSelectedControllerKey(event.target.value)}
                >
                  {selectedPack.controllers.map((controller) => (
                    <option
                      key={fieldControllerKey(controller.vendor, controller.model)}
                      value={fieldControllerKey(controller.vendor, controller.model)}
                    >
                      {controller.vendor} {controller.model}
                    </option>
                  ))}
                </select>
              </label>
              <div className="field-evidence-status">
                <span>{copy.firmwareEvidence}</span>
                <strong><CircleOff />{copy.firmwareEvidenceMissing}</strong>
              </div>
            </div>
            <div className="field-table-scroll">
              <table aria-label={copy.registryTitle}>
                <thead><tr><th>{copy.packName}</th><th>{copy.controllers}</th><th>{copy.tier}</th><th>{copy.adapter}</th></tr></thead>
                <tbody>
                  {FIELD_CATALOG.vehiclePacks.map((pack) => (
                    <tr key={pack.packId}>
                      <td><strong>{pack.displayName[locale]}</strong><small>{pack.manufacturer}</small></td>
                      <td>{pack.controllers.map((controller) => controller.model).join(", ")}</td>
                      <td><span className="field-status-pill">{pack.validationTier}</span></td>
                      <td>{pack.adapterStatus}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <FieldAdapterCenter
            locale={locale}
            devices={deviceReport?.devices}
            onReadOnlyEvidence={setReadOnlyEvidence}
          />

          <section id="tuning" className="field-section field-tuning-section" aria-labelledby="field-tuning-title">
            <FieldTuningWorkspace
              locale={locale}
              selectedPackId={selectedPackId}
              selectedControllerId={selectedControllerKey}
              snapshot={latestSnapshot ?? undefined}
            />
          </section>

          <section id="recovery" className="field-section" aria-labelledby="field-recovery-title">
            <FieldRecoveryWorkspace
              locale={locale}
              selectedPackId={selectedPackId}
              selectedControllerId={selectedControllerKey}
              device={deviceReport?.devices[0]}
              evidence={readOnlyEvidence ?? undefined}
              onSnapshotCreated={setLatestSnapshot}
            />
          </section>

          <FieldPreflightWorkspace
            locale={locale}
            selectedPackId={selectedPackId}
            selectedControllerId={selectedControllerKey}
            snapshot={latestSnapshot ?? undefined}
          />
          <footer>{copy.footer}</footer>
        </main>
      </div>
    </div>
  );
}
