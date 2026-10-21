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

import { localeSafeError, useI18n } from "../i18n/I18nProvider";
import {
  parseLabEvidencePreview,
  MAX_LAB_EVIDENCE_BYTES,
} from "./evidencePreview";
import { useEvidenceImport } from "./useEvidenceImport";
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
const COPY = {
  en: {
    setup: "Setup",
    calibration: "Calibration loop",
    title: "LAB workspace",
    workspaceLabel: "Lab workspace",
    simulation: "Simulation workspace",
    hardware: "Hardware laboratory",
    evidence: "Qualification evidence",
    safety: "Safety review",
    simulationReady: "Simulation workflow",
    openExperiment: "Open simulation experiment",
    simulationPack: "Simulation Vehicle Pack",
    selectedContract: "Selected contract",
    contractOnly: "Contract only",
    hardwareSetup: "Hardware configuration preview",
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
    evidenceTitle: "Sim to Lab evidence import preview",
    chooseEvidence: "Choose JSON evidence",
    clearEvidence: "Clear preview",
    noEvidence: "No evidence selected",
    previewOnly: "PREVIEW ONLY",
    sourceEdition: "Source edition",
    commonCore: "Common core",
    qualification: "Qualification",
    candidate: "Parameter candidate",
    parameters: "Parameters",
    evidenceRejected: "Evidence rejected",
    safetyTitle: "Execution quorum",
    operatorTitle: "Operator confirmation",
    challenge: "Operator challenge",
    challengeUnavailable: "Unavailable: authority quorum denied",
    confirm: "Confirm hardware action",
  },
  "zh-CN": {
    setup: "配置",
    calibration: "校准闭环",
    title: "LAB 工作区",
    workspaceLabel: "实验室工作区",
    simulation: "仿真工作区",
    hardware: "真机实验室",
    evidence: "资格证据",
    safety: "安全复核",
    simulationReady: "仿真工作流",
    openExperiment: "打开仿真实验",
    simulationPack: "仿真 Vehicle Pack",
    selectedContract: "当前合同",
    contractOnly: "仅合同",
    hardwareSetup: "真机配置预览",
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
    evidenceTitle: "Sim 到 Lab 证据导入预览",
    chooseEvidence: "选择 JSON 证据",
    clearEvidence: "清除预览",
    noEvidence: "尚未选择证据",
    previewOnly: "仅预览",
    sourceEdition: "来源版本",
    commonCore: "公共核心",
    qualification: "资格结果",
    candidate: "参数候选",
    parameters: "参数",
    evidenceRejected: "证据已拒绝",
    safetyTitle: "执行权限法定人数",
    operatorTitle: "操作员人工确认",
    challenge: "操作员 challenge",
    challengeUnavailable: "不可用：权限法定人数为拒绝",
    confirm: "确认真机动作",
  },
} as const;

/** Shortened display only; consumers keep the complete source identity. */
function shortHash(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

/** Choose workflows and preview evidence without granting device access from UI state. */
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
  const evidenceImport = useEvidenceImport(MAX_LAB_EVIDENCE_BYTES, parseLabEvidencePreview);
  const evidence = evidenceImport.value;
  const evidenceError = evidenceImport.error ? localeSafeError(evidenceImport.error, locale, {
    zh: "无法检查此证据文件。", en: "The evidence file could not be inspected.",
  }) : null;

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
    // Switching context must not adopt a file still loading in the previous workflow.
    evidenceImport.reset();
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
    // Roving tabindex keeps only the active tab in sequential keyboard navigation.
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
    await evidenceImport.importFile(file);
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
          <h1>{copy.title}</h1>
        </div>
      </header>

      <div className="lab-navigation">
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
                <h2>{copy.simulationReady}</h2>
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
                <h2>{copy.hardwareSetup}</h2>
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
              <div className="lab-actions">
                <Link to="/lab/hardware" className="btn btn-primary">
                  <RadioTower aria-hidden="true" /> {copy.openHardware}
                </Link>
              </div>

                <div className="lab-hardware-actions" aria-label={copy.actionsDenied}>
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
          <div className="lab-action-toolbar">
          <div className="lab-tool-intro">
            <FileCheck2 aria-hidden="true" />
            <h2>{copy.evidenceTitle}</h2>
          </div>
          <div className="lab-evidence-actions">
            <label className="btn btn-primary lab-file-button">
              <Upload aria-hidden="true" /> {copy.chooseEvidence}
              <input type="file" accept="application/json,.json" onChange={previewEvidence} />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              aria-label={copy.clearEvidence}
              title={copy.clearEvidence}
              disabled={!evidence && !evidenceError && !evidenceImport.loading}
              onClick={evidenceImport.reset}
            >
              <RotateCcw aria-hidden="true" />
            </button>
          </div>
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
              <Upload aria-hidden="true" /><strong>{copy.noEvidence}</strong>
            </div>
          )}
        </section>
      ) : null}

      {view === "safety" ? (
        <section id="lab-panel-safety" className="lab-tool" role="tabpanel" aria-labelledby="lab-view-safety">
          <div className="lab-tool-intro">
            <ShieldAlert aria-hidden="true" />
            <h2>{copy.safetyTitle}</h2>
          </div>
          <div className="lab-operator-confirmation">
            <div><h3>{copy.operatorTitle}</h3></div>
            <label><span>{copy.challenge}</span><input value={copy.challengeUnavailable} disabled readOnly /></label>
            <button type="button" className="btn" disabled><CheckCircle2 aria-hidden="true" /> {copy.confirm}</button>
          </div>
        </section>
      ) : null}
    </section>
  );
}
