import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  History,
  PackageCheck,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";

import {
  discoverFieldDevices,
  isDesktopRuntime,
  type FieldDeviceDiscoveryReport,
  type FieldParameterSnapshot,
} from "../desktop/bridge";
import { useOptionalAuth } from "../features/auth/AuthContext";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import { useI18n } from "../i18n/I18nProvider";
import { FIELD_CATALOG, type FieldLocale } from "./catalog";
import {
  FieldAdapterCenter,
  type FieldReadOnlyProtocolEvidence,
} from "./FieldAdapterCenter";
import { FieldAssistantWorkspace } from "./FieldAssistantWorkspace";
import { FieldPreflightWorkspace } from "./FieldPreflightWorkspace";
import { FieldRecoveryWorkspace } from "./FieldRecoveryWorkspace";
import { FieldTuningWorkspace } from "./FieldTuningWorkspace";
import {
  evaluateFieldSafety,
  FIELD_OBSERVATION_FIXTURES,
  type FieldObservationState,
} from "./safety";
import { hardwareDomainEdition } from "./hardwareDomain";
import "./field.css";

type FieldPageId = "assistant" | "device" | "compatibility" | "tuning" | "recovery" | "operations";

const COPY = {
  en: {
    skip: "Skip to workspace",
    nav: "Hardware laboratory navigation",
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
    page: {
      device: ["Device & adapters", "Discover hardware without opening a transport, then select the matching protocol adapter."],
      compatibility: ["Compatibility", "Match the Vehicle Pack, controller, firmware, and adapter before any controlled test."],
      tuning: ["Autonomous tuning", "Model proposes candidates; Harness constrains trials, evidence, holdout, and rollback."],
      recovery: ["Snapshots & rollback", "Capture parameter state and prepare a content-bound recovery transaction."],
      operations: ["Preflight & control", "Review zone, operator confirmation, takeover, and emergency controls."],
    },
    scan: "Discover",
    scanning: "Scanning",
    scanUnavailable: "Available in the installed Lab app",
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
  },
  "zh-CN": {
    skip: "跳到工作区",
    nav: "真机实验室导航",
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
    page: {
      device: ["设备与适配器", "在不打开传输端口的前提下发现硬件，并选择匹配的协议适配器。"],
      compatibility: ["兼容性", "受控测试前，确认机型包、飞控、固件和适配器一致。"],
      tuning: ["自主调优", "Model 提出候选，Harness 约束试验、证据、留出验证与回滚。"],
      recovery: ["快照与回滚", "采集参数状态，并准备内容绑定的恢复事务。"],
      operations: ["飞前与控制", "检查区域、操作员确认、接管与紧急控制。"],
    },
    scan: "发现设备",
    scanning: "正在扫描",
    scanUnavailable: "仅在已安装的 Lab 应用中可用",
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

interface FieldAppProps {
  initialLocale?: FieldLocale;
  initialObservationState?: FieldObservationState;
  focusOnMount?: boolean;
  embeddedInLab?: boolean;
}

function FieldPageHeading({
  icon: Icon,
  title,
  body,
  edition,
}: {
  icon: typeof RadioTower;
  title: string;
  body: string;
  edition: "lab" | "field";
}) {
  return (
    <header className="field-page-heading">
      <div>
        <span className="field-page-eyebrow"><Icon aria-hidden="true" />{edition === "lab" ? "LAB · HARDWARE" : "FIELD"}</span>
        <h1>{title}</h1>
        <p>{body}</p>
      </div>
    </header>
  );
}

function FieldWorkspace({
  initialLocale,
  initialObservationState = "device-missing",
  focusOnMount = false,
  embeddedInLab = false,
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
  const pageRef = useRef<HTMLDivElement>(null);
  const copy = COPY[locale];
  const observation = FIELD_OBSERVATION_FIXTURES[observationState];
  const decision = useMemo(() => evaluateFieldSafety(observation), [observation]);
  const selectedPack = FIELD_CATALOG.vehiclePacks.find((pack) => pack.packId === selectedPackId)
    ?? FIRST_FIELD_PACK;
  const selectedController = selectedPack.controllers.find(
    (controller) => controllerKey(controller.vendor, controller.model) === selectedControllerKey,
  ) ?? selectedPack.controllers[0];

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
    if (focusOnMount) pageRef.current?.focus({ preventScroll: true });
  }, [focusOnMount]);

  const selectPage = (page: FieldPageId) => {
    setActivePage(page);
    requestAnimationFrame(() => pageRef.current?.focus({ preventScroll: true }));
  };

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

  const renderDevicePage = () => {
    const [title, body] = copy.page.device;
    return (
      <div className="field-page field-device-page">
        <FieldPageHeading icon={RadioTower} title={title} body={body} edition={presentationEdition} />
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
                title={!isDesktopRuntime() ? copy.scanUnavailable : copy.scan}
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
    const [title, body] = copy.page.compatibility;
    return (
      <div className="field-page field-compatibility-page">
        <FieldPageHeading icon={PackageCheck} title={title} body={body} edition={presentationEdition} />
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
          <div className="field-table-scroll"><table aria-label={copy.registry}><thead><tr><th>{copy.pack}</th><th>{copy.controller}</th><th>{copy.tier}</th><th>{copy.adapter}</th></tr></thead><tbody>{FIELD_CATALOG.vehiclePacks.map((pack) => <tr key={pack.packId}><td><strong>{pack.displayName[locale]}</strong><small>{pack.manufacturer}</small></td><td>{pack.controllers.map((controller) => controller.model).join(", ")}</td><td><span className="field-status-pill">{pack.validationTier}</span></td><td>{pack.adapterStatus}</td></tr>)}</tbody></table></div>
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
      const [title, body] = copy.page.tuning;
      return <div className="field-page"><FieldPageHeading icon={SlidersHorizontal} title={title} body={body} edition={presentationEdition} /><div className="field-page-component"><FieldTuningWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} snapshot={latestSnapshot ?? undefined} /></div></div>;
    }
    if (activePage === "recovery") {
      const [title, body] = copy.page.recovery;
      return <div className="field-page"><FieldPageHeading icon={History} title={title} body={body} edition={presentationEdition} /><div className="field-page-component"><FieldRecoveryWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} device={deviceReport?.devices[0]} evidence={readOnlyEvidence ?? undefined} onSnapshotCreated={setLatestSnapshot} /></div></div>;
    }
    const [title, body] = copy.page.operations;
    return <div className="field-page"><FieldPageHeading icon={ShieldCheck} title={title} body={body} edition={presentationEdition} /><div className="field-page-component"><FieldPreflightWorkspace locale={locale} selectedPackId={selectedPackId} selectedControllerId={selectedControllerKey} snapshot={latestSnapshot ?? undefined} /></div></div>;
  };

  return (
    <div
      className={`field-app${embeddedInLab ? " field-app-embedded-lab" : ""}`}
      data-brand-edition={presentationEdition}
      data-authority="false"
      data-validated-pack-count={decision.validatedPackCount}
      data-quorum={decision.threeLayerQuorum}
    >
      <a className="field-skip-link" href="#field-page">{copy.skip}</a>
      <div className="field-layout">
        <aside className="field-sidebar">
          <nav aria-label={copy.nav}>{NAVIGATION.map(([id, label, Icon]) => <button key={id} type="button" title={copy[label]} aria-label={copy[label]} aria-current={activePage === id ? "page" : undefined} onClick={() => selectPage(id)}><Icon aria-hidden="true" /><span>{copy[label]}</span></button>)}</nav>
          <div className="field-sidebar-status" title={`${copy.packs}: 0`}><Wrench aria-hidden="true" /><div><span>{copy.packs}</span><strong>0</strong></div><small>{copy.locked}</small></div>
        </aside>
        <main className="field-main" id="field-page">
          <div ref={pageRef} className="field-active-page" tabIndex={-1} data-page={activePage}>{renderActivePage()}</div>
        </main>
      </div>
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

/**
 * Universal owns the shared application locale. The standalone FIELD entry
 * keeps its edition-scoped preference, while this route adapter makes the
 * integrated workspace follow Universal without creating a second language
 * authority.
 */
export function UniversalFieldApp() {
  const { locale } = useI18n();
  return <FieldApp initialLocale={locale} />;
}
