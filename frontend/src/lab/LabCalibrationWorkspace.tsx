import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BrainCircuit,
  Check,
  Download,
  Gauge,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";

import { useI18n } from "../i18n/I18nProvider";
import {
  LabCalibrationInputError,
  analyzeLabCalibration,
  parseLabCalibrationInput,
  serializeLabCalibrationDraftReceipt,
  type LabCalibrationAnalysis,
  type LabCalibrationInput,
  type LabObjective,
} from "./calibrationWorkflow";
import { LabEvidenceBridgePanel } from "./LabEvidenceBridgePanel";

const COPY = {
  en: {
    title: "Bidirectional calibration loop",
    subtitle: "One evidence-bound job carries each candidate from simulation into real observation, model revision, resimulation, holdout, and qualification.",
    model: "Model",
    modelState: "Proposal only",
    harness: "Harness",
    harnessState: "Constraints enforced",
    authority: "Hardware",
    authorityState: "DENY",
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
    noInputBody: "The Harness is idle. Model requests, experiments, provider calls, and hardware actions remain at zero.",
    rejected: "Evidence rejected",
    workflow: "Job progression",
    gap: "Sim-real gap",
    aggregate: "Aggregate gap",
    next: "Next Harness action",
    recommendations: "Model revision inputs",
    sim: "SIM",
    real: "REAL",
    export: "Export draft receipt",
    openSim: "Open simulation optimization",
    draftOnly: "DRAFT · NOT QUALIFIED",
    qualification: "Qualification",
    qualificationBody: "Independent holdout and a validated Vehicle Pack are required before trusted evidence can be issued.",
    safety: "Imported evidence and exported drafts never grant hardware authority.",
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
    actions: {
      "revise-model-and-resimulate": "Revise the model, propose a new candidate, then resimulate within the frozen budget.",
      "await-independent-holdout": "Freeze the calibrated model and run the independent holdout before qualification.",
    },
    reasons: {
      "zero-validated-vehicle-packs": "Denied: zero validated Vehicle Packs",
      "gap-outside-tolerance": "Denied: sim-real gap exceeds tolerance",
    },
  },
  "zh-CN": {
    title: "双向校准闭环",
    subtitle: "同一份证据绑定作业将候选参数从仿真带入真实观测，再完成模型修正、重仿真、独立 holdout 与资格判定。",
    model: "Model",
    modelState: "仅提出建议",
    harness: "Harness",
    harnessState: "强制约束",
    authority: "真机权限",
    authorityState: "拒绝",
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
    noInputBody: "Harness 当前空闲；Model 请求、实验、provider 调用和真机动作次数均为零。",
    rejected: "证据已拒绝",
    workflow: "作业进程",
    gap: "仿真与真实差距",
    aggregate: "综合差距",
    next: "下一项 Harness 动作",
    recommendations: "模型修正输入",
    sim: "仿真",
    real: "真实",
    export: "导出草稿 receipt",
    openSim: "打开仿真优化",
    draftOnly: "草稿 · 尚未取得资格",
    qualification: "资格判定",
    qualificationBody: "签发可信证据前必须通过独立 holdout，并使用已验证的 Vehicle Pack。",
    safety: "导入证据与导出草稿均不会授予真机权限。",
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
      "independent-holdout": "独立 holdout",
      "qualification-and-evidence": "资格证据",
      "field-handoff": "FIELD 交接",
    },
    actions: {
      "revise-model-and-resimulate": "修正模型，在冻结预算内提出下一组候选参数并重新仿真。",
      "await-independent-holdout": "冻结校准模型，完成独立 holdout 后再进行资格判定。",
    },
    reasons: {
      "zero-validated-vehicle-packs": "拒绝：已验证 Vehicle Pack 数量为零",
      "gap-outside-tolerance": "拒绝：仿真与真实差距超出容限",
    },
  },
} as const;

function formatMetric(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

export function LabCalibrationWorkspace() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const [objective, setObjective] = useState<LabObjective>("tracking");
  const [tolerance, setTolerance] = useState(15);
  const [cycleBudget, setCycleBudget] = useState(4);
  const [input, setInput] = useState<LabCalibrationInput | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    try {
      setInput(parseLabCalibrationInput(file.name, await file.text()));
      setError(null);
    } catch (caught) {
      setInput(null);
      setError(caught instanceof LabCalibrationInputError
        ? caught.message
        : "The evidence could not be inspected.");
    }
  }

  function reset() {
    setInput(null);
    setError(null);
  }

  function exportDraft() {
    if (!input || !analysis) return;
    const blob = new Blob(
      [serializeLabCalibrationDraftReceipt(input, analysis)],
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
      <div className="lab-tool-intro">
        <RefreshCw aria-hidden="true" />
        <div><h2>{copy.title}</h2><p>{copy.subtitle}</p></div>
      </div>

      <div className="lab-role-strip" aria-label={copy.title}>
        <span><BrainCircuit aria-hidden="true" /><small>{copy.model}</small><strong>{copy.modelState}</strong></span>
        <span><Gauge aria-hidden="true" /><small>{copy.harness}</small><strong>{copy.harnessState}</strong></span>
        <span className="is-denied"><LockKeyhole aria-hidden="true" /><small>{copy.authority}</small><strong>{copy.authorityState}</strong></span>
      </div>

      <LabEvidenceBridgePanel />

      <div className="lab-calibration-controls">
        <label>
          <span>{copy.objective}</span>
          <select value={objective} onChange={(event) => setObjective(event.target.value as LabObjective)}>
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
            onChange={(event) => setTolerance(Number(event.target.value))}
          />
        </label>
        <label>
          <span>{copy.cycleBudget}</span>
          <select value={cycleBudget} onChange={(event) => setCycleBudget(Number(event.target.value))}>
            {[2, 4, 6, 8, 10, 12].map((value) => (
              <option key={value} value={value}>{value} {copy.cycles}</option>
            ))}
          </select>
        </label>
        <div className="lab-calibration-import">
          <label className="btn lab-file-button">
            <Upload aria-hidden="true" /> {copy.import}
            <input type="file" accept="application/json,.json" onChange={importEvidence} />
          </label>
          <button type="button" className="btn btn-ghost" disabled={!input && !error} onClick={reset}>
            <RefreshCw aria-hidden="true" /> {copy.reset}
          </button>
        </div>
      </div>

      {error ? (
        <div className="lab-deny-banner" role="alert">
          <X aria-hidden="true" /><div><strong>{copy.rejected}</strong><p>{error}</p></div>
        </div>
      ) : !input || !analysis ? (
        <div className="lab-empty-evidence">
          <RefreshCw aria-hidden="true" /><strong>{copy.noInput}</strong><p>{copy.noInputBody}</p>
        </div>
      ) : (
        <>
          <div className="lab-calibration-identity">
            <span><small>Job</small><strong>{input.jobId}</strong></span>
            <span><small>Cycle</small><strong>{input.cycleOrdinal}</strong></span>
            <span><small>Vehicle Pack</small><strong>{input.vehiclePackId}</strong></span>
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

          <div className="lab-next-action">
            <BrainCircuit aria-hidden="true" />
            <div>
              <small>{copy.next}</small>
              <strong>{copy.actions[analysis.nextAction]}</strong>
              <span>{copy.recommendations}: {analysis.recommendations.join(" · ")}</span>
            </div>
          </div>

          <div className="lab-qualification-deny" role="status">
            <ShieldCheck aria-hidden="true" />
            <div><strong>{copy.qualification}: {copy.reasons[analysis.qualificationReason]}</strong><p>{copy.qualificationBody}</p><small>{copy.safety}</small></div>
          </div>

          <div className="lab-actions">
            <Link to="/jobs/new" className="btn btn-primary"><ArrowRight aria-hidden="true" /> {copy.openSim}</Link>
            <button type="button" className="btn" onClick={exportDraft}><Download aria-hidden="true" /> {copy.export}</button>
            <button type="button" className="btn" disabled><LockKeyhole aria-hidden="true" /> {copy.authorityState}</button>
          </div>
        </>
      )}
    </section>
  );
}
