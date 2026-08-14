import {
  BatteryCharging,
  Cable,
  Box,
  ChevronRight,
  CircleDot,
  Copy,
  Cpu,
  Download,
  Eye,
  EyeOff,
  Grid3X3,
  Gauge,
  GitBranch,
  History,
  Layers3,
  Lock,
  Move3d,
  PackageCheck,
  Plus,
  Redo2,
  Rotate3d,
  Save,
  Scale3d,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  Undo2,
  Unlock,
  Upload,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";

import { VehicleModelPreview3D } from "../components/VehicleModelPreview3D";
import { useAuth } from "../features/auth/AuthContext";
import { activeAssistantTenantContext } from "../features/experiment/workspaceRegistry";
import {
  buildVehiclePackDraft,
  verifyVehiclePackDraft,
  type VehiclePackDraftEnvelope,
} from "../features/vehicleStudio/pack";
import {
  addVehicleConstraint,
  addVehicleComponent,
  calculateVehicleDiagnostics,
  createVehicleModelFromBrief,
  createVehicleModelDraft,
  duplicateVehicleComponent,
  mirrorVehicleComponent,
  radialArrayVehicleComponent,
  removeVehicleConstraint,
  removeVehicleComponent,
  setVehicleComponentParent,
  updateVehicleComponent,
  validateVehicleModel,
  type VehicleComponentDraft,
  type VehicleComponentKind,
  type VehicleDesignMission,
  type VehicleModelDraft,
  type VehiclePrimitive,
} from "../features/vehicleStudio/model";
import {
  cacheVehicleModels,
  loadVehicleModels,
  nextVehicleRevision,
  removeVehicleModel,
  restoreVehicleRevision,
  saveVehicleModel,
  type StoredVehicleModel,
} from "../features/vehicleStudio/storage";
import {
  deleteCloudVehicleModel,
  loadCloudVehicleModels,
  mergeVehicleModelStores,
  saveCloudVehicleModel,
  vehicleModelBoundaryFor,
} from "../features/vehicleStudio/cloudStorage";
import { useI18n } from "../i18n/I18nProvider";

type InspectorTab = "assembly" | "properties" | "analysis" | "delivery";
type Manipulator = "select" | "move" | "rotate" | "scale";
type ViewPreset = "isometric" | "top" | "front" | "side";
type Axis = "x" | "y" | "z";
const MAX_VEHICLE_PACK_DRAFT_BYTES = 2_500_000;

interface AssemblyRow {
  component: VehicleComponentDraft;
  depth: number;
}

function buildAssemblyRows(components: VehicleComponentDraft[]): AssemblyRow[] {
  const result: AssemblyRow[] = [];
  const visited = new Set<string>();
  const append = (parentId: string | null, depth: number) => {
    for (const component of components.filter((candidate) => candidate.parentId === parentId)) {
      if (visited.has(component.id)) continue;
      visited.add(component.id);
      result.push({ component, depth });
      append(component.id, depth + 1);
    }
  };
  append(null, 0);
  for (const component of components) {
    if (!visited.has(component.id)) result.push({ component, depth: 0 });
  }
  return result;
}

const COMPONENT_GROUPS: Array<{ title: string; entries: Array<{ kind: VehicleComponentKind; label: string; icon: ReactNode }> }> = [
  { title: "Structure", entries: [
    { kind: "fuselage", label: "Fuselage", icon: <Box /> },
    { kind: "frame", label: "Frame", icon: <Grid3X3 /> },
    { kind: "arm", label: "Arm", icon: <Wrench /> },
    { kind: "landing-gear", label: "Landing gear", icon: <Move3d /> },
  ] },
  { title: "Propulsion", entries: [
    { kind: "motor", label: "Motor", icon: <CircleDot /> },
    { kind: "propeller", label: "Propeller", icon: <Rotate3d /> },
    { kind: "battery", label: "Battery", icon: <BatteryCharging /> },
  ] },
  { title: "Avionics & payload", entries: [
    { kind: "flight-controller", label: "Flight controller", icon: <Cpu /> },
    { kind: "sensor", label: "Sensor", icon: <Sparkles /> },
    { kind: "camera-gimbal", label: "Camera / gimbal", icon: <CircleDot /> },
    { kind: "payload", label: "Payload", icon: <Box /> },
    { kind: "custom", label: "Custom solid", icon: <Plus /> },
  ] },
];

const EN = {
  eyebrow: "UNIVERSAL / PARAMETRIC VEHICLE DESIGN",
  title: "Vehicle Studio",
  subtitle: "Build the airframe as an assembly, tune every part, then verify mass, balance, clearance, and propulsion margins.",
  library: "Design library",
  newModel: "New aircraft",
  parts: "Component library",
  assembly: "Assembly",
  scene: "Assembly tree",
  properties: "Properties",
  analysis: "Engineering checks",
  delivery: "Revision & delivery",
  save: "Save revision",
  ai: "Design with AI",
  empty: "No saved aircraft yet.",
  noSelection: "Select a component in the tree or viewport to edit its geometry and engineering properties.",
  ready: "The current engineering contract is internally consistent.",
  issues: "Engineering issues",
  export: "Export verified draft",
  import: "Import draft",
};

const ZH: typeof EN = {
  eyebrow: "UNIVERSAL 专属 / 参数化无人机设计",
  title: "无人机建模工作台",
  subtitle: "以装配体方式搭建机体，精调每个部件，并校核质量、重心、间隙和动力裕度。",
  library: "设计库",
  newModel: "新建无人机",
  parts: "组件库",
  assembly: "装配",
  scene: "装配树",
  properties: "属性",
  analysis: "工程校核",
  delivery: "版本与交付",
  save: "保存新版本",
  ai: "AI 协同设计",
  empty: "还没有保存的无人机。",
  noSelection: "请在装配树或三维视口中选择组件，精调其几何、位置、材料和质量。",
  ready: "当前工程合同内部一致。",
  issues: "工程问题",
  export: "导出已校核草稿",
  import: "导入草稿",
};

const KIND_NAMES: Record<VehicleComponentKind, string> = {
  fuselage: "Fuselage", frame: "Frame", arm: "Arm", motor: "Motor", propeller: "Propeller",
  "landing-gear": "Landing gear", battery: "Battery", "flight-controller": "Flight controller",
  sensor: "Sensor", payload: "Payload", "camera-gimbal": "Camera / gimbal", custom: "Custom solid",
};

function numberValue(event: ChangeEvent<HTMLInputElement>): number {
  return Number(event.target.value);
}

function downloadEnvelope(envelope: VehiclePackDraftEnvelope) {
  const blob = new Blob([`${JSON.stringify(envelope, null, 2)}\n`], { type: "application/vnd.dronedream.vehicle-pack-draft+json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${envelope.payload.packId}-${envelope.payload.packVersion}.ddvp.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function cloneDraft(draft: VehicleModelDraft): VehicleModelDraft {
  return structuredClone(draft);
}

function NumericField({ label, value, onChange, step = .01 }: { label: string; value: number; onChange: (value: number) => void; step?: number }) {
  return <label className="vehicle-property-field"><span>{label}</span><input aria-label={label} type="number" step={step} value={value} onChange={(event) => onChange(numberValue(event))} /></label>;
}

function VectorFields({ label, value, onChange, step = .01 }: { label: string; value: Record<Axis, number>; onChange: (axis: Axis, value: number) => void; step?: number }) {
  return <fieldset className="vehicle-vector-fields"><legend>{label}</legend>{(["x", "y", "z"] as Axis[]).map((axis) => <NumericField key={axis} label={axis.toUpperCase()} value={value[axis]} step={step} onChange={(next) => onChange(axis, next)} />)}</fieldset>;
}

export function VehicleStudio() {
  const requestedDraftId = new URLSearchParams(window.location.search).get("draft");
  const { locale } = useI18n();
  const copy = locale === "zh-CN" ? ZH : EN;
  const { account } = useAuth();
  const ownerId = account?.id ?? "local";
  const tenantContext = activeAssistantTenantContext(ownerId);
  const cloudBoundary = useMemo(
    () => vehicleModelBoundaryFor(ownerId, tenantContext.tenantId, tenantContext.organizationId),
    [ownerId, tenantContext.organizationId, tenantContext.tenantId],
  );
  const [models, setModels] = useState<StoredVehicleModel[]>(() => loadVehicleModels(ownerId));
  const [draft, setDraft] = useState<VehicleModelDraft>(() => createVehicleModelDraft());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("assembly");
  const [manipulator, setManipulator] = useState<Manipulator>("select");
  const [wireframe, setWireframe] = useState(false);
  const [exploded, setExploded] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [viewPreset, setViewPreset] = useState<ViewPreset>("isometric");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiDesignerOpen, setAiDesignerOpen] = useState(false);
  const [aiDecisions, setAiDecisions] = useState<string[]>([]);
  const [designBrief, setDesignBrief] = useState({
    name: "Survey engineering multirotor",
    mission: "survey" as VehicleDesignMission,
    motorCount: "auto" as "auto" | "4" | "6" | "8",
    payloadKg: .35,
    targetFlightMinutes: 24,
    operatingEnvironment: "outdoor" as "indoor" | "outdoor" | "windy",
    camera: true,
    lidar: false,
  });
  const undoRef = useRef<VehicleModelDraft[]>([]);
  const redoRef = useRef<VehicleModelDraft[]>([]);
  const importRef = useRef<HTMLInputElement>(null);

  const issues = useMemo(() => validateVehicleModel(draft), [draft]);
  const diagnostics = useMemo(() => calculateVehicleDiagnostics(draft), [draft]);
  const selected = draft.components.find((component) => component.id === selectedId) ?? null;
  const currentRecord = models.find((model) => model.draftId === draft.draftId);
  const assemblyRows = useMemo(() => buildAssemblyRows(draft.components), [draft.components]);

  useEffect(() => {
    let cancelled = false;
    const ownerModels = loadVehicleModels(ownerId);
    const requestedModel = requestedDraftId ? ownerModels.find((model) => model.draftId === requestedDraftId) : null;
    const next = requestedModel?.revisions[0] ?? ownerModels[0]?.revisions[0] ?? createVehicleModelDraft();
    setModels(ownerModels);
    setDraft(cloneDraft(next));
    setSelectedId(next.components[0]?.id ?? null);
    undoRef.current = [];
    redoRef.current = [];
    if (cloudBoundary) {
      void loadCloudVehicleModels(cloudBoundary).then((cloudModels) => {
        if (cancelled || !cloudModels) return;
        const merged = cacheVehicleModels(ownerId, mergeVehicleModelStores(ownerModels, cloudModels));
        const requestedCloudModel = requestedDraftId
          ? merged.find((model) => model.draftId === requestedDraftId)
          : null;
        const restored = requestedCloudModel?.revisions[0] ?? merged[0]?.revisions[0] ?? next;
        setModels(merged);
        setDraft(cloneDraft(restored));
        setSelectedId(restored.components[0]?.id ?? null);
      }).catch(() => {
        if (!cancelled) setMessage("Cloud revisions are unavailable. Local editing remains active.");
      });
    }
    return () => { cancelled = true; };
  }, [cloudBoundary, ownerId, requestedDraftId]);

  const commit = (next: VehicleModelDraft) => {
    undoRef.current = [...undoRef.current.slice(-49), cloneDraft(draft)];
    redoRef.current = [];
    next.updatedAt = new Date().toISOString();
    setDraft(next);
    setMessage(null);
  };
  const undo = () => {
    const previous = undoRef.current.pop();
    if (!previous) return;
    redoRef.current.push(cloneDraft(draft));
    setDraft(previous);
    if (selectedId && !previous.components.some((part) => part.id === selectedId)) setSelectedId(previous.components[0]?.id ?? null);
  };
  const redo = () => {
    const next = redoRef.current.pop();
    if (!next) return;
    undoRef.current.push(cloneDraft(draft));
    setDraft(next);
  };
  const updateSelected = (mutator: (component: VehicleComponentDraft) => void) => {
    if (!selectedId) return;
    commit(updateVehicleComponent(draft, selectedId, mutator));
  };
  const addPart = (kind: VehicleComponentKind) => {
    const next = addVehicleComponent(draft, kind);
    commit(next);
    setSelectedId(next.components.at(-1)?.id ?? null);
    setInspectorTab("properties");
  };
  const duplicateSelected = () => {
    if (!selected) return;
    const next = duplicateVehicleComponent(draft, selected.id);
    commit(next);
    setSelectedId(next.components.at(-1)?.id ?? null);
  };
  const mirrorSelected = () => {
    if (!selected) return;
    const next = mirrorVehicleComponent(draft, selected.id, "x");
    commit(next);
    setSelectedId(next.components.at(-1)?.id ?? null);
  };
  const arraySelected = () => {
    if (!selected) return;
    commit(radialArrayVehicleComponent(draft, selected.id, 4));
  };
  const persistRevision = async (revision: VehicleModelDraft) => {
    const localModels = saveVehicleModel(ownerId, revision);
    setModels(localModels);
    setDraft(revision);
    if (!cloudBoundary) return true;
    try {
      return await saveCloudVehicleModel(cloudBoundary, revision);
    } catch {
      return false;
    }
  };
  const save = async () => {
    try {
      const saved = currentRecord ? nextVehicleRevision(draft) : cloneDraft(draft);
      const cloudSaved = await persistRevision(saved);
      setMessage(cloudBoundary && !cloudSaved
        ? `Saved locally as r${saved.revision}; cloud sync is pending.`
        : `${copy.save} · r${saved.revision}`);
    } catch { setMessage("The revision could not be saved."); }
  };
  const importPack = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > MAX_VEHICLE_PACK_DRAFT_BYTES) throw new Error("The draft exceeds 2.5 MB.");
      const envelope = await verifyVehiclePackDraft(JSON.parse(await file.text()));
      const imported = { ...cloneDraft(envelope.payload.model), draftId: crypto.randomUUID(), revision: 1, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
      const cloudSaved = await persistRevision(imported);
      setSelectedId(imported.components[0]?.id ?? null);
      setMessage(cloudBoundary && !cloudSaved
        ? "Imported locally; cloud sync is pending."
        : "Imported as a new aircraft draft.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Import failed."); }
    finally { setBusy(false); }
  };
  const exportPack = async () => {
    setBusy(true);
    try { downloadEnvelope(await buildVehiclePackDraft(draft)); setMessage("Verified draft exported."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Export failed."); }
    finally { setBusy(false); }
  };

  const generateAssistedDesign = () => {
    const result = createVehicleModelFromBrief({
      name: designBrief.name,
      mission: designBrief.mission,
      motorCount: designBrief.motorCount === "auto" ? undefined : Number(designBrief.motorCount) as 4 | 6 | 8,
      payloadKg: designBrief.payloadKg,
      targetFlightMinutes: designBrief.targetFlightMinutes,
      operatingEnvironment: designBrief.operatingEnvironment,
      camera: designBrief.camera,
      lidar: designBrief.lidar,
    });
    commit(result.draft);
    setSelectedId(result.draft.components.find((component) => component.kind === "frame")?.id ?? result.draft.components[0]?.id ?? null);
    setAiDecisions(result.decisions);
    setInspectorTab("analysis");
    setAiDesignerOpen(false);
    setMessage(locale === "zh-CN" ? "已生成可继续手工精修的参数化装配草稿。" : "Generated an editable parametric assembly draft.");
  };

  return <div className="vehicle-studio-page vehicle-studio-v2" data-brand-edition="universal">
    <header className="vehicle-studio-v2-header">
      <div><span>{copy.eyebrow}</span><h1>{copy.title}</h1><p>{copy.subtitle}</p></div>
      <div className="vehicle-studio-v2-header-actions">
        <button type="button" className="btn" onClick={() => setAiDesignerOpen(true)}><Sparkles />{copy.ai}</button>
            <button type="button" className="btn btn-primary" onClick={() => { void save(); }}><Save />{copy.save}</button>
      </div>
    </header>

    <main className="vehicle-workbench">
      <aside className="vehicle-workbench-left">
        <section className="vehicle-library-panel">
          <div className="vehicle-panel-heading"><strong>{copy.library}</strong><button type="button" aria-label={copy.newModel} onClick={() => {
            const next = createVehicleModelDraft(); setDraft(next); setSelectedId(next.components[0]?.id ?? null); undoRef.current = []; redoRef.current = [];
          }}><Plus /></button></div>
          <div className="vehicle-saved-list">{models.length ? models.map((model) => <button type="button" className={draft.draftId === model.draftId ? "is-active" : ""} key={model.draftId} onClick={() => {
            const next = cloneDraft(model.revisions[0]); setDraft(next); setSelectedId(next.components[0]?.id ?? null); undoRef.current = []; redoRef.current = [];
          }}><Box /><span><strong>{model.revisions[0].name}</strong><small>r{model.revisions[0].revision} · {model.revisions[0].components.length} parts</small></span><ChevronRight /></button>) : <p>{copy.empty}</p>}</div>
        </section>
        <section className="vehicle-component-palette">
          <div className="vehicle-panel-heading"><strong>{copy.parts}</strong></div>
          {COMPONENT_GROUPS.map((group) => <div className="vehicle-component-group" key={group.title}><span>{group.title}</span><div>{group.entries.map((entry) => <button type="button" key={entry.kind} onClick={() => addPart(entry.kind)}>{entry.icon}<small>{entry.label}</small></button>)}</div></div>)}
        </section>
      </aside>

      <section className="vehicle-workbench-center">
        <div className="vehicle-canvas-toolbar">
          <div>
            <button type="button" aria-label="Undo" disabled={!undoRef.current.length} onClick={undo}><Undo2 /></button>
            <button type="button" aria-label="Redo" disabled={!redoRef.current.length} onClick={redo}><Redo2 /></button>
            <span />
            {(["select", "move", "rotate", "scale"] as Manipulator[]).map((tool) => <button type="button" className={manipulator === tool ? "is-active" : ""} aria-label={tool} key={tool} onClick={() => setManipulator(tool)}>{tool === "select" ? <Box /> : tool === "move" ? <Move3d /> : tool === "rotate" ? <Rotate3d /> : <Scale3d />}</button>)}
            <span />
            <button type="button" aria-label="Duplicate selected component" disabled={!selected} onClick={duplicateSelected}><Copy /></button>
            <button type="button" aria-label="Mirror selected component on X" disabled={!selected} onClick={mirrorSelected}><Move3d /></button>
            <button type="button" aria-label="Create radial array from selected component" disabled={!selected} onClick={arraySelected}><Rotate3d /></button>
          </div>
          <div>
            {(["isometric", "top", "front", "side"] as ViewPreset[]).map((preset) => <button type="button" className={`vehicle-view-preset ${viewPreset === preset ? "is-active" : ""}`} aria-label={`${preset} view`} key={preset} onClick={() => setViewPreset(preset)}>{preset === "isometric" ? "ISO" : preset === "front" ? "F" : preset === "side" ? "R" : "T"}</button>)}
            <span />
            <button type="button" className={showGrid ? "is-active" : ""} aria-label="Toggle grid" onClick={() => setShowGrid((value) => !value)}><Grid3X3 /></button>
            <button type="button" className={wireframe ? "is-active" : ""} aria-label="Toggle wireframe" onClick={() => setWireframe((value) => !value)}><Wrench /></button>
            <button type="button" className={exploded ? "is-active" : ""} aria-label="Exploded view" onClick={() => setExploded((value) => !value)}><Move3d /></button>
          </div>
        </div>
        <div className="vehicle-viewport-stage">
          <VehicleModelPreview3D draft={draft} selectedComponentId={selectedId} onSelectComponent={setSelectedId} wireframe={wireframe} exploded={exploded} showGrid={showGrid} manipulator={manipulator} viewPreset={viewPreset} onTransformComponent={(componentId, transform) => commit(updateVehicleComponent(draft, componentId, (part) => { part.transform = transform; }))} copy={{
            ariaLabel: "Interactive component-level vehicle modeling viewport",
            unavailable: "3D unavailable · showing engineering plan view",
            interaction: "Select parts · Drag to orbit · Scroll to zoom",
            motors: "motors", ratio: "thrust / weight",
          }} />
          <div className="vehicle-viewport-badge"><span>{manipulator.toUpperCase()}</span><strong>{selected?.name ?? "Assembly"}</strong></div>
        </div>
        <div className="vehicle-diagnostics-strip">
          <span><small>Parts</small><strong>{diagnostics.componentCount}</strong></span>
          <span><small>Mass</small><strong>{diagnostics.totalMassKg.toFixed(2)} kg</strong></span>
          <span><small>Endurance</small><strong>{diagnostics.estimatedHoverMinutes.toFixed(1)} min</strong></span>
          <span><small>Balance</small><strong>{diagnostics.balanceScore.toFixed(0)} / 100</strong></span>
          <span><small>Rotor clearance</small><strong>{Math.round(diagnostics.minimumRotorClearanceM * 1_000)} mm</strong></span>
          <span className={diagnostics.thrustToWeight >= 1.6 ? "is-good" : "is-bad"}><small>Thrust / weight</small><strong>{diagnostics.thrustToWeight.toFixed(2)}×</strong></span>
        </div>
      </section>

      <aside className="vehicle-workbench-right">
        <div className="vehicle-inspector-tabs" role="tablist">
          {(["assembly", "properties", "analysis", "delivery"] as InspectorTab[]).map((tab) => <button type="button" role="tab" aria-selected={inspectorTab === tab} key={tab} onClick={() => setInspectorTab(tab)}>{copy[tab]}</button>)}
        </div>
        <div className="vehicle-inspector-body">
          {inspectorTab === "assembly" ? <div className="vehicle-assembly-panel">
            <div className="vehicle-inspector-section-title"><span><GitBranch />Hierarchical assembly</span><small>{draft.components.length} components</small></div>
            <div className="vehicle-assembly-tree">{assemblyRows.map(({ component, depth }) => <button type="button" className={component.id === selectedId ? "is-active" : ""} style={{ paddingLeft: `${10 + depth * 15}px` }} key={component.id} onClick={() => setSelectedId(component.id)}>{depth ? <Cable className="vehicle-assembly-branch" /> : <Layers3 className="vehicle-assembly-root" />}<span className={`vehicle-kind-dot kind-${component.kind}`} /><span><strong>{component.name}</strong><small>{KIND_NAMES[component.kind]} · {component.source}</small></span><i onClick={(event) => { event.stopPropagation(); commit(updateVehicleComponent(draft, component.id, (part) => { part.visible = !part.visible; })); }}>{component.visible ? <Eye /> : <EyeOff />}</i><i onClick={(event) => { event.stopPropagation(); commit(updateVehicleComponent(draft, component.id, (part) => { part.locked = !part.locked; })); }}>{component.locked ? <Lock /> : <Unlock />}</i></button>)}</div>
          </div> : null}

          {inspectorTab === "properties" ? selected ? <div className="vehicle-properties-panel">
            <label className="vehicle-property-field vehicle-property-wide"><span>Name</span><input value={selected.name} onChange={(event) => updateSelected((part) => { part.name = event.target.value; })} /></label>
            <label className="vehicle-property-field"><span>Primitive</span><select value={selected.geometry.primitive} onChange={(event) => updateSelected((part) => { part.geometry.primitive = event.target.value as VehiclePrimitive; })}>{["box", "rounded-box", "cylinder", "sphere", "capsule", "cone"].map((primitive) => <option key={primitive}>{primitive}</option>)}</select></label>
            <label className="vehicle-property-field"><span>Base color</span><input type="color" value={selected.material.baseColor} onChange={(event) => updateSelected((part) => { part.material.baseColor = event.target.value; })} /></label>
            <label className="vehicle-property-field vehicle-property-wide"><span>Assembly parent</span><select value={selected.parentId ?? ""} onChange={(event) => commit(setVehicleComponentParent(draft, selected.id, event.target.value || null))}><option value="">Assembly root</option>{draft.components.filter((component) => component.id !== selected.id).map((component) => <option key={component.id} value={component.id}>{component.name}</option>)}</select></label>
            <label className="vehicle-property-field vehicle-property-wide"><span>External mesh / CAD asset</span><input value={selected.geometry.meshUri} placeholder="glTF, GLB, OBJ, STEP-derived asset URI" onChange={(event) => updateSelected((part) => { part.geometry.meshUri = event.target.value; })} /></label>
            <VectorFields label="Position (m)" value={selected.transform.positionM} onChange={(axis, value) => updateSelected((part) => { part.transform.positionM[axis] = value; })} />
            <VectorFields label="Rotation (deg)" value={selected.transform.rotationDeg} step={1} onChange={(axis, value) => updateSelected((part) => { part.transform.rotationDeg[axis] = value; })} />
            <VectorFields label="Dimensions (m)" value={selected.geometry.sizeM} onChange={(axis, value) => updateSelected((part) => { part.geometry.sizeM[axis] = value; })} />
            <div className="vehicle-property-grid"><NumericField label="Radius (m)" value={selected.geometry.radiusM} onChange={(value) => updateSelected((part) => { part.geometry.radiusM = value; })} /><NumericField label="Length (m)" value={selected.geometry.lengthM} onChange={(value) => updateSelected((part) => { part.geometry.lengthM = value; })} /><NumericField label="Mass (kg)" value={selected.mass.massKg} onChange={(value) => updateSelected((part) => { part.mass.massKg = value; })} /><NumericField label="Density (kg/m³)" value={selected.mass.densityKgM3} step={10} onChange={(value) => updateSelected((part) => { part.mass.densityKgM3 = value; })} /><NumericField label="Metalness" value={selected.material.metalness} onChange={(value) => updateSelected((part) => { part.material.metalness = value; })} /><NumericField label="Roughness" value={selected.material.roughness} onChange={(value) => updateSelected((part) => { part.material.roughness = value; })} /><NumericField label="Opacity" value={selected.material.opacity} onChange={(value) => updateSelected((part) => { part.material.opacity = value; })} /></div>
            <label className="vehicle-property-field"><span>Mass calculation</span><select value={selected.mass.mode} onChange={(event) => updateSelected((part) => { part.mass.mode = event.target.value as "explicit" | "density"; })}><option value="explicit">Explicit component mass</option><option value="density">Material density × volume</option></select></label>
            <label className="vehicle-property-field"><span>Engineering tags</span><input value={selected.tags.join(", ")} onChange={(event) => updateSelected((part) => { part.tags = event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean); })} /></label>
            <div className="vehicle-component-operations">
              <button type="button" onClick={duplicateSelected}><Copy />Duplicate</button>
              <button type="button" onClick={mirrorSelected}><Move3d />Mirror X</button>
              <button type="button" onClick={arraySelected}><Rotate3d />Array ×4</button>
              <button type="button" className="is-danger" onClick={() => { commit(removeVehicleComponent(draft, selected.id)); setSelectedId(null); }}><Trash2 />Delete</button>
            </div>
          </div> : <p className="vehicle-inspector-empty">{copy.noSelection}</p> : null}

          {inspectorTab === "analysis" ? <div className="vehicle-analysis-panel">
            <div className="vehicle-analysis-metrics"><span><Scale3d /><small>Total mass</small><strong>{diagnostics.totalMassKg.toFixed(3)} kg</strong></span><span><Move3d /><small>Span</small><strong>{diagnostics.spanM.toFixed(3)} m</strong></span><span><Zap /><small>Thrust margin</small><strong>{diagnostics.thrustToWeight.toFixed(2)}×</strong></span><span><Gauge /><small>Hover estimate</small><strong>{diagnostics.estimatedHoverMinutes.toFixed(1)} min</strong></span><span><Target /><small>Balance score</small><strong>{diagnostics.balanceScore.toFixed(0)} / 100</strong></span><span><Rotate3d /><small>Rotor clearance</small><strong>{Math.round(diagnostics.minimumRotorClearanceM * 1_000)} mm</strong></span><span><BatteryCharging /><small>Battery energy</small><strong>{diagnostics.batteryEnergyWh.toFixed(0)} Wh</strong></span><span><Grid3X3 /><small>Disk area</small><strong>{diagnostics.rotorDiskAreaM2.toFixed(2)} m²</strong></span></div>
            <div className="vehicle-com-diagram"><i style={{ left: `${50 + diagnostics.centerOfMassM.x * 100}%`, top: `${50 + diagnostics.centerOfMassM.z * 100}%` }} /><span>Projected center of mass</span></div>
            {aiDecisions.length ? <div className="vehicle-ai-decisions"><div className="vehicle-inspector-section-title"><span><Sparkles />Design rationale</span><small>AI draft · editable</small></div>{aiDecisions.map((decision, index) => <p key={`${index}:${decision}`}><span>{String(index + 1).padStart(2, "0")}</span>{decision}</p>)}</div> : null}
            <div className="vehicle-constraint-panel"><div className="vehicle-inspector-section-title"><span><Cable />Assembly constraints</span><button type="button" onClick={() => commit(addVehicleConstraint(draft, { type: "balance", componentIds: draft.components.map((component) => component.id), axis: "y", value: .015, enabled: true }))}><Plus />Balance</button></div>{draft.constraints.map((constraint) => <div className="vehicle-constraint-row" key={constraint.id}><button type="button" aria-label="Toggle constraint" className={constraint.enabled ? "is-enabled" : ""} onClick={() => commit({ ...cloneDraft(draft), constraints: draft.constraints.map((candidate) => candidate.id === constraint.id ? { ...candidate, enabled: !candidate.enabled } : candidate) })}><CircleDot /></button><span><strong>{constraint.type.replaceAll("-", " ")}</strong><small>{constraint.componentIds.length} components · {constraint.axis.toUpperCase()} · {constraint.value}</small></span><button type="button" aria-label="Remove constraint" onClick={() => commit(removeVehicleConstraint(draft, constraint.id))}><X /></button></div>)}</div>
            {diagnostics.engineeringWarnings.length ? <div className="vehicle-engineering-warnings">{diagnostics.engineeringWarnings.map((warning) => <p key={warning}><ShieldCheck />{warning}</p>)}</div> : null}
            {issues.length ? <div className="vehicle-studio-issues"><strong>{copy.issues} · {issues.length}</strong><ul>{issues.map((issue) => <li key={`${issue.field}:${issue.code}`}><code>{issue.field}</code>{issue.message}</li>)}</ul></div> : <p className="vehicle-studio-ready"><ShieldCheck />{copy.ready}</p>}
          </div> : null}

          {inspectorTab === "delivery" ? <div className="vehicle-delivery-panel">
            <div className="vehicle-delivery-contract"><PackageCheck /><strong>Vehicle Pack v2</strong><span>Components, transforms, materials, masses, constraints, avionics, and generated simulation assets.</span></div>
            <label className="vehicle-property-field"><span>Aircraft name</span><input value={draft.name} onChange={(event) => commit({ ...cloneDraft(draft), name: event.target.value })} /></label>
            <label className="vehicle-property-field"><span>Manufacturer</span><input value={draft.manufacturer} onChange={(event) => commit({ ...cloneDraft(draft), manufacturer: event.target.value })} /></label>
            <button type="button" className="btn btn-primary" disabled={busy || issues.length > 0} onClick={exportPack}><Download />{copy.export}</button>
            <button type="button" className="btn" disabled={busy} onClick={() => importRef.current?.click()}><Upload />{copy.import}</button>
            <input ref={importRef} className="sr-only" type="file" accept=".json,.ddvp.json,application/json" onChange={importPack} />
            {currentRecord?.revisions.length ? <div className="vehicle-revision-list"><h3><History />Revision history</h3>{currentRecord.revisions.map((revision) => <button type="button" key={revision.revision} onClick={() => {
              const restored = restoreVehicleRevision(revision, currentRecord.revisions[0].revision);
              void persistRevision(restored).then((cloudSaved) => setMessage(cloudBoundary && !cloudSaved
                ? `Restored locally as r${restored.revision}; cloud sync is pending.`
                : `Restored as r${restored.revision}.`));
            }}><strong>r{revision.revision}</strong><span>{new Date(revision.updatedAt).toLocaleString(locale)}</span></button>)}</div> : null}
            {currentRecord ? <button type="button" className="btn btn-danger" onClick={() => {
              const draftId = draft.draftId;
              setModels(removeVehicleModel(ownerId, draftId));
              if (cloudBoundary) void deleteCloudVehicleModel(cloudBoundary, draftId);
              const next = createVehicleModelDraft();
              setDraft(next);
              setSelectedId(next.components[0]?.id ?? null);
            }}><Trash2 />Delete aircraft</button> : null}
          </div> : null}
        </div>
        {message ? <p className="vehicle-studio-message" role="status">{message}</p> : null}
      </aside>
    </main>
    {aiDesignerOpen ? <div className="vehicle-ai-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setAiDesignerOpen(false); }}>
      <form className="vehicle-ai-designer" aria-label="AI aircraft designer" onSubmit={(event) => { event.preventDefault(); generateAssistedDesign(); }}>
        <header><div><span><Sparkles />AI engineering brief</span><h2>Generate an editable aircraft assembly</h2><p>Translate mission intent into a parameterized starting point, then refine every component manually.</p></div><button type="button" aria-label="Close designer" onClick={() => setAiDesignerOpen(false)}><X /></button></header>
        <div className="vehicle-ai-brief-grid">
          <label className="vehicle-property-field vehicle-property-wide"><span>Aircraft name</span><input aria-label="Aircraft name" value={designBrief.name} onChange={(event) => setDesignBrief((current) => ({ ...current, name: event.target.value }))} /></label>
          <label className="vehicle-property-field"><span>Mission</span><select aria-label="Mission" value={designBrief.mission} onChange={(event) => setDesignBrief((current) => ({ ...current, mission: event.target.value as VehicleDesignMission }))}><option value="survey">Mapping & survey</option><option value="inspection">Close inspection</option><option value="endurance">Long endurance</option><option value="payload">Payload lift</option><option value="agility">Agile flight</option></select></label>
          <label className="vehicle-property-field"><span>Rotor architecture</span><select aria-label="Rotor architecture" value={designBrief.motorCount} onChange={(event) => setDesignBrief((current) => ({ ...current, motorCount: event.target.value as typeof current.motorCount }))}><option value="auto">Choose from mission</option><option value="4">Quadrotor</option><option value="6">Hexarotor</option><option value="8">Octorotor</option></select></label>
          <NumericField label="Mission payload (kg)" value={designBrief.payloadKg} step={.05} onChange={(payloadKg) => setDesignBrief((current) => ({ ...current, payloadKg }))} />
          <NumericField label="Target flight time (min)" value={designBrief.targetFlightMinutes} step={1} onChange={(targetFlightMinutes) => setDesignBrief((current) => ({ ...current, targetFlightMinutes }))} />
          <label className="vehicle-property-field"><span>Operating environment</span><select aria-label="Operating environment" value={designBrief.operatingEnvironment} onChange={(event) => setDesignBrief((current) => ({ ...current, operatingEnvironment: event.target.value as typeof current.operatingEnvironment }))}><option value="indoor">Indoor / protected</option><option value="outdoor">Outdoor / nominal</option><option value="windy">Wind-exposed</option></select></label>
          <fieldset className="vehicle-ai-capabilities"><legend>Mission equipment</legend><label><input aria-label="Stabilized camera" type="checkbox" checked={designBrief.camera} onChange={(event) => setDesignBrief((current) => ({ ...current, camera: event.target.checked }))} /><span><CircleDot /><strong>Stabilized camera</strong><small>Gimbal, lens and imaging payload</small></span></label><label><input aria-label="LiDAR scanner" type="checkbox" checked={designBrief.lidar} onChange={(event) => setDesignBrief((current) => ({ ...current, lidar: event.target.checked }))} /><span><Target /><strong>LiDAR scanner</strong><small>Range sensor and isolated mount</small></span></label></fieldset>
        </div>
        <footer><span><ShieldCheck />Produces a non-executable engineering draft for review.</span><div><button type="button" className="btn" onClick={() => setAiDesignerOpen(false)}>Cancel</button><button type="submit" className="btn btn-primary"><Sparkles />Build draft</button></div></footer>
      </form>
    </div> : null}
  </div>;
}
