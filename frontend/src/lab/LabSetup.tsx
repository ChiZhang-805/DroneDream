import { useMemo, useState } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  FileCheck2,
  FlaskConical,
  LockKeyhole,
  MonitorUp,
  Play,
  RadioTower,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Upload,
  XCircle,
} from "lucide-react";

import { useI18n } from "../i18n/I18nProvider";
import {
  LabEvidencePreviewError,
  parseLabEvidencePreview,
  type LabEvidencePreview,
} from "./evidencePreview";
import { LabCalibrationWorkspace } from "./LabCalibrationWorkspace";
import vehiclePackAdapterJson from "./vehicle-pack-adapter.v1.json";
import "./lab.css";

type Workspace = "simulation" | "hardware";
export type LabSetupView = "calibration" | "setup" | "evidence" | "safety";

interface VehicleController {
  vendor: string;
  model: string;
  status: string;
}
interface VehiclePackOption {
  packId: string;
  displayName: Record<"en" | "zh-CN", string>;
  validationStatus: string;
  validationTier: string;
  productAvailability: string;
  supportedEditions: string[];
  autopilotFamily: string;
  controllers: VehicleController[];
  firmwareVersions: string[];
}

const vehiclePackAdapter = vehiclePackAdapterJson as {
  policy: {
    validatedPackCount: number;
    frontendIsAuthority: boolean;
    zeroValidatedPackDecision: string;
  };
  packs: VehiclePackOption[];
};

const VIEWS: LabSetupView[] = ["calibration", "setup", "evidence", "safety"];
const HARDWARE_ACTIONS = [
  "hardware.parameter.write",
  "hardware.arm",
  "hardware.flight",
  "hardware.hitl.execute",
] as const;

const COPY = {
  en: {
    eyebrow: "LAB 1.0.0 PREVIEW",
    title: "Sim-to-Real calibration laboratory",
    subtitle:
      "Model + Harness connects simulation search, controlled real observations, model calibration, independent holdout, and evidence issuance in one bounded job.",
    edition: "Edition",
    editionValue: "DroneDream · LAB",
    packs: "Validated packs",
    packsValue: "0 of 8",
    authority: "Hardware authority",
    deny: "DENY",
    workspaceLabel: "Lab workspace",
    simulation: "Simulation workspace",
    simulationShort: "Simulation",
    simulationDetail: "PX4 SITL and Gazebo workflow",
    hardware: "Hardware laboratory",
    hardwareDetail: "Configuration preview only",
    switchNotice:
      "Workspace selection changes the workflow only; it never grants hardware authority.",
    calibration: "Calibration loop",
    setup: "Setup",
    evidence: "Qualification evidence",
    safety: "Safety review",
    simulationReady: "Simulation workflow",
    simulationBody:
      "Use the shared experiment workflow for parameter search, fixed scenarios, PX4 SITL, Gazebo, and qualification receipt generation.",
    openExperiment: "Open simulation experiment",
    simulationPack: "Simulation Vehicle Pack",
    selectedContract: "Selected contract",
    contractOnly: "Contract only",
    hardwareSetup: "Hardware configuration preview",
    hardwareBody:
      "Selections bind the intended vehicle, controller, and firmware context. They do not discover a device or authorize an action.",
    vehiclePack: "Vehicle Pack",
    controller: "Flight controller",
    firmware: "Firmware identity",
    noController: "No hardware controller in this pack",
    adapterState: "Adapter state",
    adapterStateValue: "Not validated",
    discovery: "Discover controller",
    openHardware: "Open hardware laboratory",
    write: "Write parameters",
    arm: "Arm vehicle",
    flight: "Start flight / HITL",
    actionsDenied: "Hardware execution is denied",
    actionsDeniedBody:
      "All write, arm, flight, and HITL entry points are disabled because the registry contains zero validated and signed Vehicle Packs.",
    evidenceTitle: "Sim to Lab evidence import preview",
    evidenceBody:
      "Inspect a bounded JSON simulation qualification receipt and parameter candidate locally. Previewed evidence remains untrusted and cannot satisfy hardware authority.",
    chooseEvidence: "Choose JSON evidence",
    clearEvidence: "Clear preview",
    noEvidence: "No evidence selected",
    noEvidenceBody: "A preview never uploads, persists, consumes, or promotes a receipt.",
    previewOnly: "PREVIEW ONLY",
    sourceEdition: "Source edition",
    commonCore: "Common core",
    qualification: "Qualification",
    candidate: "Parameter candidate",
    parameters: "Parameters",
    evidenceRejected: "Evidence rejected",
    safetyTitle: "Execution quorum",
    safetyBody:
      "A hardware request can proceed only when every authority signs the same canonical context. Missing, stale, mismatched, or negative decisions resolve to deny.",
    native: "Native",
    backend: "Backend",
    runtime: "Runtime",
    missing: "Missing",
    quorumResult: "Quorum result",
    reasonZeroPacks: "zero-validated-packs",
    reasonMissingLayers: "native-backend-runtime-missing",
    operatorTitle: "Operator confirmation",
    operatorBody:
      "Confirmation requires a short-lived one-time challenge bound to an authorization request. A checkbox or workspace switch is not accepted.",
    challenge: "Operator challenge",
    challengeUnavailable: "Unavailable: authority quorum denied",
    confirm: "Confirm hardware action",
    deniedCapabilities: "Denied capability IDs",
  },
  "zh-CN": {
    eyebrow: "LAB 1.0.0 内测预览",
    title: "Sim-to-Real 校准实验室",
    subtitle:
      "Model + Harness 在同一份受预算约束的作业中贯通仿真搜索、受控真实观测、模型校准、独立 holdout 与证据签发。",
    edition: "版本",
    editionValue: "DroneDream · LAB",
    packs: "已验证机型包",
    packsValue: "0 / 8",
    authority: "真机权限",
    deny: "拒绝",
    workspaceLabel: "实验室工作区",
    simulation: "仿真工作区",
    simulationShort: "仿真",
    simulationDetail: "PX4 SITL 与 Gazebo 工作流",
    hardware: "真机实验室",
    hardwareDetail: "仅提供配置预览",
    switchNotice:
      "切换工作区只改变流程，绝不会授予真机权限。",
    calibration: "校准闭环",
    setup: "配置",
    evidence: "资格证据",
    safety: "安全复核",
    simulationReady: "仿真工作流",
    simulationBody:
      "使用公共实验流程完成参数搜索、固定场景、PX4 SITL、Gazebo 以及仿真资格 receipt 生成。",
    openExperiment: "打开仿真实验",
    simulationPack: "仿真 Vehicle Pack",
    selectedContract: "当前合同",
    contractOnly: "仅合同",
    hardwareSetup: "真机配置预览",
    hardwareBody:
      "选择项用于绑定预期机型、飞控与固件上下文，不会发现设备，也不会授予执行权限。",
    vehiclePack: "Vehicle Pack",
    controller: "飞行控制器",
    firmware: "固件身份",
    noController: "该机型包不包含真机飞控",
    adapterState: "适配器状态",
    adapterStateValue: "尚未验证",
    discovery: "发现飞控",
    openHardware: "打开真机实验室",
    write: "写入参数",
    arm: "解锁飞行器",
    flight: "启动飞行 / HITL",
    actionsDenied: "真机执行已拒绝",
    actionsDeniedBody:
      "注册表中没有已验证且签名的 Vehicle Pack，因此写参数、解锁、飞行与 HITL 入口全部禁用。",
    evidenceTitle: "Sim 到 Lab 证据导入预览",
    evidenceBody:
      "仅在本地检查受大小限制的 JSON 仿真资格 receipt 与参数候选。预览证据仍不受信任，不能构成真机权限。",
    chooseEvidence: "选择 JSON 证据",
    clearEvidence: "清除预览",
    noEvidence: "尚未选择证据",
    noEvidenceBody: "预览不会上传、持久化、消费或晋级任何 receipt。",
    previewOnly: "仅预览",
    sourceEdition: "来源版本",
    commonCore: "公共核心",
    qualification: "资格结果",
    candidate: "参数候选",
    parameters: "参数",
    evidenceRejected: "证据已拒绝",
    safetyTitle: "执行权限法定人数",
    safetyBody:
      "只有所有权限层对同一份规范上下文签发一致决定时，真机请求才可能继续。缺失、过期、不匹配或否定决定一律归为拒绝。",
    native: "Native",
    backend: "后端",
    runtime: "Runtime",
    missing: "缺失",
    quorumResult: "法定人数结果",
    reasonZeroPacks: "零个已验证机型包",
    reasonMissingLayers: "native、后端与 Runtime 决定缺失",
    operatorTitle: "操作员人工确认",
    operatorBody:
      "人工确认必须使用绑定授权请求的短时一次性 challenge；复选框或工作区切换不被接受。",
    challenge: "操作员 challenge",
    challengeUnavailable: "不可用：权限法定人数为拒绝",
    confirm: "确认真机动作",
    deniedCapabilities: "被拒绝的能力 ID",
  },
} as const;

function shortHash(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

export function LabSetup({
  initialView = "calibration",
}: {
  initialView?: LabSetupView;
} = {}) {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const [workspace, setWorkspace] = useState<Workspace>("simulation");
  const [view, setView] = useState<LabSetupView>(initialView);
  const [packId, setPackId] = useState(vehiclePackAdapter.packs[0]?.packId ?? "");
  const [controllerIndex, setControllerIndex] = useState(0);
  const [firmwareIndex, setFirmwareIndex] = useState(0);
  const [evidence, setEvidence] = useState<LabEvidencePreview | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  const availablePacks = useMemo(
    () => vehiclePackAdapter.packs.filter((pack) => (
      workspace === "simulation"
        ? pack.supportedEditions.includes("sim")
        : pack.supportedEditions.includes("lab") && pack.controllers.length > 0
    )),
    [workspace],
  );
  const selectedPack = availablePacks.find((pack) => pack.packId === packId)
    ?? availablePacks[0]
    ?? vehiclePackAdapter.packs[0];
  const selectedController = selectedPack?.controllers[controllerIndex]
    ?? selectedPack?.controllers[0];
  const selectedFirmware = selectedPack?.firmwareVersions[firmwareIndex]
    ?? selectedPack?.firmwareVersions[0];

  function chooseWorkspace(next: Workspace) {
    const nextPacks = vehiclePackAdapter.packs.filter((pack) => (
      next === "simulation"
        ? pack.supportedEditions.includes("sim")
        : pack.supportedEditions.includes("lab") && pack.controllers.length > 0
    ));
    setWorkspace(next);
    setView("setup");
    setPackId(nextPacks[0]?.packId ?? "");
    setControllerIndex(0);
    setFirmwareIndex(0);
  }

  function selectView(next: LabSetupView) {
    setView(next);
  }

  function handleViewKeyDown(event: KeyboardEvent<HTMLButtonElement>, current: LabSetupView) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentIndex = VIEWS.indexOf(current);
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = VIEWS[(currentIndex + offset + VIEWS.length) % VIEWS.length];
    if (!next) return;
    selectView(next);
    document.getElementById(`lab-view-${next}`)?.focus();
  }

  async function previewEvidence(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const preview = parseLabEvidencePreview(file.name, await file.text());
      setEvidence(preview);
      setEvidenceError(null);
    } catch (error) {
      setEvidence(null);
      setEvidenceError(
        error instanceof LabEvidencePreviewError
          ? error.message
          : "The evidence file could not be inspected.",
      );
    }
  }

  return (
    <section
      className="lab-page"
      data-workspace={workspace}
      data-brand-edition="lab"
      data-grants-hardware-authority="false"
    >
      <header className="lab-header">
        <div>
          <p className="lab-eyebrow">{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <p className="sr-only">{copy.subtitle}</p>
        </div>
        <div className="lab-status-summary" aria-label={copy.authority}>
          <span><small>{copy.edition}</small><strong>{copy.editionValue}</strong></span>
          <span><small>{copy.packs}</small><strong>{copy.packsValue}</strong></span>
          <span className="lab-deny-summary"><small>{copy.authority}</small><strong>{copy.deny}</strong></span>
        </div>
      </header>

      <div className="lab-workspace-switch" role="group" aria-label={copy.workspaceLabel}>
        <button
          type="button"
          className={workspace === "simulation" ? "is-active" : undefined}
          aria-pressed={workspace === "simulation"}
          onClick={() => chooseWorkspace("simulation")}
        >
          <MonitorUp aria-hidden="true" />
          <span><strong>{copy.simulation}</strong></span>
        </button>
        <button
          type="button"
          className={workspace === "hardware" ? "is-active" : undefined}
          aria-pressed={workspace === "hardware"}
          onClick={() => chooseWorkspace("hardware")}
        >
          <RadioTower aria-hidden="true" />
          <span><strong>{copy.hardware}</strong></span>
        </button>
      </div>
      <p className="sr-only" role="status">{copy.switchNotice}</p>

      <div className="lab-view-tabs" role="tablist" aria-label={copy.title}>
        {VIEWS.map((item) => {
          const label = copy[item];
          const Icon = item === "calibration"
            ? RefreshCw
            : item === "setup"
              ? FlaskConical
              : item === "evidence"
                ? FileCheck2
                : ShieldAlert;
          return (
            <button
              key={item}
              id={`lab-view-${item}`}
              type="button"
              role="tab"
              aria-selected={view === item}
              aria-controls={`lab-panel-${item}`}
              tabIndex={view === item ? 0 : -1}
              onClick={() => selectView(item)}
              onKeyDown={(event) => handleViewKeyDown(event, item)}
            >
              <Icon aria-hidden="true" /> {label}
            </button>
          );
        })}
      </div>

      {view === "calibration" ? (
        <section
          id="lab-panel-calibration"
          className="lab-tool"
          role="tabpanel"
          aria-labelledby="lab-view-calibration"
        >
          <LabCalibrationWorkspace />
        </section>
      ) : null}

      {view === "setup" ? (
        <section id="lab-panel-setup" className="lab-tool" role="tabpanel" aria-labelledby="lab-view-setup">
          {workspace === "simulation" ? (
            <div className="lab-setup-layout">
              <div className="lab-tool-intro">
                <MonitorUp aria-hidden="true" />
                <div><h2>{copy.simulationReady}</h2><p>{copy.simulationBody}</p></div>
              </div>
              <div className="lab-field-grid">
                <label>
                  <span>{copy.simulationPack}</span>
                  <select
                    value={selectedPack?.packId}
                    onChange={(event) => {
                      setPackId(event.target.value);
                      setControllerIndex(0);
                      setFirmwareIndex(0);
                    }}
                  >
                    {availablePacks.map((pack) => (
                      <option key={pack.packId} value={pack.packId}>{pack.displayName[locale]}</option>
                    ))}
                  </select>
                </label>
                <div className="lab-contract-readout">
                  <span>{copy.selectedContract}</span>
                  <strong>{selectedPack?.packId}</strong>
                  <small>{copy.contractOnly} · {selectedPack?.autopilotFamily.toUpperCase()} {selectedFirmware}</small>
                </div>
              </div>
              <div className="lab-actions">
                <Link to="/jobs/new" className="btn btn-primary">
                  <Play aria-hidden="true" /> {copy.openExperiment}
                </Link>
              </div>
            </div>
          ) : (
            <div className="lab-setup-layout">
              <div className="lab-tool-intro">
                <RadioTower aria-hidden="true" />
                <div><h2>{copy.hardwareSetup}</h2><p>{copy.hardwareBody}</p></div>
              </div>
              <div className="lab-field-grid lab-hardware-fields">
                <label>
                  <span>{copy.vehiclePack}</span>
                  <select
                    value={selectedPack?.packId}
                    onChange={(event) => {
                      setPackId(event.target.value);
                      setControllerIndex(0);
                      setFirmwareIndex(0);
                    }}
                  >
                    {availablePacks.map((pack) => (
                      <option key={pack.packId} value={pack.packId}>{pack.displayName[locale]}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>{copy.controller}</span>
                  <select
                    value={controllerIndex}
                    disabled={!selectedController}
                    onChange={(event) => setControllerIndex(Number(event.target.value))}
                  >
                    {selectedPack?.controllers.length ? selectedPack.controllers.map((controller, index) => (
                      <option key={`${controller.vendor}-${controller.model}`} value={index}>
                        {controller.vendor} {controller.model} · {controller.status}
                      </option>
                    )) : <option>{copy.noController}</option>}
                  </select>
                </label>
                <label>
                  <span>{copy.firmware}</span>
                  <select
                    value={firmwareIndex}
                    onChange={(event) => setFirmwareIndex(Number(event.target.value))}
                  >
                    {selectedPack?.firmwareVersions.map((firmware, index) => (
                      <option key={firmware} value={index}>{firmware}</option>
                    ))}
                  </select>
                </label>
                <div className="lab-contract-readout">
                  <span>{copy.adapterState}</span>
                  <strong>{copy.adapterStateValue}</strong>
                  <small>{selectedPack?.packId} · {selectedController?.model} · {selectedFirmware}</small>
                </div>
              </div>
              <div className="lab-deny-banner" role="alert">
                <XCircle aria-hidden="true" />
                <div><strong>{copy.actionsDenied}</strong><p>{copy.actionsDeniedBody}</p></div>
              </div>
              <div className="lab-hardware-actions" aria-label={copy.actionsDenied}>
                <Link to="/lab/hardware" className="btn btn-primary">
                  <RadioTower aria-hidden="true" /> {copy.openHardware}
                </Link>
                {[copy.discovery, copy.write, copy.arm, copy.flight].map((label) => (
                  <button key={label} type="button" className="btn" disabled>
                    <LockKeyhole aria-hidden="true" /> {label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      ) : null}

      {view === "evidence" ? (
        <section id="lab-panel-evidence" className="lab-tool" role="tabpanel" aria-labelledby="lab-view-evidence">
          <div className="lab-tool-intro">
            <FileCheck2 aria-hidden="true" />
            <div><h2>{copy.evidenceTitle}</h2><p>{copy.evidenceBody}</p></div>
          </div>
          <div className="lab-evidence-actions">
            <label className="btn lab-file-button">
              <Upload aria-hidden="true" /> {copy.chooseEvidence}
              <input type="file" accept="application/json,.json" onChange={previewEvidence} />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!evidence && !evidenceError}
              onClick={() => { setEvidence(null); setEvidenceError(null); }}
            >
              <RotateCcw aria-hidden="true" /> {copy.clearEvidence}
            </button>
          </div>
          {evidenceError ? (
            <div className="lab-deny-banner" role="alert">
              <XCircle aria-hidden="true" /><div><strong>{copy.evidenceRejected}</strong><p>{evidenceError}</p></div>
            </div>
          ) : evidence ? (
            <div className="lab-evidence-preview" aria-live="polite">
              <header><span>{evidence.fileName}</span><strong>{copy.previewOnly}</strong></header>
              <dl>
                <div><dt>{copy.sourceEdition}</dt><dd>{evidence.sourceEdition}</dd></div>
                <div><dt>{copy.commonCore}</dt><dd><code>{shortHash(evidence.commonCoreCommit)}</code></dd></div>
                <div><dt>{copy.qualification}</dt><dd>{evidence.qualificationLevel} · {evidence.qualificationDecision}</dd></div>
                <div><dt>{copy.candidate}</dt><dd><code>{shortHash(evidence.parameterCandidateHash)}</code></dd></div>
              </dl>
              <div className="lab-parameter-preview">
                <strong>{copy.parameters}</strong>
                {evidence.parameters.length ? (
                  <ul>{evidence.parameters.map((parameter) => (
                    <li key={parameter.name}><code>{parameter.name}</code><span>{parameter.value} {parameter.unit}</span></li>
                  ))}</ul>
                ) : <span>0</span>}
              </div>
            </div>
          ) : (
            <div className="lab-empty-evidence">
              <Upload aria-hidden="true" /><strong>{copy.noEvidence}</strong><p>{copy.noEvidenceBody}</p>
            </div>
          )}
        </section>
      ) : null}

      {view === "safety" ? (
        <section id="lab-panel-safety" className="lab-tool" role="tabpanel" aria-labelledby="lab-view-safety">
          <div className="lab-tool-intro">
            <ShieldAlert aria-hidden="true" />
            <div><h2>{copy.safetyTitle}</h2><p>{copy.safetyBody}</p></div>
          </div>
          <div className="lab-quorum" aria-label={copy.safetyTitle}>
            {[copy.native, copy.backend, copy.runtime].map((layer) => (
              <div key={layer}><span>{layer}</span><strong><XCircle aria-hidden="true" /> {copy.missing}</strong></div>
            ))}
            <div className="lab-quorum-result">
              <span>{copy.quorumResult}</span><strong>{copy.deny}</strong>
              <small>{copy.reasonZeroPacks} · {copy.reasonMissingLayers}</small>
            </div>
          </div>
          <div className="lab-operator-confirmation">
            <div><h3>{copy.operatorTitle}</h3><p>{copy.operatorBody}</p></div>
            <label><span>{copy.challenge}</span><input value={copy.challengeUnavailable} disabled readOnly /></label>
            <button type="button" className="btn" disabled><CheckCircle2 aria-hidden="true" /> {copy.confirm}</button>
          </div>
          <details className="lab-denied-capabilities">
            <summary>{copy.deniedCapabilities}</summary>
            <ul>{HARDWARE_ACTIONS.map((action) => <li key={action}><code>{action}</code></li>)}</ul>
          </details>
        </section>
      ) : null}
    </section>
  );
}
