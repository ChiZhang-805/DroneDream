import {
  Ban,
  CheckCircle2,
  CircleOff,
  ClipboardCheck,
  MapPinned,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";

import {
  isDesktopRuntime,
  prepareFieldPreflight,
  type FieldParameterSnapshot,
  type FieldPreflightPlan,
} from "../desktop/bridge";
import { localeSafeError } from "../i18n/I18nProvider";
import type { FieldLocale } from "./catalog";
import { FIELD_HARDWARE_ACTIONS } from "./safety";

const COPY = {
  en: {
    preflightTitle: "Preflight quorum",
    preflightBody: "Evaluate source-bound aircraft, snapshot, zone, and operator evidence. Evaluation never grants control.",
    zoneName: "Operating zone",
    radius: "Radius (m)",
    altitude: "Maximum altitude (m)",
    evaluate: "Evaluate preflight",
    evaluateFailed: "Preflight evaluation failed.",
    unavailable: "Native preflight evaluation is available in the installed Field app.",
    acknowledgement: "I confirm the declared zone and understand that this local record is not signed authority.",
    localOnly: "Local only",
    missing: "Missing",
    denied: "Denied",
    blockers: "Blocking evidence",
    plan: "Plan",
    controlTitle: "Takeover & emergency",
    controlBody: "Control commands remain unavailable until the native safety contract is complete.",
    takeover: "Request takeover",
    emergency: "Emergency stop",
    actionMatrix: "Hardware action decisions",
    action: {
      "parameter-write": "Parameter write",
      "rollback-apply": "Rollback apply",
      takeover: "Takeover",
      "emergency-stop": "Emergency stop",
      arm: "Arm",
      flight: "Flight",
    },
    quorum: {
      vehiclePack: "Vehicle Pack",
      controller: "Controller",
      firmware: "Firmware",
      observation: "Protocol observation",
      snapshot: "Parameter snapshot",
      zone: "Operating zone",
      operatorConfirmation: "Operator confirmation",
      nativeBackendRuntime: "Native/backend/runtime",
      policy: "Policy decision",
    },
  },
  "zh-CN": {
    preflightTitle: "飞前仲裁",
    preflightBody: "评估源绑定的机型、快照、区域和操作者证据；评估本身永远不授予控制权限。",
    zoneName: "作业区域",
    radius: "半径（米）",
    altitude: "最大高度（米）",
    evaluate: "评估飞前条件",
    evaluateFailed: "飞前条件评估失败。",
    unavailable: "原生飞前评估仅在已安装的 Field 应用中可用。",
    acknowledgement: "我确认所声明的区域，并理解此本地记录不是签名权限证据。",
    localOnly: "仅本地",
    missing: "缺失",
    denied: "已拒绝",
    blockers: "阻断证据",
    plan: "计划",
    controlTitle: "接管与紧急操作",
    controlBody: "原生安全合同完整闭合前，所有控制命令保持不可用。",
    takeover: "请求接管",
    emergency: "紧急停止",
    actionMatrix: "真机动作决策",
    action: {
      "parameter-write": "写入参数",
      "rollback-apply": "应用回滚",
      takeover: "接管",
      "emergency-stop": "紧急停止",
      arm: "解锁",
      flight: "飞行",
    },
    quorum: {
      vehiclePack: "机型包",
      controller: "飞控",
      firmware: "固件",
      observation: "协议观察",
      snapshot: "参数快照",
      zone: "作业区域",
      operatorConfirmation: "操作者确认",
      nativeBackendRuntime: "原生/后端/运行时",
      policy: "策略决策",
    },
  },
} as const;

function shortHash(value: string): string {
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

export function FieldPreflightWorkspace({
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
  const desktop = isDesktopRuntime();
  const [zoneName, setZoneName] = useState("Indoor cage A");
  const [zoneRadiusM, setZoneRadiusM] = useState(12);
  const [maxAltitudeM, setMaxAltitudeM] = useState(5);
  const [operatorConfirmed, setOperatorConfirmed] = useState(false);
  const [plan, setPlan] = useState<FieldPreflightPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evaluate = async () => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await prepareFieldPreflight({
        vehiclePackId: selectedPackId,
        controllerId: selectedControllerId,
        firmwareVersion: snapshot?.firmwareVersion ?? "unverified",
        deviceObservationId: snapshot?.deviceObservationId ?? null,
        observationSha256: snapshot?.observationSha256 ?? null,
        snapshotSha256: snapshot?.snapshotSha256 ?? null,
        zoneName,
        zoneRadiusM,
        maxAltitudeM,
        operatorConfirmed,
      }));
    } catch (reason) {
      setPlan(null);
      setError(localeSafeError(reason, locale, {
        zh: COPY["zh-CN"].evaluateFailed,
        en: COPY.en.evaluateFailed,
      }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section
        id="preflight"
        className="field-section field-preflight-workspace"
        aria-labelledby="field-preflight-title"
        data-authority="false"
      >
        <header>
          <div><h2 id="field-preflight-title">{copy.preflightTitle}</h2><p>{copy.preflightBody}</p></div>
          <ClipboardCheck aria-hidden="true" />
        </header>
        {!desktop ? <p className="field-adapter-offline"><Ban aria-hidden="true" />{copy.unavailable}</p> : null}
        <div className="field-preflight-inputs">
          <label><span>{copy.zoneName}</span><input value={zoneName} maxLength={160} onChange={(event) => setZoneName(event.target.value)} /></label>
          <label><span>{copy.radius}</span><input type="number" min={1} max={10_000} value={zoneRadiusM} onChange={(event) => setZoneRadiusM(Number(event.target.value))} /></label>
          <label><span>{copy.altitude}</span><input type="number" min={1} max={1_000} value={maxAltitudeM} onChange={(event) => setMaxAltitudeM(Number(event.target.value))} /></label>
        </div>
        <label className="field-operator-acknowledgement">
          <input type="checkbox" checked={operatorConfirmed} onChange={(event) => setOperatorConfirmed(event.target.checked)} />
          <span><strong>{copy.acknowledgement}</strong><small>{operatorConfirmed ? copy.localOnly : copy.missing}</small></span>
        </label>
        <button
          type="button"
          className="field-preflight-evaluate"
          disabled={!desktop || busy}
          onClick={() => void evaluate()}
        ><MapPinned aria-hidden="true" />{copy.evaluate}</button>
        {error ? <p className="field-tuning-error" role="alert"><Ban aria-hidden="true" />{error}</p> : null}
        {plan ? (
          <>
            <div className="field-gate-grid" role="status">
              {Object.entries(plan.quorum).map(([key, status]) => (
                <div key={key} data-local-only={status === "local-only" ? "true" : undefined}>
                  {status === "matched" || status === "present"
                    ? <CheckCircle2 aria-hidden="true" />
                    : <CircleOff aria-hidden="true" />}
                  <span>{copy.quorum[key as keyof typeof copy.quorum] ?? key}</span>
                  <strong>{status}</strong>
                </div>
              ))}
            </div>
            <div className="field-recovery-denial" role="status">
              <Ban aria-hidden="true" /><strong>{copy.blockers}</strong>
              <code>{copy.plan} {shortHash(plan.planSha256)}</code>
              <ul>{plan.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
            </div>
          </>
        ) : null}
      </section>

      <section id="control" className="field-section" aria-labelledby="field-control-title">
        <header><div><h2 id="field-control-title">{copy.controlTitle}</h2><p>{copy.controlBody}</p></div><ShieldAlert aria-hidden="true" /></header>
        <div className="field-control-buttons">
          <button type="button" disabled><SlidersHorizontal aria-hidden="true" />{copy.takeover}</button>
          <button type="button" disabled><ShieldAlert aria-hidden="true" />{copy.emergency}</button>
        </div>
        <h3>{copy.actionMatrix}</h3>
        <div className="field-action-matrix">
          {FIELD_HARDWARE_ACTIONS.map((action) => (
            <div key={action}><CircleOff aria-hidden="true" /><span>{copy.action[action]}</span><strong>{plan?.actionDecisions[action] ?? copy.denied}</strong></div>
          ))}
        </div>
      </section>
    </>
  );
}
