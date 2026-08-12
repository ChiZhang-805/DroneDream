import {
  Activity,
  Ban,
  CheckCircle2,
  CircleGauge,
  FileJson2,
  FlaskConical,
  History,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getFieldTuningStatus,
  isDesktopRuntime,
  listFieldHarnessJobs,
  prepareFieldHardwareTuning,
  runFieldHarnessJob,
  runFieldTuningDemo,
  type FieldHarnessJobReceipt,
  type FieldHarnessJobSummary,
  type FieldHarnessParameterBound,
  type FieldHarnessTrialInput,
  type FieldHardwareTuningPlan,
  type FieldParameterSnapshot,
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
    snapshotBound: "Snapshot bound",
    snapshotMissing: "No parameter snapshot bound",
    job: "Harness job",
    writeBudget: "Parameter write budget",
    recordedTitle: "Recorded-device Harness job",
    recordedBody: "Import content-bound trial telemetry collected from this snapshot. The local Model proposes the next bounded candidate; Harness scores every trial, checks the final independent holdout, and stores a tamper-evident receipt.",
    jobName: "Job name",
    jobNameValue: "Field attitude evidence review",
    evidenceJson: "Parameter bounds and recorded trials (JSON)",
    evidenceTemplate: "Create template from snapshot",
    evidenceRun: "Analyze evidence and propose next trial",
    evidenceRunning: "Analyzing evidence...",
    evidenceNeedsSnapshot: "Create or load a parameter snapshot before running a recorded-device job.",
    evidenceInvalid: "The JSON must contain parameterBounds and at least two training trials followed by one independent holdout.",
    proposed: "Next bounded proposal",
    evidenceVerdict: "Recorded evidence verdict",
    hardwareStillDenied: "This result does not write parameters or grant hardware authority.",
    history: "Persisted job history",
    noHistory: "No persisted Harness jobs yet.",
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
    snapshotBound: "已绑定参数快照",
    snapshotMissing: "尚未绑定参数快照",
    job: "Harness 作业",
    writeBudget: "参数写入预算",
    recordedTitle: "真机记录证据 Harness 作业",
    recordedBody: "导入与当前快照绑定的真实试验遥测。Model 提出下一组受步长约束的候选参数，Harness 对试验评分、检查最后一组独立留出证据，并保存防篡改回执。",
    jobName: "作业名称",
    jobNameValue: "现场姿态调参证据复核",
    evidenceJson: "参数边界与真机试验记录（JSON）",
    evidenceTemplate: "根据快照生成模板",
    evidenceRun: "分析证据并提出下一组试验参数",
    evidenceRunning: "正在分析证据...",
    evidenceNeedsSnapshot: "请先创建或加载参数快照，再运行真机记录证据作业。",
    evidenceInvalid: "JSON 必须包含参数边界、至少两组训练试验，以及最后一组独立留出试验。",
    proposed: "下一组受限候选参数",
    evidenceVerdict: "记录证据判定",
    hardwareStillDenied: "该结果不会写入参数，也不会授予真机权限。",
    history: "已保存作业历史",
    noHistory: "尚无已保存的 Harness 作业。",
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
  snapshot,
}: {
  locale: FieldLocale;
  selectedPackId: string;
  selectedControllerId: string;
  snapshot?: FieldParameterSnapshot;
}) {
  const copy = COPY[locale];
  const [objective, setObjective] = useState<string>(copy.objectiveValue);
  const [iterations, setIterations] = useState(5);
  const [targetScore, setTargetScore] = useState(0.55);
  const [status, setStatus] = useState<FieldTuningStatus>(fieldBrowserStatus);
  const [statusSource, setStatusSource] = useState<"native" | "browser">("browser");
  const [receipt, setReceipt] = useState<FieldTuningDemoReceipt | null>(null);
  const [hardwarePlan, setHardwarePlan] = useState<FieldHardwareTuningPlan | null>(null);
  const [jobName, setJobName] = useState<string>(copy.jobNameValue);
  const [evidenceJson, setEvidenceJson] = useState("");
  const [harnessReceipt, setHarnessReceipt] = useState<FieldHarnessJobReceipt | null>(null);
  const [jobHistory, setJobHistory] = useState<FieldHarnessJobSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setObjective(copy.objectiveValue);
    setJobName(copy.jobNameValue);
  }, [copy.jobNameValue, copy.objectiveValue]);

  useEffect(() => {
    if (!isDesktopRuntime()) return;
    void getFieldTuningStatus()
      .then((next) => {
        setStatus(next);
        setStatusSource("native");
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
    void listFieldHarnessJobs()
      .then(setJobHistory)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  const createEvidenceTemplate = () => {
    if (!snapshot) {
      setError(copy.evidenceNeedsSnapshot);
      return;
    }
    const parameterBounds = Object.fromEntries(
      Object.entries(snapshot.parameters).map(([name, value]) => {
        const span = Math.max(Math.abs(value) * 0.25, 0.1);
        return [name, {
          min: Number((value - span).toFixed(6)),
          max: Number((value + span).toFixed(6)),
          maxStep: Number(Math.max(span * 0.1, 0.001).toFixed(6)),
        }];
      }),
    );
    setEvidenceJson(JSON.stringify({ parameterBounds, trials: [] }, null, 2));
    setError(null);
  };

  const runRecordedHarness = async () => {
    if (!snapshot) {
      setError(copy.evidenceNeedsSnapshot);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(evidenceJson) as {
        parameterBounds?: Record<string, FieldHarnessParameterBound>;
        trials?: FieldHarnessTrialInput[];
      };
      if (!parsed.parameterBounds || !Array.isArray(parsed.trials) || parsed.trials.length < 3) {
        throw new Error(copy.evidenceInvalid);
      }
      const next = await runFieldHarnessJob({
        jobName,
        objective,
        targetScore,
        maxIterations: Math.max(iterations, parsed.trials.length - 1),
        deviceObservationId: snapshot.deviceObservationId,
        observationSha256: snapshot.observationSha256,
        snapshotSha256: snapshot.snapshotSha256,
        vehiclePackId: snapshot.vehiclePackId,
        controllerId: snapshot.controllerId,
        firmwareVersion: snapshot.firmwareVersion,
        adapterId: snapshot.adapterId,
        parameterBounds: parsed.parameterBounds,
        trials: parsed.trials,
      });
      setHarnessReceipt(next);
      setJobHistory(await listFieldHarnessJobs());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

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
            deviceObservationId: snapshot?.deviceObservationId ?? null,
            vehiclePackId: selectedPackId,
            controllerId: selectedControllerId,
            firmwareVersion: snapshot?.firmwareVersion ?? "unverified",
            adapterId: snapshot?.adapterId ?? null,
            observationSha256: snapshot?.observationSha256 ?? null,
            snapshotSha256: snapshot?.snapshotSha256 ?? null,
            objective,
            maxIterations: iterations,
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

      <section className="field-recorded-harness" aria-labelledby="field-recorded-harness-title">
        <header>
          <div>
            <h3 id="field-recorded-harness-title"><FileJson2 aria-hidden="true" />{copy.recordedTitle}</h3>
            <p>{copy.recordedBody}</p>
          </div>
          <span><ShieldCheck aria-hidden="true" />hardwareAuthority=false</span>
        </header>
        <div className="field-recorded-harness-grid">
          <label>
            <span>{copy.jobName}</span>
            <input value={jobName} maxLength={80} onChange={(event) => setJobName(event.target.value)} />
          </label>
          <label className="field-recorded-json">
            <span>{copy.evidenceJson}</span>
            <textarea
              value={evidenceJson}
              spellCheck={false}
              rows={10}
              placeholder={'{\n  "parameterBounds": {},\n  "trials": []\n}'}
              onChange={(event) => setEvidenceJson(event.target.value)}
            />
          </label>
          <div className="field-recorded-actions">
            <button type="button" onClick={createEvidenceTemplate}>
              <FileJson2 aria-hidden="true" />{copy.evidenceTemplate}
            </button>
            <button
              type="button"
              className="field-primary-command"
              disabled={busy || !snapshot || jobName.trim() === "" || evidenceJson.trim() === ""}
              onClick={() => void runRecordedHarness()}
            >
              <Sparkles aria-hidden="true" />{busy ? copy.evidenceRunning : copy.evidenceRun}
            </button>
          </div>
        </div>
        {!snapshot ? <p className="field-inline-boundary"><Ban aria-hidden="true" />{copy.evidenceNeedsSnapshot}</p> : null}
        {harnessReceipt ? (
          <div className="field-recorded-result" aria-live="polite">
            <div>
              <span>{copy.evidenceVerdict}</span>
              <strong>{harnessReceipt.qualification.recordedEvidencePassed ? copy.passed : copy.rejected}</strong>
              <code>{compactHash(harnessReceipt.receiptSha256)}</code>
            </div>
            <div>
              <span>{copy.proposed}</span>
              <code>{JSON.stringify(harnessReceipt.proposedParameters)}</code>
              <code>{compactHash(harnessReceipt.proposedCandidateSha256)}</code>
            </div>
            <p><ShieldCheck aria-hidden="true" />{copy.hardwareStillDenied}</p>
          </div>
        ) : null}
        <details className="field-harness-history">
          <summary><History aria-hidden="true" />{copy.history} ({jobHistory.length})</summary>
          {jobHistory.length === 0 ? <p>{copy.noHistory}</p> : (
            <ul>{jobHistory.map((job) => (
              <li key={job.jobId}>
                <strong>{job.jobName}</strong>
                <span>{job.qualificationStatus}</span>
                <code>{compactHash(job.receiptSha256)}</code>
              </li>
            ))}</ul>
          )}
        </details>
      </section>

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
        <span>{snapshot ? copy.snapshotBound : copy.snapshotMissing}</span>
        <code>{snapshot ? compactHash(snapshot.snapshotSha256) : "-"}</code>
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
            <div><h4>{copy.job}</h4><code>{hardwarePlan.jobId}</code></div>
            <div><h4>{copy.writeBudget}</h4><code>{hardwarePlan.budget.parameterWriteBudget}</code></div>
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
