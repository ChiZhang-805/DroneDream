import {
  Activity,
  Ban,
  CheckCircle2,
  CircleGauge,
  FlaskConical,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getFieldTuningStatus,
  isDesktopRuntime,
  prepareFieldHardwareTuning,
  runFieldTuningDemo,
  type FieldHardwareTuningPlan,
  type FieldTuningDemoReceipt,
  type FieldTuningStatus,
} from "../desktop/bridge";
import type { FieldLocale } from "./catalog";
import {
  fieldBrowserHardwareDenial,
  fieldBrowserStatus,
  runFieldBrowserFixture,
} from "./tuning";

const COPY = {
  en: {
    title: "Autonomous field tuning",
    body: "Model proposes bounded candidates. Harness runs the controlled experiment, scores telemetry, classifies failures, and preserves rollback evidence.",
    domain: "Real-device domain",
    noSimulation: "No simulation stage",
    authority: "Hardware authority",
    denied: "Denied",
    model: "Model proposes",
    harness: "Harness controls",
    evidence: "Evidence qualifies",
    objective: "Tuning objective",
    objectiveValue: "Reduce attitude tracking error without increasing control effort",
    iterations: "Iteration budget",
    target: "Target score",
    demo: "Run safe tuning demo",
    running: "Running bounded loop...",
    demoBoundary: "Fixture telemetry only. No device discovery, parameter write, arm, or flight occurs.",
    native: "Native contract",
    browser: "Browser fixture",
    candidates: "Candidate history",
    iteration: "Iteration",
    proposal: "Parameter proposal",
    tracking: "Tracking error",
    overshoot: "Overshoot",
    effort: "Control effort",
    score: "Score",
    verdict: "Verdict",
    selected: "Selected",
    observed: "Observed",
    holdout: "Independent holdout",
    passed: "Passed",
    rejected: "Rejected",
    demoOnly: "Demo-qualified only",
    notHardwareEvidence: "The receipt is content-bound demonstration evidence and is never valid for hardware.",
    hardwareGate: "Real-hardware execution gate",
    gateBody: "A real tuning job is prepared separately and must satisfy every compatibility, recovery, operator, and native authority gate.",
    evaluate: "Evaluate current hardware gate",
    blockers: "Current blockers",
    required: "Required evidence",
    unavailable: "Native Field contract unavailable",
  },
  "zh-CN": {
    title: "真机自主调参",
    body: "Model 提出受边界约束的候选参数，Harness 负责受控实验、遥测评分、失败分类和回滚证据。",
    domain: "真机实验域",
    noSimulation: "无仿真阶段",
    authority: "真机权限",
    denied: "已拒绝",
    model: "Model 提出候选",
    harness: "Harness 受控执行",
    evidence: "证据完成判定",
    objective: "调参目标",
    objectiveValue: "在不增加控制开销的前提下降低姿态跟踪误差",
    iterations: "迭代预算",
    target: "目标分数",
    demo: "运行安全调参演示",
    running: "正在执行受限闭环...",
    demoBoundary: "仅使用测试遥测，不发现设备、不写参数、不解锁、不飞行。",
    native: "原生合同",
    browser: "浏览器测试数据",
    candidates: "候选参数历史",
    iteration: "迭代",
    proposal: "参数候选",
    tracking: "跟踪误差",
    overshoot: "超调",
    effort: "控制开销",
    score: "分数",
    verdict: "结果",
    selected: "已选择",
    observed: "已观测",
    holdout: "独立留出验证",
    passed: "通过",
    rejected: "未通过",
    demoOnly: "仅演示通过",
    notHardwareEvidence: "该回执仅为内容绑定的演示证据，永远不能作为真机资格证据。",
    hardwareGate: "真机执行安全门",
    gateBody: "真实调参任务必须单独准备，并同时满足兼容性、恢复、操作者确认和原生权限要求。",
    evaluate: "评估当前真机安全门",
    blockers: "当前阻断",
    required: "必需证据",
    unavailable: "原生 Field 合同不可用",
  },
} as const;

function compactHash(value: string): string {
  const hash = value.startsWith("sha256:") ? value.slice(7) : value;
  return `${hash.slice(0, 8)}...${hash.slice(-6)}`;
}

export function FieldTuningWorkspace({
  locale,
  selectedPackId,
  selectedControllerId,
}: {
  locale: FieldLocale;
  selectedPackId: string;
  selectedControllerId: string;
}) {
  const copy = COPY[locale];
  const [objective, setObjective] = useState<string>(copy.objectiveValue);
  const [iterations, setIterations] = useState(5);
  const [targetScore, setTargetScore] = useState(0.55);
  const [status, setStatus] = useState<FieldTuningStatus>(fieldBrowserStatus);
  const [statusSource, setStatusSource] = useState<"native" | "browser">("browser");
  const [receipt, setReceipt] = useState<FieldTuningDemoReceipt | null>(null);
  const [hardwarePlan, setHardwarePlan] = useState<FieldHardwareTuningPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setObjective(copy.objectiveValue);
  }, [copy.objectiveValue]);

  useEffect(() => {
    if (!isDesktopRuntime()) return;
    void getFieldTuningStatus()
      .then((next) => {
        setStatus(next);
        setStatusSource("native");
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  const selectedCandidate = useMemo(
    () => receipt?.candidates.find(
      (candidate) => candidate.candidateSha256 === receipt.selectedCandidateSha256,
    ) ?? null,
    [receipt],
  );

  const runDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      const request = { objective, maxIterations: iterations, targetScore };
      setReceipt(
        isDesktopRuntime()
          ? await runFieldTuningDemo(request)
          : runFieldBrowserFixture(request),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const evaluateHardwareGate = async () => {
    setError(null);
    try {
      setHardwarePlan(
        isDesktopRuntime()
          ? await prepareFieldHardwareTuning({
            deviceId: "unbound-device",
            vehiclePackId: selectedPackId,
            controllerId: selectedControllerId,
            firmwareVersion: "unverified",
            objective,
          })
          : fieldBrowserHardwareDenial(),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="field-tuning-workspace" data-authority="false" data-simulation="false">
      <header className="field-tuning-header">
        <div>
          <h2 id="field-tuning-title">{copy.title}</h2>
          <p>{copy.body}</p>
        </div>
        <div className="field-tuning-domain" aria-label={copy.domain}>
          <span><RadioStatus />{copy.domain}</span>
          <span><Ban aria-hidden="true" />{copy.noSimulation}</span>
          <span><ShieldCheck aria-hidden="true" />{copy.authority}: {copy.denied}</span>
        </div>
      </header>

      <ol className="field-tuning-flow" aria-label={copy.title}>
        <li><Sparkles aria-hidden="true" /><span>01</span><strong>{copy.model}</strong></li>
        <li><FlaskConical aria-hidden="true" /><span>02</span><strong>{copy.harness}</strong></li>
        <li><ShieldCheck aria-hidden="true" /><span>03</span><strong>{copy.evidence}</strong></li>
      </ol>

      <div className="field-tuning-controls">
        <label>
          <span>{copy.objective}</span>
          <input value={objective} maxLength={120} onChange={(event) => setObjective(event.target.value)} />
        </label>
        <label>
          <span>{copy.iterations}</span>
          <input
            type="number"
            min={2}
            max={8}
            value={iterations}
            onChange={(event) => setIterations(Math.max(2, Math.min(8, Number(event.target.value))))}
          />
        </label>
        <label>
          <span>{copy.target}</span>
          <input
            type="number"
            min={0.15}
            max={0.9}
            step={0.01}
            value={targetScore}
            onChange={(event) => setTargetScore(Number(event.target.value))}
          />
        </label>
        <button type="button" className="field-primary-command" disabled={busy || objective.trim() === ""} onClick={() => void runDemo()}>
          <Play aria-hidden="true" />{busy ? copy.running : copy.demo}
        </button>
      </div>
      <p className="field-inline-boundary"><ShieldCheck aria-hidden="true" />{copy.demoBoundary}</p>
      <div className="field-contract-line">
        <span>{statusSource === "native" ? copy.native : copy.browser}</span>
        <code>{compactHash(status.contractSha256)}</code>
        <span>{status.validatedPackCount} validated packs</span>
      </div>

      {error ? <div className="field-tuning-error" role="alert"><Ban aria-hidden="true" />{copy.unavailable}: {error}</div> : null}

      {receipt ? (
        <div className="field-tuning-results" aria-live="polite">
          <section aria-labelledby="field-candidates-title">
            <header><h3 id="field-candidates-title">{copy.candidates}</h3><Activity aria-hidden="true" /></header>
            <div className="field-table-scroll">
              <table>
                <thead><tr><th>{copy.iteration}</th><th>{copy.proposal}</th><th>{copy.tracking}</th><th>{copy.overshoot}</th><th>{copy.effort}</th><th>{copy.score}</th><th>{copy.verdict}</th></tr></thead>
                <tbody>
                  {receipt.candidates.map((candidate) => {
                    const selected = candidate.candidateSha256 === receipt.selectedCandidateSha256;
                    return (
                      <tr key={candidate.candidateSha256} data-selected={selected || undefined}>
                        <td>{candidate.iteration}</td>
                        <td><code>R {candidate.parameters.MC_ROLL_P?.toFixed(2)} / P {candidate.parameters.MC_PITCH_P?.toFixed(2)}</code></td>
                        <td>{candidate.trackingError.toFixed(3)}</td>
                        <td>{candidate.overshootPercent.toFixed(1)}%</td>
                        <td>{candidate.controlEffort.toFixed(3)}</td>
                        <td><strong>{candidate.score.toFixed(3)}</strong></td>
                        <td>{selected ? <span className="field-result-selected"><CheckCircle2 aria-hidden="true" />{copy.selected}</span> : copy.observed}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <aside className="field-holdout" aria-label={copy.holdout}>
            <CircleGauge aria-hidden="true" />
            <div><span>{copy.holdout}</span><strong>{receipt.holdout.score.toFixed(3)}</strong></div>
            <div><span>{copy.verdict}</span><strong>{receipt.holdout.passed ? copy.passed : copy.rejected}</strong></div>
            <div><span>{copy.demoOnly}</span><code>{selectedCandidate ? compactHash(selectedCandidate.candidateSha256) : "-"}</code></div>
            <p>{copy.notHardwareEvidence}</p>
          </aside>
        </div>
      ) : null}

      <section className="field-hardware-gate" aria-labelledby="field-hardware-gate-title">
        <header><div><h3 id="field-hardware-gate-title">{copy.hardwareGate}</h3><p>{copy.gateBody}</p></div><ShieldCheck aria-hidden="true" /></header>
        <button type="button" onClick={() => void evaluateHardwareGate()}><ShieldCheck aria-hidden="true" />{copy.evaluate}</button>
        {hardwarePlan ? (
          <div className="field-gate-evidence" role="status">
            <div><h4>{copy.blockers}</h4><ul>{hardwarePlan.blockers.map((item) => <li key={item}>{item}</li>)}</ul></div>
            <div><h4>{copy.required}</h4><ul>{hardwarePlan.requiredEvidence.map((item) => <li key={item}>{item}</li>)}</ul></div>
            <p><RotateCcw aria-hidden="true" />canExecute=false · hardwareAuthority=false</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function RadioStatus() {
  return <span className="field-live-indicator" aria-hidden="true" />;
}
