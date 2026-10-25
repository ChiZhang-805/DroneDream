import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Download,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";

import { localeSafeError, useI18n } from "../i18n/I18nProvider";
import {
  evaluateLabCalibrationCycle,
  isDesktopRuntime,
} from "../desktop/bridge";
import {
  analyzeLabCalibration,
  MAX_LAB_CALIBRATION_INPUT_BYTES,
  parseLabCalibrationInput,
  serializeLabCalibrationDraftReceipt,
  type LabCalibrationAnalysis,
  type LabObjective,
} from "./calibrationWorkflow";
import { LabEvidenceBridgePanel } from "./LabEvidenceBridgePanel";
import { useEvidenceImport } from "./useEvidenceImport";

const COPY = {
  en: {
    exportFailed: "The draft receipt could not be generated.",
    inspectFailed: "The evidence could not be inspected.",
    title: "Bidirectional calibration loop",
    objective: "Optimization objective",
    objectives: {
      tracking: "Tracking accuracy",
      stability: "Stability margin",
      energy: "Energy efficiency",
      robustness: "Robustness",
    },
    tolerance: "Gap tolerance",
    cycleBudget: "Cycle budget",
    cycles: "cycles",
    import: "Import bound cycle evidence",
    reset: "Reset analysis",
    noInput: "No cycle evidence bound",
    rejected: "Evidence rejected",
    workflow: "Job progression",
    gap: "Sim-real gap",
    aggregate: "Aggregate gap",
    sim: "SIM",
    real: "REAL",
    export: "Export draft receipt",
    openSim: "Open simulation optimization",
    draftOnly: "DRAFT · NOT QUALIFIED",
    job: "Job",
    cycle: "Cycle",
    vehiclePack: "Vehicle Pack",
    status: { complete: "Complete", ready: "Ready", pending: "Pending", blocked: "Blocked" },
    metrics: {
      trackingRmseM: "Tracking RMSE",
      maxErrorM: "Maximum error",
      energyWh: "Energy",
      overshootCount: "Overshoot count",
    },
    stages: {
      "objective-and-constraints": "Objective & constraints",
      "simulation-search": "Simulation search",
      "controlled-real-observation": "Controlled real observation",
      "sim-real-gap-analysis": "Gap analysis",
      "real-sim-model-calibration": "Model calibration",
      resimulation: "Resimulation",
      "independent-holdout": "Independent holdout",
      "qualification-and-evidence": "Qualification evidence",
      "field-handoff": "FIELD handoff",
    },
  },
  "zh-CN": {
    exportFailed: "无法生成草稿回执。",
    inspectFailed: "无法检查导入的证据。",
    title: "双向校准闭环",
    objective: "优化目标",
    objectives: {
      tracking: "跟踪精度",
      stability: "稳定裕度",
      energy: "能效",
      robustness: "鲁棒性",
    },
    tolerance: "差距容限",
    cycleBudget: "循环预算",
    cycles: "轮",
    import: "导入已绑定循环证据",
    reset: "重置分析",
    noInput: "尚未绑定循环证据",
    rejected: "证据已拒绝",
    workflow: "作业进程",
    gap: "仿真与真实差距",
    aggregate: "综合差距",
    sim: "仿真",
    real: "真实",
    export: "导出草稿回执",
    openSim: "打开仿真优化",
    draftOnly: "草稿 · 尚未取得资格",
    job: "作业",
    cycle: "循环",
    vehiclePack: "机型包",
    status: { complete: "完成", ready: "就绪", pending: "等待", blocked: "阻断" },
    metrics: {
      trackingRmseM: "跟踪 RMSE",
      maxErrorM: "最大误差",
      energyWh: "能耗",
      overshootCount: "超调次数",
    },
    stages: {
      "objective-and-constraints": "目标与约束",
      "simulation-search": "仿真搜索",
      "controlled-real-observation": "受控真实观测",
      "sim-real-gap-analysis": "差距分析",
      "real-sim-model-calibration": "模型校准",
      resimulation: "重新仿真",
      "independent-holdout": "独立留出验证",
      "qualification-and-evidence": "资格证据",
      "field-handoff": "FIELD 交接",
    },
  },
} as const;

/** Render already-validated metrics, not a second source of physical measurements. */
function formatMetric(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

/** Local sim/real comparison and draft export; no automatic model training or actuation. */
export function LabCalibrationWorkspace() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const [objective, setObjective] = useState<LabObjective>("tracking");
  const [tolerance, setTolerance] = useState(15);
  const [cycleBudget, setCycleBudget] = useState(4);
  const evidenceImport = useEvidenceImport(MAX_LAB_CALIBRATION_INPUT_BYTES,
                                          parseLabCalibrationInput);
  const input = evidenceImport.value;
  const [exportError, setExportError] = useState<string | null>(null);
  const exportGeneration = useRef(0);
  useEffect(() => () => { exportGeneration.current += 1; }, []);
  const error = evidenceImport.error ? localeSafeError(evidenceImport.error, locale, {
    zh: COPY["zh-CN"].inspectFailed, en: COPY.en.inspectFailed,
  }) : exportError;
  const analysis = useMemo<LabCalibrationAnalysis | null>(
    () => input
      ? analyzeLabCalibration(input, objective, tolerance, cycleBudget)
      : null,
    [cycleBudget, input, objective, tolerance],
  );

  async function importEvidence(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    invalidateExport();
    await evidenceImport.importFile(file);
  }

  /** Any changed input invalidates a pending native export; late results cannot download. */
  function invalidateExport() {
    exportGeneration.current += 1;
    setExportError(null);
  }

  function reset() {
    invalidateExport();
    evidenceImport.reset();
  }

  async function exportDraft() {
    if (!input || !analysis) return;
    const ticket = ++exportGeneration.current;
    let source: string;
    if (isDesktopRuntime()) {
      try {
        const receipt = await evaluateLabCalibrationCycle({
          schemaVersion: 1,
          jobId: input.jobId,
          cycleOrdinal: input.cycleOrdinal,
          commonCoreCommit: input.commonCoreCommit,
          editionManifestSha256: input.editionManifestSha256,
          vehiclePackId: input.vehiclePackId,
          controllerIdentity: input.controllerIdentity,
          firmwareIdentity: input.firmwareIdentity,
          simulationReceiptSha256: input.simulationReceiptHash,
          realObservationReceiptSha256: input.realObservationReceiptHash,
          parameterCandidateSha256: input.parameterCandidateHash,
          objectiveContractSha256: input.objectiveContractHash,
          constraintContractSha256: input.constraintContractHash,
          holdoutContractSha256: input.holdoutContractHash,
          metricNormalizationReceiptSha256: input.metricNormalizationReceiptHash,
          objective,
          tolerancePercent: tolerance,
          cycleBudget,
          simulation: input.simulation,
          realObservation: input.realObservation,
          independentHoldoutPassed: false,
        });
        source = `${JSON.stringify(receipt, null, 2)}\n`;
      } catch (caught) {
        if (ticket !== exportGeneration.current) return;
        setExportError(localeSafeError(caught, locale, {
          zh: COPY["zh-CN"].exportFailed,
          en: COPY.en.exportFailed,
        }));
        return;
      }
    } else {
      source = serializeLabCalibrationDraftReceipt(input, analysis);
    }
    if (ticket !== exportGeneration.current) return;
    const blob = new Blob(
      [source],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${input.jobId}-cycle-${input.cycleOrdinal}-lab-draft.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section
      className="lab-calibration"
      data-brand-edition="lab"
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <div className="lab-action-toolbar">
      <div className="lab-tool-intro">
        <RefreshCw aria-hidden="true" />
        <div><h2>{copy.title}</h2></div>
      </div>
      <div className="lab-calibration-import">
        <label className="btn btn-primary lab-file-button" title={copy.import}>
          <Upload aria-hidden="true" /> {locale === "zh-CN" ? "导入循环证据" : "Import cycle"}
          <input aria-label={copy.import} type="file" accept="application/json,.json" onChange={importEvidence} />
        </label>
        <button type="button" className="btn btn-ghost" aria-label={copy.reset} title={copy.reset}
          disabled={!input && !error && !evidenceImport.loading} onClick={reset}>
          <RefreshCw aria-hidden="true" />
        </button>
      </div>
      </div>

      <div className="lab-calibration-controls">
        <label>
          <span>{copy.objective}</span>
          <select value={objective} onChange={(event) => {
            invalidateExport(); setObjective(event.target.value as LabObjective);
          }}>
            {(Object.keys(copy.objectives) as LabObjective[]).map((value) => (
              <option key={value} value={value}>{copy.objectives[value]}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{copy.tolerance}: <strong>{tolerance}%</strong></span>
          <input
            type="range"
            min="1"
            max="50"
            value={tolerance}
            onChange={(event) => { invalidateExport(); setTolerance(Number(event.target.value)); }}
          />
        </label>
        <label>
          <span>{copy.cycleBudget}</span>
          <select value={cycleBudget} onChange={(event) => {
            invalidateExport(); setCycleBudget(Number(event.target.value));
          }}>
            {[2, 4, 6, 8, 10, 12].map((value) => (
              <option key={value} value={value}>{value} {copy.cycles}</option>
            ))}
          </select>
        </label>
      </div>

      <LabEvidenceBridgePanel />

      {error ? (
        <div className="lab-deny-banner" role="alert">
          <X aria-hidden="true" /><div><strong>{copy.rejected}</strong><p>{error}</p></div>
        </div>
      ) : !input || !analysis ? (
        <div className="lab-empty-evidence">
          <RefreshCw aria-hidden="true" /><strong>{copy.noInput}</strong>
        </div>
      ) : (
        <div className="lab-calibration-results">
          <div className="lab-calibration-identity">
            <span><small>{copy.job}</small><strong>{input.jobId}</strong></span>
            <span><small>{copy.cycle}</small><strong>{input.cycleOrdinal}</strong></span>
            <span><small>{copy.vehiclePack}</small><strong>{input.vehiclePackId}</strong></span>
            <span><small>{copy.draftOnly}</small><strong>{input.sourceKind}</strong></span>
          </div>

          <section className="lab-calibration-band" aria-labelledby="lab-workflow-title">
            <header><h3 id="lab-workflow-title">{copy.workflow}</h3></header>
            <ol className="lab-stage-list">
              {analysis.stages.map((stage) => (
                <li key={stage.id} data-status={stage.status}>
                  <span aria-hidden="true">{stage.status === "complete" ? <Check /> : <ArrowRight />}</span>
                  <strong>{copy.stages[stage.id as keyof typeof copy.stages]}</strong>
                  <small>{copy.status[stage.status]}</small>
                </li>
              ))}
            </ol>
          </section>

          <section className="lab-calibration-band" aria-labelledby="lab-gap-title">
            <header>
              <div><h3 id="lab-gap-title">{copy.gap}</h3><small>{copy.aggregate}</small></div>
              <strong className={analysis.gapWithinTolerance ? "is-pass" : "is-fail"}>
                {analysis.aggregateGapPercent}%
              </strong>
            </header>
            <div className="lab-gap-table" role="table" aria-label={copy.gap}>
              {analysis.gaps.map((gap) => (
                <div role="row" key={gap.key}>
                  <strong role="rowheader">{copy.metrics[gap.key]}</strong>
                  <span role="cell"><small>{copy.sim}</small>{formatMetric(gap.simulation)}</span>
                  <span role="cell"><small>{copy.real}</small>{formatMetric(gap.real)}</span>
                  <span role="cell" className={gap.withinTolerance ? "is-pass" : "is-fail"}>
                    {gap.percent}%
                  </span>
                </div>
              ))}
            </div>
          </section>

          <div className="lab-actions">
            <Link to="/jobs/new" className="btn btn-primary"><ArrowRight aria-hidden="true" /> {copy.openSim}</Link>
            <button type="button" className="btn" onClick={exportDraft}><Download aria-hidden="true" /> {copy.export}</button>
          </div>
        </div>
      )}
    </section>
  );
}
