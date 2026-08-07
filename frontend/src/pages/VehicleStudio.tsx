import {
  Box,
  ChevronRight,
  Download,
  History,
  PackageCheck,
  Plus,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { useAuth } from "../features/auth/AuthContext";
import {
  buildVehiclePackDraft,
  verifyVehiclePackDraft,
  type VehiclePackDraftEnvelope,
} from "../features/vehicleStudio/pack";
import {
  createVehicleModelDraft,
  validateVehicleModel,
  type AutopilotFamily,
  type VehicleClass,
  type VehicleModelDraft,
  type VehiclePackTargetEdition,
} from "../features/vehicleStudio/model";
import {
  loadVehicleModels,
  nextVehicleRevision,
  removeVehicleModel,
  restoreVehicleRevision,
  saveVehicleModel,
  type StoredVehicleModel,
} from "../features/vehicleStudio/storage";
import { useI18n } from "../i18n/I18nProvider";

type StudioTab = "identity" | "airframe" | "propulsion" | "avionics" | "share";
const MAX_VEHICLE_PACK_DRAFT_BYTES = 2_500_000;

const COPY = {
  en: {
    eyebrow: "UNIVERSAL EXCLUSIVE",
    title: "Vehicle Studio",
    subtitle: "Define a drone once, keep its revisions, and export a verifiable Vehicle Pack draft for SIM, LAB, or FIELD.",
    safety: "A draft is unsigned and unvalidated. Exporting or importing it never installs a module, starts Model + Harness, or grants simulation or hardware authority.",
    newModel: "New model",
    savedModels: "Saved models",
    noModels: "No saved models yet.",
    revision: "Revision",
    saveRevision: "Save new revision",
    delete: "Delete model",
    identity: "Identity",
    airframe: "Airframe",
    propulsion: "Propulsion",
    avionics: "Avionics",
    share: "Pack & share",
    modelName: "Model name",
    manufacturer: "Manufacturer",
    vehicleClass: "Vehicle class",
    bodyShape: "Body shape",
    mass: "Total vehicle mass (kg)",
    length: "Length (m)",
    width: "Width (m)",
    height: "Height (m)",
    motors: "Motor count",
    armLength: "Arm length (m)",
    propeller: "Propeller diameter (m)",
    thrust: "Maximum thrust per motor (N)",
    batteryCells: "Battery cells",
    batteryCapacity: "Battery capacity (mAh)",
    autopilot: "Autopilot family",
    controller: "Flight controller",
    firmware: "Firmware version",
    controlTarget: "Primary control target",
    sensors: "Sensor set",
    targets: "Target Editions",
    notes: "Engineering notes",
    preview: "Geometry preview",
    ratio: "Thrust-to-weight",
    issues: "Resolve these model issues before export",
    ready: "Model contract is internally consistent",
    export: "Export Vehicle Pack draft",
    import: "Import Vehicle Pack draft",
    imported: "Imported as a new local model draft.",
    importFailed: "The Vehicle Pack draft could not be imported.",
    exportFailed: "The Vehicle Pack draft could not be exported.",
    saveFailed: "The model could not be saved in local storage.",
    deleteFailed: "The local model could not be deleted.",
    fileTooLarge: "The Vehicle Pack draft exceeds the 2.5 MB import limit.",
    exportReady: "The export contains a generated Gazebo SDF and a canonical SHA-256 envelope.",
    packBoundary: "Receiving Editions must verify the envelope again. SIM may use generated assets only after its own compatibility gate; LAB/FIELD hardware use remains denied until signed validation evidence exists.",
    history: "Revision history",
    restore: "Restore as new revision",
  },
  "zh-CN": {
    eyebrow: "UNIVERSAL 专属能力",
    title: "无人机建模工作室",
    subtitle: "一次定义无人机，持续保存版本，并为 SIM、LAB 或 FIELD 导出可复核的 Vehicle Pack 草稿。",
    safety: "草稿未经签名和验证。导入或导出不会安装模块、启动 Model + Harness，也不会授予仿真或真机权限。",
    newModel: "新建模型",
    savedModels: "已保存模型",
    noModels: "还没有保存的模型。",
    revision: "版本",
    saveRevision: "保存新版本",
    delete: "删除模型",
    identity: "基本信息",
    airframe: "机体结构",
    propulsion: "动力系统",
    avionics: "飞控与传感器",
    share: "生成与共享",
    modelName: "模型名称",
    manufacturer: "制造方",
    vehicleClass: "机型类别",
    bodyShape: "机体形状",
    mass: "整机总质量（kg）",
    length: "长度（m）",
    width: "宽度（m）",
    height: "高度（m）",
    motors: "电机数量",
    armLength: "机臂长度（m）",
    propeller: "桨叶直径（m）",
    thrust: "单电机最大推力（N）",
    batteryCells: "电池串数",
    batteryCapacity: "电池容量（mAh）",
    autopilot: "飞控系统",
    controller: "飞控硬件",
    firmware: "固件版本",
    controlTarget: "主要控制目标",
    sensors: "传感器组合",
    targets: "目标版本",
    notes: "工程说明",
    preview: "几何预览",
    ratio: "推重比",
    issues: "导出前需要解决以下模型问题",
    ready: "模型合同内部一致",
    export: "导出 Vehicle Pack 草稿",
    import: "导入 Vehicle Pack 草稿",
    imported: "已作为新的本地模型草稿导入。",
    importFailed: "无法导入这个 Vehicle Pack 草稿。",
    exportFailed: "无法导出这个 Vehicle Pack 草稿。",
    saveFailed: "无法将模型保存到本地存储。",
    deleteFailed: "无法删除这个本地模型。",
    fileTooLarge: "Vehicle Pack 草稿超过 2.5 MB 导入上限。",
    exportReady: "导出包包含自动生成的 Gazebo SDF 和可复算的 SHA-256 完整性封装。",
    packBoundary: "接收端必须再次验证封装。SIM 仍需通过自身兼容性门才能使用生成资产；LAB/FIELD 在获得签名验证证据前继续拒绝真机用途。",
    history: "版本历史",
    restore: "恢复为新版本",
  },
} as const;

const TABS: StudioTab[] = ["identity", "airframe", "propulsion", "avionics", "share"];
const SENSOR_TYPES = ["imu", "gps", "barometer", "magnetometer", "camera", "lidar"] as const;
const TARGET_EDITIONS: VehiclePackTargetEdition[] = ["sim", "lab", "field"];

function numberValue(event: ChangeEvent<HTMLInputElement>): number {
  return Number(event.target.value);
}

function downloadEnvelope(envelope: VehiclePackDraftEnvelope) {
  const blob = new Blob([`${JSON.stringify(envelope, null, 2)}\n`], {
    type: "application/vnd.dronedream.vehicle-pack-draft+json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${envelope.payload.packId}-${envelope.payload.packVersion}.ddvp.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ModelPreview({ draft }: { draft: VehicleModelDraft }) {
  const rotorAngles = Array.from(
    { length: draft.propulsion.motorCount },
    (_, index) => (Math.PI * 2 * index) / draft.propulsion.motorCount,
  );
  const ratio = draft.propulsion.motorCount * draft.propulsion.maximumThrustPerMotorN
    / Math.max(0.001, draft.body.massKg * 9.80665);
  return (
    <div className="vehicle-model-preview" data-testid="vehicle-model-preview">
      <svg viewBox="0 0 320 240" role="img" aria-label={draft.name}>
        <defs>
          <linearGradient id="vehicleStudioGradient" x1="0" x2="1">
            <stop offset="0" stopColor="var(--dd-brand-start)" />
            <stop offset="0.52" stopColor="var(--dd-brand-middle)" />
            <stop offset="1" stopColor="var(--dd-brand-end)" />
          </linearGradient>
        </defs>
        {rotorAngles.map((angle, index) => {
          const x = 160 + Math.cos(angle) * 82;
          const y = 112 + Math.sin(angle) * 72;
          return (
            <g key={index}>
              <line x1="160" y1="112" x2={x} y2={y} className="vehicle-preview-arm" />
              <ellipse cx={x} cy={y} rx="27" ry="8" className="vehicle-preview-rotor" />
              <circle cx={x} cy={y} r="7" className="vehicle-preview-motor" />
            </g>
          );
        })}
        <rect x="122" y="84" width="76" height="56" rx="18" fill="url(#vehicleStudioGradient)" />
        <path d="M137 111h46M160 92v39" className="vehicle-preview-path" />
      </svg>
      <div><span>{draft.propulsion.motorCount} motors</span><strong>{ratio.toFixed(2)}×</strong></div>
    </div>
  );
}

export function VehicleStudio() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const { account } = useAuth();
  const ownerId = account?.id ?? "local";
  const [models, setModels] = useState<StoredVehicleModel[]>(() => loadVehicleModels(ownerId));
  const [draft, setDraft] = useState<VehicleModelDraft>(() => createVehicleModelDraft());
  const [tab, setTab] = useState<StudioTab>("identity");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);
  const issues = useMemo(() => validateVehicleModel(draft), [draft]);
  const currentRecord = models.find((model) => model.draftId === draft.draftId);

  useEffect(() => {
    const ownerModels = loadVehicleModels(ownerId);
    setModels(ownerModels);
    setDraft(ownerModels[0]?.revisions[0]
      ? structuredClone(ownerModels[0].revisions[0])
      : createVehicleModelDraft());
    setMessage(null);
  }, [ownerId]);

  const update = (mutator: (next: VehicleModelDraft) => void) => {
    setDraft((current) => {
      const next = structuredClone(current);
      mutator(next);
      next.updatedAt = new Date().toISOString();
      return next;
    });
    setMessage(null);
  };
  const save = () => {
    try {
      const saved = currentRecord ? nextVehicleRevision(draft) : structuredClone(draft);
      setModels(saveVehicleModel(ownerId, saved));
      setDraft(saved);
      setMessage(`${copy.revision} ${saved.revision}`);
    } catch {
      setMessage(copy.saveFailed);
    }
  };
  const selectModel = (model: StoredVehicleModel) => {
    setDraft(structuredClone(model.revisions[0]));
    setMessage(null);
  };
  const importPack = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > MAX_VEHICLE_PACK_DRAFT_BYTES) throw new Error(copy.fileTooLarge);
      const envelope = await verifyVehiclePackDraft(JSON.parse(await file.text()));
      const imported = {
        ...structuredClone(envelope.payload.model),
        draftId: crypto.randomUUID(),
        revision: 1,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      setDraft(imported);
      setModels(saveVehicleModel(ownerId, imported));
      setMessage(copy.imported);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : copy.importFailed);
    } finally {
      setBusy(false);
    }
  };
  const exportPack = async () => {
    setBusy(true);
    try {
      downloadEnvelope(await buildVehiclePackDraft(draft));
      setMessage(copy.exportReady);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : copy.exportFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="vehicle-studio-page" data-brand-edition="universal">
      <header className="vehicle-studio-hero">
        <div><span>{copy.eyebrow}</span><h1>{copy.title}</h1><p>{copy.subtitle}</p></div>
        <div className="vehicle-studio-safety"><ShieldCheck /><p>{copy.safety}</p></div>
      </header>
      <div className="vehicle-studio-layout">
        <aside className="vehicle-studio-library" aria-label={copy.savedModels}>
          <button type="button" className="btn btn-primary" onClick={() => {
            setDraft(createVehicleModelDraft());
            setTab("identity");
            setMessage(null);
          }}><Plus />{copy.newModel}</button>
          <h2>{copy.savedModels}</h2>
          {models.length === 0 ? <p>{copy.noModels}</p> : models.map((model) => (
            <button
              type="button"
              className={model.draftId === draft.draftId ? "is-active" : undefined}
              key={model.draftId}
              onClick={() => selectModel(model)}
            >
              <Box /><span><strong>{model.revisions[0].name}</strong><small>{copy.revision} {model.revisions[0].revision}</small></span><ChevronRight />
            </button>
          ))}
        </aside>
        <main className="vehicle-studio-editor">
          <div className="vehicle-studio-toolbar">
            <div role="tablist" aria-label={copy.title}>
              {TABS.map((item) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === item}
                  key={item}
                  onClick={() => setTab(item)}
                >{copy[item]}</button>
              ))}
            </div>
            <div>
              <button type="button" className="btn" onClick={save}><Save />{copy.saveRevision}</button>
              {currentRecord ? <button type="button" className="btn btn-danger" aria-label={copy.delete} onClick={() => {
                try {
                  setModels(removeVehicleModel(ownerId, draft.draftId));
                  setDraft(createVehicleModelDraft());
                } catch {
                  setMessage(copy.deleteFailed);
                }
              }}><Trash2 /></button> : null}
            </div>
          </div>
          <div className="vehicle-studio-content">
            <section className="vehicle-studio-form" role="tabpanel">
              {tab === "identity" ? <>
                <label>{copy.modelName}<input value={draft.name} onChange={(event) => update((next) => { next.name = event.target.value; })} /></label>
                <label>{copy.manufacturer}<input value={draft.manufacturer} onChange={(event) => update((next) => { next.manufacturer = event.target.value; })} /></label>
                <label>{copy.vehicleClass}<select value={draft.vehicleClass} onChange={(event) => update((next) => { next.vehicleClass = event.target.value as VehicleClass; })}><option value="multicopter-small">Small multicopter</option><option value="multicopter-medium">Medium multicopter</option><option value="multicopter-research">Research multicopter</option></select></label>
                <label className="vehicle-studio-wide">{copy.notes}<textarea value={draft.notes} onChange={(event) => update((next) => { next.notes = event.target.value; })} /></label>
              </> : null}
              {tab === "airframe" ? <>
                <label>{copy.bodyShape}<select value={draft.body.shape} onChange={(event) => update((next) => { next.body.shape = event.target.value as "box" | "cylinder"; })}><option value="box">Box</option><option value="cylinder">Cylinder</option></select></label>
                <label>{copy.mass}<input type="number" min="0.01" step="0.01" value={draft.body.massKg} onChange={(event) => update((next) => { next.body.massKg = numberValue(event); })} /></label>
                <label>{copy.length}<input type="number" min="0.01" step="0.01" value={draft.body.lengthM} onChange={(event) => update((next) => { next.body.lengthM = numberValue(event); })} /></label>
                <label>{copy.width}<input type="number" min="0.01" step="0.01" value={draft.body.widthM} onChange={(event) => update((next) => { next.body.widthM = numberValue(event); })} /></label>
                <label>{copy.height}<input type="number" min="0.01" step="0.01" value={draft.body.heightM} onChange={(event) => update((next) => { next.body.heightM = numberValue(event); })} /></label>
              </> : null}
              {tab === "propulsion" ? <>
                <label>{copy.motors}<select value={draft.propulsion.motorCount} onChange={(event) => update((next) => { next.propulsion.motorCount = Number(event.target.value) as 4 | 6 | 8; })}><option value="4">4</option><option value="6">6</option><option value="8">8</option></select></label>
                <label>{copy.armLength}<input type="number" min="0.05" step="0.01" value={draft.propulsion.armLengthM} onChange={(event) => update((next) => { next.propulsion.armLengthM = numberValue(event); })} /></label>
                <label>{copy.propeller}<input type="number" min="0.05" step="0.001" value={draft.propulsion.propellerDiameterM} onChange={(event) => update((next) => { next.propulsion.propellerDiameterM = numberValue(event); })} /></label>
                <label>{copy.thrust}<input type="number" min="0.1" step="0.1" value={draft.propulsion.maximumThrustPerMotorN} onChange={(event) => update((next) => { next.propulsion.maximumThrustPerMotorN = numberValue(event); })} /></label>
                <label>{copy.batteryCells}<input type="number" min="1" max="16" step="1" value={draft.propulsion.batteryCells} onChange={(event) => update((next) => { next.propulsion.batteryCells = numberValue(event); })} /></label>
                <label>{copy.batteryCapacity}<input type="number" min="100" step="100" value={draft.propulsion.batteryCapacityMah} onChange={(event) => update((next) => { next.propulsion.batteryCapacityMah = numberValue(event); })} /></label>
              </> : null}
              {tab === "avionics" ? <>
                <label>{copy.autopilot}<select value={draft.autopilot.family} onChange={(event) => update((next) => { next.autopilot.family = event.target.value as AutopilotFamily; })}><option value="px4">PX4</option><option value="ardupilot">ArduPilot</option><option value="crazyflie">Crazyflie</option></select></label>
                <label>{copy.controller}<input value={draft.autopilot.controllerModel} onChange={(event) => update((next) => { next.autopilot.controllerModel = event.target.value; })} /></label>
                <label>{copy.firmware}<input value={draft.autopilot.firmwareVersion} onChange={(event) => update((next) => { next.autopilot.firmwareVersion = event.target.value; })} /></label>
                <label>{copy.controlTarget}<select value={draft.controlTarget.primary} onChange={(event) => update((next) => { next.controlTarget.primary = event.target.value as "position" | "velocity" | "attitude"; })}><option value="position">Position</option><option value="velocity">Velocity</option><option value="attitude">Attitude</option></select></label>
                <fieldset className="vehicle-studio-wide"><legend>{copy.sensors}</legend>{SENSOR_TYPES.map((sensorType) => {
                  const sensor = draft.sensors.find((item) => item.type === sensorType);
                  return <label className="vehicle-studio-check" key={sensorType}><input type="checkbox" checked={Boolean(sensor?.enabled)} onChange={(event) => update((next) => {
                    const existing = next.sensors.find((item) => item.type === sensorType);
                    if (existing) existing.enabled = event.target.checked;
                    else next.sensors.push({ id: crypto.randomUUID(), type: sensorType, model: `Generic ${sensorType}`, enabled: true });
                  })} />{sensorType.toUpperCase()}</label>;
                })}</fieldset>
              </> : null}
              {tab === "share" ? <>
                <fieldset className="vehicle-studio-wide"><legend>{copy.targets}</legend>{TARGET_EDITIONS.map((edition) => <label className="vehicle-studio-check" key={edition}><input type="checkbox" checked={draft.targetEditions.includes(edition)} onChange={(event) => update((next) => {
                  next.targetEditions = event.target.checked
                    ? [...new Set([...next.targetEditions, edition])]
                    : next.targetEditions.filter((item) => item !== edition);
                })} />DroneDream · {edition.toUpperCase()}</label>)}</fieldset>
                <div className="vehicle-studio-share-actions vehicle-studio-wide">
                  <button type="button" className="btn btn-primary" disabled={busy || issues.length > 0} onClick={exportPack}><Download />{copy.export}</button>
                  <button type="button" className="btn" disabled={busy} onClick={() => importRef.current?.click()}><Upload />{copy.import}</button>
                  <input ref={importRef} className="sr-only" type="file" accept=".json,.ddvp.json,application/json" onChange={importPack} />
                </div>
                <p className="vehicle-studio-boundary vehicle-studio-wide"><PackageCheck />{copy.packBoundary}</p>
              </> : null}
            </section>
            <aside className="vehicle-studio-inspector">
              <h2>{copy.preview}</h2><ModelPreview draft={draft} />
              {issues.length > 0 ? <div className="vehicle-studio-issues" role="alert"><strong>{copy.issues}</strong><ul>{issues.map((issue) => <li key={`${issue.field}:${issue.code}`}><code>{issue.field}</code> {issue.message}</li>)}</ul></div> : <p className="vehicle-studio-ready"><ShieldCheck />{copy.ready}</p>}
              {message ? <p className="vehicle-studio-message" role="status">{message}</p> : null}
              {currentRecord && currentRecord.revisions.length > 1 ? <div className="vehicle-studio-history"><h3><History />{copy.history}</h3>{currentRecord.revisions.map((revision) => <button type="button" key={revision.revision} onClick={() => {
                const restored = restoreVehicleRevision(revision, currentRecord.revisions[0].revision);
                setDraft(restored);
                setModels(saveVehicleModel(ownerId, restored));
              }}><span>{copy.revision} {revision.revision}</span><small>{new Date(revision.updatedAt).toLocaleString(locale)}</small><RotateCcw aria-label={copy.restore} /></button>)}</div> : null}
            </aside>
          </div>
        </main>
      </div>
    </div>
  );
}
