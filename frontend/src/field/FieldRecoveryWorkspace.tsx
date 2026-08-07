import {
  ArchiveRestore,
  Ban,
  Braces,
  Check,
  FileDiff,
  HardDrive,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  compareFieldParameterSnapshot,
  createFieldParameterSnapshot,
  isDesktopRuntime,
  prepareFieldParameterRollback,
  type FieldDiscoveredDevice,
  type FieldParameterDiffReceipt,
  type FieldParameterSnapshot,
  type FieldRollbackPlan,
} from "../desktop/bridge";
import type { FieldLocale } from "./catalog";
import type { FieldReadOnlyProtocolEvidence } from "./FieldAdapterCenter";

const COPY = {
  en: {
    title: "Parameter snapshot & recovery",
    body: "Persist an imported read-only parameter set, compare drift, and prepare a content-bound rollback plan before any write is considered.",
    observation: "Observation receipt SHA-256",
    firmware: "Observed firmware",
    adapter: "Protocol adapter",
    baseline: "Baseline parameters (JSON)",
    current: "Current parameters (JSON)",
    capture: "Save snapshot",
    compare: "Compare drift",
    rollback: "Prepare rollback",
    snapshot: "Snapshot",
    parameterSet: "Parameter set",
    changes: "Changed parameters",
    name: "Parameter",
    before: "Snapshot",
    after: "Current",
    delta: "Delta",
    noChanges: "No parameter drift detected.",
    denied: "Rollback execution denied",
    unavailable: "Snapshot tools are available in the installed Field app.",
    invalid: "Enter a JSON object containing 1 to 256 finite numeric parameters.",
    evidence: "Imported values are evidence only. Saving, comparing, or planning never opens a device or grants hardware authority.",
  },
  "zh-CN": {
    title: "参数快照与恢复",
    body: "在考虑任何写入前，保存导入的只读参数集、比较漂移并准备内容绑定的回滚计划。",
    observation: "观察回执 SHA-256",
    firmware: "已观察固件",
    adapter: "通信协议适配器",
    baseline: "基线参数（JSON）",
    current: "当前参数（JSON）",
    capture: "保存快照",
    compare: "比较差异",
    rollback: "准备回滚",
    snapshot: "快照",
    parameterSet: "参数集",
    changes: "变更参数",
    name: "参数",
    before: "快照值",
    after: "当前值",
    delta: "变化量",
    noChanges: "未检测到参数漂移。",
    denied: "回滚执行已拒绝",
    unavailable: "快照工具仅在已安装的 Field 应用中可用。",
    invalid: "请输入包含 1 到 256 个有限数值参数的 JSON 对象。",
    evidence: "导入值仅作为证据。保存、比较或规划不会打开设备，也不会授予真机权限。",
  },
} as const;

const DEFAULT_PARAMETERS = JSON.stringify({
  MC_ROLL_P: 6.5,
  MC_PITCH_P: 6.5,
  MPC_XY_VEL_P_ACC: 1.8,
}, null, 2);

function parseParameters(raw: string): Record<string, number> {
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("shape");
  const entries = Object.entries(parsed);
  if (entries.length === 0 || entries.length > 256) throw new Error("count");
  for (const [name, value] of entries) {
    if (
      !/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(name)
      || typeof value !== "number"
      || !Number.isFinite(value)
      || Math.abs(value) > 1_000_000_000
    ) {
      throw new Error("parameter");
    }
  }
  return Object.fromEntries(entries) as Record<string, number>;
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

export function FieldRecoveryWorkspace({
  locale,
  selectedPackId,
  selectedControllerId,
  device,
  evidence,
}: {
  locale: FieldLocale;
  selectedPackId: string;
  selectedControllerId: string;
  device?: FieldDiscoveredDevice;
  evidence?: FieldReadOnlyProtocolEvidence;
}) {
  const copy = COPY[locale];
  const desktop = isDesktopRuntime();
  const [observationSha256, setObservationSha256] = useState(
    evidence?.observationSha256 ?? device?.observationId ?? "",
  );
  const [firmwareVersion, setFirmwareVersion] = useState("unverified");
  const [adapterId, setAdapterId] = useState("mavlink-common-v2");
  const [baselineText, setBaselineText] = useState(DEFAULT_PARAMETERS);
  const [currentText, setCurrentText] = useState(DEFAULT_PARAMETERS);
  const [snapshot, setSnapshot] = useState<FieldParameterSnapshot | null>(null);
  const [diff, setDiff] = useState<FieldParameterDiffReceipt | null>(null);
  const [rollback, setRollback] = useState<FieldRollbackPlan | null>(null);
  const [busy, setBusy] = useState<"snapshot" | "diff" | "rollback" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (device) setObservationSha256(device.observationId);
  }, [device]);

  useEffect(() => {
    if (!evidence) return;
    setObservationSha256(evidence.observationSha256);
    setAdapterId(evidence.adapterId);
  }, [evidence]);

  const observationValid = /^[a-f0-9]{64}$/.test(observationSha256);
  const identity = useMemo(() => ({
    deviceObservationId: evidence?.deviceObservationId ?? device?.observationId ?? "operator-imported",
    vehiclePackId: selectedPackId,
    controllerId: selectedControllerId,
    firmwareVersion,
    adapterId,
  }), [
    adapterId,
    device?.observationId,
    evidence?.deviceObservationId,
    firmwareVersion,
    selectedControllerId,
    selectedPackId,
  ]);

  const capture = async () => {
    setBusy("snapshot");
    setError(null);
    setDiff(null);
    setRollback(null);
    try {
      const parameters = parseParameters(baselineText);
      const next = await createFieldParameterSnapshot({
        ...identity,
        observationSha256,
        parameters,
      });
      setSnapshot(next);
      setCurrentText(JSON.stringify(parameters, null, 2));
    } catch (reason) {
      setError(reason instanceof SyntaxError || (reason instanceof Error && /shape|count|parameter/.test(reason.message))
        ? copy.invalid
        : reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const compare = async () => {
    if (!snapshot) return;
    setBusy("diff");
    setError(null);
    setRollback(null);
    try {
      setDiff(await compareFieldParameterSnapshot({
        snapshotSha256: snapshot.snapshotSha256,
        currentParameters: parseParameters(currentText),
      }));
    } catch (reason) {
      setError(reason instanceof SyntaxError || (reason instanceof Error && /shape|count|parameter/.test(reason.message))
        ? copy.invalid
        : reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const prepareRollback = async () => {
    if (!snapshot) return;
    setBusy("rollback");
    setError(null);
    try {
      setRollback(await prepareFieldParameterRollback({
        snapshotSha256: snapshot.snapshotSha256,
        currentParameters: parseParameters(currentText),
      }));
    } catch (reason) {
      setError(reason instanceof SyntaxError || (reason instanceof Error && /shape|count|parameter/.test(reason.message))
        ? copy.invalid
        : reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const changes = diff?.changes ?? rollback?.changes ?? [];

  return (
    <div className="field-recovery-workspace" data-authority="false" data-hardware-write-attempts="0">
      <header>
        <div><h2 id="field-recovery-title">{copy.title}</h2><p>{copy.body}</p></div>
        <ArchiveRestore aria-hidden="true" />
      </header>
      <p className="field-inline-boundary"><ShieldCheck aria-hidden="true" />{copy.evidence}</p>
      {!desktop ? <p className="field-adapter-offline"><Ban aria-hidden="true" />{copy.unavailable}</p> : null}

      <div className="field-recovery-identity">
        <label><span>{copy.observation}</span><input value={observationSha256} maxLength={64} spellCheck={false} onChange={(event) => setObservationSha256(event.target.value.trim().toLowerCase())} /></label>
        <label><span>{copy.firmware}</span><input value={firmwareVersion} maxLength={160} onChange={(event) => setFirmwareVersion(event.target.value)} /></label>
        <label><span>{copy.adapter}</span><select value={adapterId} onChange={(event) => setAdapterId(event.target.value)}><option value="mavlink-common-v2">MAVLink Common v2</option><option value="mavlink-ardupilotmega-v2">MAVLink ArduPilotMega v2</option><option value="betaflight-msp-v1">Betaflight / INAV MSP v1</option><option value="crazyflie-crtp">Crazyflie CRTP</option><option value="dronecan-v1">DroneCAN v1</option></select></label>
      </div>

      <div className="field-recovery-editors">
        <label><span><HardDrive aria-hidden="true" />{copy.baseline}</span><textarea rows={9} value={baselineText} spellCheck={false} onChange={(event) => setBaselineText(event.target.value)} /></label>
        <label><span><Braces aria-hidden="true" />{copy.current}</span><textarea rows={9} value={currentText} spellCheck={false} onChange={(event) => setCurrentText(event.target.value)} /></label>
      </div>

      <div className="field-recovery-actions">
        <button type="button" className="field-primary-command" disabled={!desktop || !observationValid || busy !== null} onClick={() => void capture()}><HardDrive aria-hidden="true" />{copy.capture}</button>
        <button type="button" disabled={!desktop || !snapshot || busy !== null} onClick={() => void compare()}><FileDiff aria-hidden="true" />{copy.compare}</button>
        <button type="button" disabled={!desktop || !snapshot || busy !== null} onClick={() => void prepareRollback()}><RotateCcw aria-hidden="true" />{copy.rollback}</button>
      </div>

      {error ? <p className="field-tuning-error" role="alert"><Ban aria-hidden="true" />{error}</p> : null}
      {snapshot ? (
        <div className="field-recovery-receipt" role="status">
          <Check aria-hidden="true" /><span>{copy.snapshot}</span><code>{shortHash(snapshot.snapshotSha256)}</code>
          <span>{copy.parameterSet}</span><code>{shortHash(snapshot.parameterSetSha256)}</code>
        </div>
      ) : null}
      {rollback ? (
        <div className="field-recovery-denial" role="status">
          <Ban aria-hidden="true" /><strong>{copy.denied}</strong><code>canExecute=false · hardwareAuthority=false</code>
          <ul>{rollback.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
        </div>
      ) : null}
      {(diff || rollback) ? (
        <div className="field-table-scroll">
          {changes.length === 0 ? <p>{copy.noChanges}</p> : (
            <table aria-label={copy.changes}>
              <thead><tr><th>{copy.name}</th><th>{copy.before}</th><th>{copy.after}</th><th>{copy.delta}</th></tr></thead>
              <tbody>{changes.map((change) => <tr key={change.name}><td><code>{change.name}</code></td><td>{change.before ?? "-"}</td><td>{change.after ?? "-"}</td><td>{change.delta ?? "-"}</td></tr>)}</tbody>
            </table>
          )}
        </div>
      ) : null}
    </div>
  );
}
