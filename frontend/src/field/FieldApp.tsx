import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArchiveRestore,
  ChevronRight,
  CircleOff,
  ClipboardCheck,
  FileClock,
  Gauge,
  HardDrive,
  Languages,
  PackageCheck,
  RadioTower,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

import { BrandLockup } from "../components/BrandLockup";
import { FIELD_CATALOG, type FieldLocale } from "./catalog";
import {
  evaluateFieldSafety,
  FIELD_HARDWARE_ACTIONS,
  FIELD_OBSERVATION_FIXTURES,
  type FieldObservationState,
} from "./safety";

const COPY = {
  en: {
    skip: "Skip to Field overview",
    edition: "FIELD",
    preview: "Internal safety preview",
    locale: "Language",
    nav: "Field navigation",
    overview: "Overview",
    devices: "Device",
    compatibility: "Compatibility",
    recovery: "Snapshot & rollback",
    preflight: "Preflight",
    control: "Safety control",
    title: "Field readiness",
    subtitle: "Read-only device observation and compatibility review",
    zeroTitle: "Hardware authority unavailable",
    zeroBody: "No Vehicle Pack has a validated hardware tier. Device observations cannot unlock control.",
    validated: "Validated packs",
    quorum: "Three-layer quorum",
    source: "Observation source",
    sourceValue: "Built-in read-only fixture",
    observation: "Observation state",
    states: {
      offline: "Offline",
      "device-missing": "No device",
      "unknown-device": "Unknown device",
      "firmware-drift": "Firmware drift",
      "recognized-unvalidated": "Recognized, unvalidated",
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
    recoveryTitle: "Parameter recovery",
    recoveryBody: "A signed snapshot and exact compatibility proof are required before native recovery can be considered.",
    snapshot: "Create snapshot",
    rollback: "Apply rollback",
    snapshotState: "Snapshot",
    rollbackState: "Rollback plan",
    notCaptured: "Not captured",
    notAuthorized: "Not authorized",
    preflightTitle: "Preflight quorum",
    preflightBody: "Operator confirmation is one input. It cannot replace native, policy, or runtime approval.",
    zone: "Operating zone",
    confirmation: "Operator confirmation",
    nativeGate: "Native safety gate",
    runtimeGate: "Runtime gate",
    missing: "Missing",
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
    footer: "DroneDream · FIELD 1.0.0 · contract-only",
  },
  "zh-CN": {
    skip: "跳到 Field 概览",
    edition: "FIELD",
    preview: "内部安全预览",
    locale: "语言",
    nav: "Field 导航",
    overview: "概览",
    devices: "设备",
    compatibility: "兼容性",
    recovery: "快照与回滚",
    preflight: "飞前检查",
    control: "安全控制",
    title: "真机就绪状态",
    subtitle: "只读设备观察与兼容性复核",
    zeroTitle: "真机权限不可用",
    zeroBody: "当前没有达到硬件验证层级的机型包。设备观察结果不能解锁控制权限。",
    validated: "已验证机型包",
    quorum: "三层仲裁",
    source: "观察来源",
    sourceValue: "内置只读测试数据",
    observation: "观察状态",
    states: {
      offline: "离线",
      "device-missing": "无设备",
      "unknown-device": "未知设备",
      "firmware-drift": "固件漂移",
      "recognized-unvalidated": "已识别，未验证",
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
    recoveryTitle: "参数恢复",
    recoveryBody: "原生恢复进入评估前，必须具备签名快照与精确兼容性证据。",
    snapshot: "创建快照",
    rollback: "应用回滚",
    snapshotState: "参数快照",
    rollbackState: "回滚计划",
    notCaptured: "尚未捕获",
    notAuthorized: "未获授权",
    preflightTitle: "飞前仲裁",
    preflightBody: "操作者确认只是输入之一，不能替代原生、策略或运行时批准。",
    zone: "作业区域",
    confirmation: "操作者确认",
    nativeGate: "原生安全门",
    runtimeGate: "运行时安全门",
    missing: "缺失",
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
    footer: "DroneDream · FIELD 1.0.0 · 合同阶段",
  },
} as const;

const NAVIGATION = [
  ["overview", "overview", Gauge],
  ["device", "devices", RadioTower],
  ["compatibility", "compatibility", PackageCheck],
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
          <BrandLockup variant="compact" className="field-brand-lockup" />
          <span aria-hidden="true">· {copy.edition}</span>
        </div>
        <div className="field-topbar-actions">
          <span className="field-preview-badge"><ShieldCheck />{copy.preview}</span>
          <button
            className="field-language-button"
            type="button"
            aria-label={copy.locale}
            onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}
          >
            <Languages aria-hidden="true" />
            {locale === "en" ? "中文" : "EN"}
          </button>
        </div>
      </header>

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
              <h1 id="field-title">{copy.title}</h1>
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
              <div><span>{copy.source}</span><strong>{copy.sourceValue}</strong></div>
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
            </div>
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
              <table>
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

          <section id="recovery" className="field-section" aria-labelledby="field-recovery-title">
            <header><div><h2 id="field-recovery-title">{copy.recoveryTitle}</h2><p>{copy.recoveryBody}</p></div><ArchiveRestore /></header>
            <div className="field-two-column">
              <div className="field-operation-block"><span>{copy.snapshotState}</span><strong>{copy.notCaptured}</strong><button type="button" disabled><HardDrive />{copy.snapshot}</button></div>
              <div className="field-operation-block"><span>{copy.rollbackState}</span><strong>{copy.notAuthorized}</strong><button type="button" disabled><RotateCcw />{copy.rollback}</button></div>
            </div>
          </section>

          <section id="preflight" className="field-section" aria-labelledby="field-preflight-title">
            <header><div><h2 id="field-preflight-title">{copy.preflightTitle}</h2><p>{copy.preflightBody}</p></div><ClipboardCheck /></header>
            <div className="field-gate-grid">
              {[copy.pack, copy.controller, copy.firmware, copy.zone, copy.confirmation, copy.nativeGate, copy.runtimeGate].map((label) => (
                <div key={label}><CircleOff /><span>{label}</span><strong>{copy.missing}</strong></div>
              ))}
            </div>
          </section>

          <section id="control" className="field-section" aria-labelledby="field-control-title">
            <header><div><h2 id="field-control-title">{copy.controlTitle}</h2><p>{copy.controlBody}</p></div><ShieldAlert /></header>
            <div className="field-control-buttons">
              <button type="button" disabled><SlidersHorizontal />{copy.takeover}</button>
              <button type="button" disabled><ShieldAlert />{copy.emergency}</button>
            </div>
            <h3>{copy.actionMatrix}</h3>
            <div className="field-action-matrix">
              {FIELD_HARDWARE_ACTIONS.map((action) => (
                <div key={action}><CircleOff /><span>{copy.action[action]}</span><strong>{copy.denied}</strong></div>
              ))}
            </div>
          </section>
          <footer>{copy.footer}</footer>
        </main>
      </div>
    </div>
  );
}
