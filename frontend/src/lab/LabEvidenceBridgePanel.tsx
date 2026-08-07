import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { FileCheck2, GitCompareArrows, ShieldX, Upload } from "lucide-react";

import { useI18n } from "../i18n/I18nProvider";
import { LabEvidencePreviewError, parseLabEvidencePreview } from "./evidencePreview";
import type { LabEvidencePreview } from "./evidencePreview";
import {
  FIELD_PRODUCT_SOURCE,
  FieldEvidenceBridgeError,
  evaluateSimFieldBridge,
  parseFieldHarnessReceipt,
} from "./fieldEvidenceBridge";
import type { FieldHarnessReceipt } from "./fieldEvidenceBridge";

const COPY = {
  en: {
    title: "SIM / FIELD evidence bridge",
    sim: "SIM candidate",
    field: "FIELD observation",
    importSim: "Import SIM receipt",
    importField: "Import FIELD receipt",
    missing: "Not bound",
    verified: "Integrity verified",
    waiting: "Waiting for both receipts",
    matched: "Candidate lineage matched · calibration blocked",
    denied: "Evidence mismatch · denied",
    source: "Field source",
    holdout: "Holdout",
    candidate: "Candidate",
    snapshot: "Snapshot",
    blockers: "Remaining gates",
    pass: "Recorded evidence passed",
    safety: "Evidence import never grants hardware authority.",
    error: "Evidence rejected",
  },
  "zh-CN": {
    title: "SIM / FIELD 证据桥",
    sim: "SIM 候选参数",
    field: "FIELD 真实观测",
    importSim: "导入 SIM receipt",
    importField: "导入 FIELD receipt",
    missing: "尚未绑定",
    verified: "完整性已核验",
    waiting: "等待两侧 receipt",
    matched: "候选链路已匹配 · 校准仍阻断",
    denied: "证据不匹配 · 已拒绝",
    source: "Field 来源",
    holdout: "Holdout",
    candidate: "候选参数",
    snapshot: "快照",
    blockers: "剩余门禁",
    pass: "记录证据已通过",
    safety: "导入证据绝不授予真机权限。",
    error: "证据已拒绝",
  },
} as const;

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

export function LabEvidenceBridgePanel() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const [simulation, setSimulation] = useState<LabEvidencePreview | null>(null);
  const [field, setField] = useState<FieldHarnessReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const decision = useMemo(
    () => evaluateSimFieldBridge(simulation, field),
    [field, simulation],
  );

  async function importSimulation(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setSimulation(parseLabEvidencePreview(file.name, await file.text()));
      setError(null);
    } catch (caught) {
      setSimulation(null);
      setError(caught instanceof LabEvidencePreviewError ? caught.message : copy.error);
    }
  }

  async function importField(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setField(await parseFieldHarnessReceipt(file.name, await file.text()));
      setError(null);
    } catch (caught) {
      setField(null);
      setError(caught instanceof FieldEvidenceBridgeError ? caught.message : copy.error);
    }
  }

  const status = decision.state === "waiting-for-evidence"
    ? copy.waiting
    : decision.state === "mismatch-denied"
      ? copy.denied
      : copy.matched;

  return (
    <section
      className="lab-evidence-bridge"
      data-bridge-state={decision.state}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
      aria-labelledby="lab-evidence-bridge-title"
    >
      <header>
        <GitCompareArrows aria-hidden="true" />
        <h3 id="lab-evidence-bridge-title">{copy.title}</h3>
        <strong data-state={decision.state}>{status}</strong>
      </header>

      <div className="lab-evidence-bridge-inputs">
        <div>
          <span><small>{copy.sim}</small><strong>{simulation?.fileName ?? copy.missing}</strong></span>
          <label className="btn lab-file-button">
            <Upload aria-hidden="true" /> {copy.importSim}
            <input type="file" accept="application/json,.json" onChange={importSimulation} />
          </label>
        </div>
        <div>
          <span>
            <small>{copy.field}</small>
            <strong>{field ? `${field.fileName} · ${copy.verified}` : copy.missing}</strong>
          </span>
          <label className="btn lab-file-button">
            <Upload aria-hidden="true" /> {copy.importField}
            <input type="file" accept="application/json,.json" onChange={importField} />
          </label>
        </div>
      </div>

      {error ? (
        <p className="lab-evidence-bridge-error" role="alert">
          <ShieldX aria-hidden="true" /><strong>{copy.error}</strong><span>{error}</span>
        </p>
      ) : field ? (
        <div className="lab-evidence-bridge-binding" aria-live="polite">
          <span><small>{copy.source}</small><strong>{FIELD_PRODUCT_SOURCE.slice(0, 10)}</strong></span>
          <span><small>{copy.holdout}</small><strong>{field.recordedEvidencePassed ? copy.pass : copy.denied}</strong></span>
          <span><small>{copy.candidate}</small><strong>{shortHash(field.selectedCandidateSha256)}</strong></span>
          <span><small>{copy.snapshot}</small><strong>{shortHash(field.snapshotSha256)}</strong></span>
          <FileCheck2 aria-label={copy.verified} />
        </div>
      ) : null}

      {decision.blockers.length > 0 ? (
        <details className="lab-evidence-bridge-blockers">
          <summary>{copy.blockers} · {decision.blockers.length}</summary>
          <ul>{decision.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
        </details>
      ) : null}
      <p className="lab-evidence-bridge-safety"><ShieldX aria-hidden="true" />{copy.safety}</p>
    </section>
  );
}
