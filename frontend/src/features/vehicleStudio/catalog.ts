import {
  calculateVehicleDiagnostics,
  createVehicleComponent,
  getVehicleComponentMassProperties,
  rebuildVehicleRotorArchitecture,
  type VehicleComponentDraft,
  type VehicleComponentKind,
  type VehicleModelDraft,
  type VehicleSensorDraft,
  type VehicleVector3,
} from "./model";

export type VehicleCatalogGroup = "airframe" | "propulsion" | "energy" | "avionics" | "mission";

export interface VehicleCatalogEntry {
  id: string;
  group: VehicleCatalogGroup;
  kind: VehicleComponentKind;
  name: string;
  summary: string;
  metrics: string[];
  tags: string[];
  applyMode: "architecture" | "fleet" | "replace-or-add" | "add";
  architecture?: { motorCount: 4 | 6 | 8; armLengthM: number; propellerDiameterM: number };
  propulsion?: Partial<VehicleModelDraft["propulsion"]>;
  sensor?: Pick<VehicleSensorDraft, "type" | "model">;
  component: {
    geometry?: Partial<VehicleComponentDraft["geometry"]> & { sizeM?: VehicleVector3 };
    transform?: Partial<VehicleComponentDraft["transform"]> & { positionM?: VehicleVector3; rotationDeg?: VehicleVector3; scale?: VehicleVector3 };
    material?: Partial<VehicleComponentDraft["material"]>;
    mass?: Partial<VehicleComponentDraft["mass"]>;
    tags?: string[];
  };
}

export interface VehicleMaterialPreset {
  id: string;
  name: string;
  densityKgM3: number;
  baseColor: string;
  metalness: number;
  roughness: number;
}

export const VEHICLE_MATERIAL_PRESETS: VehicleMaterialPreset[] = [
  { id: "carbon-laminate", name: "Carbon laminate", densityKgM3: 1_600, baseColor: "#24212c", metalness: .34, roughness: .31 },
  { id: "aluminum-6061", name: "6061 aluminum", densityKgM3: 2_700, baseColor: "#aeb7c4", metalness: .82, roughness: .24 },
  { id: "magnesium-alloy", name: "Magnesium alloy", densityKgM3: 1_800, baseColor: "#9aa3a5", metalness: .72, roughness: .3 },
  { id: "nylon-cf", name: "Carbon-filled nylon", densityKgM3: 1_240, baseColor: "#34323a", metalness: .08, roughness: .48 },
  { id: "abs", name: "ABS enclosure", densityKgM3: 1_050, baseColor: "#f0f2f5", metalness: .02, roughness: .38 },
  { id: "tpu", name: "TPU isolator", densityKgM3: 1_210, baseColor: "#35c5b4", metalness: 0, roughness: .72 },
];

export const VEHICLE_COMPONENT_CATALOG: VehicleCatalogEntry[] = [
  {
    id: "airframe-quad-450", group: "airframe", kind: "frame", name: "450 mm quad X architecture",
    summary: "Compact four-motor research frame with 10-inch rotor clearance.", metrics: ["4 motors", "0.30 m arm", "10 in prop"], tags: ["quad-x", "portable", "research"], applyMode: "architecture",
    architecture: { motorCount: 4, armLengthM: .3, propellerDiameterM: .254 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .23, y: .032, z: .17 } }, mass: { mode: "explicit", massKg: .19 }, material: { baseColor: "#25212e", metalness: .5, roughness: .28 }, tags: ["primary-structure", "carbon-laminate", "quad-x"] },
  },
  {
    id: "airframe-hexa-680", group: "airframe", kind: "frame", name: "680 mm survey hex architecture",
    summary: "Six-motor layout with useful redundancy and a wider payload envelope.", metrics: ["6 motors", "0.39 m arm", "13 in prop"], tags: ["hex", "survey", "redundant"], applyMode: "architecture",
    architecture: { motorCount: 6, armLengthM: .39, propellerDiameterM: .33 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .31, y: .038, z: .23 } }, mass: { mode: "explicit", massKg: .31 }, material: { baseColor: "#211f2b", metalness: .52, roughness: .27 }, tags: ["primary-structure", "carbon-laminate", "survey"] },
  },
  {
    id: "airframe-octo-900", group: "airframe", kind: "frame", name: "900 mm heavy-lift octo",
    summary: "Eight-motor architecture for payload lift and motor-out design studies.", metrics: ["8 motors", "0.52 m arm", "15 in prop"], tags: ["octo", "payload", "redundant"], applyMode: "architecture",
    architecture: { motorCount: 8, armLengthM: .52, propellerDiameterM: .381 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .38, y: .046, z: .29 } }, mass: { mode: "explicit", massKg: .52 }, material: { baseColor: "#1c1a25", metalness: .56, roughness: .25 }, tags: ["primary-structure", "carbon-laminate", "heavy-lift"] },
  },
  {
    id: "arm-carbon-25", group: "airframe", kind: "arm", name: "25 mm carbon arm set",
    summary: "Applies a rigid rectangularized tube profile to every arm in the layout.", metrics: ["25 mm class", "55 g each", "fleet apply"], tags: ["carbon", "structure", "arm"], applyMode: "fleet",
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .28, y: .026, z: .032 } }, mass: { mode: "explicit", massKg: .055 }, material: { baseColor: "#24212b", metalness: .46, roughness: .3 }, tags: ["arm", "carbon-laminate", "replaceable"] },
  },
  {
    id: "motor-2216", group: "propulsion", kind: "motor", name: "2216 efficiency motor set",
    summary: "Light motor preset for compact mapping and endurance platforms.", metrics: ["75 g", "12 N max", "4–6S"], tags: ["efficient", "mapping", "motor"], applyMode: "fleet", propulsion: { maximumThrustPerMotorN: 12 },
    component: { geometry: { primitive: "cylinder", sizeM: { x: .034, y: .032, z: .034 }, radiusM: .017, lengthM: .032 }, mass: { mode: "explicit", massKg: .075 }, material: { baseColor: "#2c3038", metalness: .78, roughness: .22 }, tags: ["brushless-motor", "2216-class", "efficiency"] },
  },
  {
    id: "motor-2814", group: "propulsion", kind: "motor", name: "2814 survey motor set",
    summary: "Balanced mid-size motor preset for 13-inch survey configurations.", metrics: ["132 g", "21 N max", "6S"], tags: ["survey", "motor", "mid-size"], applyMode: "fleet", propulsion: { maximumThrustPerMotorN: 21 },
    component: { geometry: { primitive: "cylinder", sizeM: { x: .042, y: .038, z: .042 }, radiusM: .021, lengthM: .038 }, mass: { mode: "explicit", massKg: .132 }, material: { baseColor: "#20242b", metalness: .8, roughness: .2 }, tags: ["brushless-motor", "2814-class", "survey"] },
  },
  {
    id: "motor-3508", group: "propulsion", kind: "motor", name: "3508 lift motor set",
    summary: "Higher-torque motor preset for larger propellers and payload studies.", metrics: ["184 g", "32 N max", "6–8S"], tags: ["payload", "motor", "high-torque"], applyMode: "fleet", propulsion: { maximumThrustPerMotorN: 32 },
    component: { geometry: { primitive: "cylinder", sizeM: { x: .05, y: .044, z: .05 }, radiusM: .025, lengthM: .044 }, mass: { mode: "explicit", massKg: .184 }, material: { baseColor: "#181c24", metalness: .84, roughness: .18 }, tags: ["brushless-motor", "3508-class", "high-torque"] },
  },
  {
    id: "prop-10", group: "propulsion", kind: "propeller", name: "10-inch rotor set",
    summary: "Compact rotor geometry applied consistently across the motor layout.", metrics: ["0.254 m", "14 g each", "fleet apply"], tags: ["10-inch", "agile", "propeller"], applyMode: "fleet", propulsion: { propellerDiameterM: .254 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .254, y: .008, z: .026 } }, mass: { mode: "explicit", massKg: .014 }, material: { baseColor: "#db4eb2", metalness: .18, roughness: .34 }, tags: ["rotor", "10-inch", "two-blade"] },
  },
  {
    id: "prop-13", group: "propulsion", kind: "propeller", name: "13-inch rotor set",
    summary: "Survey rotor preset with a larger disk area and editable mass model.", metrics: ["0.330 m", "23 g each", "fleet apply"], tags: ["13-inch", "survey", "propeller"], applyMode: "fleet", propulsion: { propellerDiameterM: .33 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .33, y: .009, z: .034 } }, mass: { mode: "explicit", massKg: .023 }, material: { baseColor: "#cf43a8", metalness: .2, roughness: .32 }, tags: ["rotor", "13-inch", "two-blade"] },
  },
  {
    id: "prop-15", group: "propulsion", kind: "propeller", name: "15-inch rotor set",
    summary: "Large rotor preset for low disk loading and heavy-lift studies.", metrics: ["0.381 m", "31 g each", "fleet apply"], tags: ["15-inch", "endurance", "propeller"], applyMode: "fleet", propulsion: { propellerDiameterM: .381 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .381, y: .01, z: .038 } }, mass: { mode: "explicit", massKg: .031 }, material: { baseColor: "#bd3e9e", metalness: .22, roughness: .3 }, tags: ["rotor", "15-inch", "two-blade"] },
  },
  {
    id: "battery-4s-5", group: "energy", kind: "battery", name: "4S 5 Ah flight pack",
    summary: "Compact energy preset for agile and portable airframes.", metrics: ["74 Wh", "0.48 kg", "4S"], tags: ["4s", "compact", "battery"], applyMode: "replace-or-add", propulsion: { batteryCells: 4, batteryCapacityMah: 5_000 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .145, y: .047, z: .052 } }, mass: { mode: "explicit", massKg: .48 }, material: { baseColor: "#24c6c0", metalness: .14, roughness: .38 }, tags: ["energy-storage", "4s", "5000mah"] },
  },
  {
    id: "battery-6s-10", group: "energy", kind: "battery", name: "6S 10 Ah endurance pack",
    summary: "Higher-voltage energy preset for survey and endurance layouts.", metrics: ["222 Wh", "1.31 kg", "6S"], tags: ["6s", "survey", "battery"], applyMode: "replace-or-add", propulsion: { batteryCells: 6, batteryCapacityMah: 10_000 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .19, y: .068, z: .082 } }, mass: { mode: "explicit", massKg: 1.31 }, material: { baseColor: "#1cb9b4", metalness: .14, roughness: .38 }, tags: ["energy-storage", "6s", "10000mah"] },
  },
  {
    id: "battery-6s-16", group: "energy", kind: "battery", name: "6S 16 Ah payload pack",
    summary: "Large energy preset for heavy-lift and long-duration studies.", metrics: ["355 Wh", "2.05 kg", "6S"], tags: ["6s", "payload", "battery"], applyMode: "replace-or-add", propulsion: { batteryCells: 6, batteryCapacityMah: 16_000 },
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .225, y: .078, z: .102 } }, mass: { mode: "explicit", massKg: 2.05 }, material: { baseColor: "#159f9b", metalness: .16, roughness: .36 }, tags: ["energy-storage", "6s", "16000mah"] },
  },
  {
    id: "fc-isolated", group: "avionics", kind: "flight-controller", name: "Isolated autopilot stack",
    summary: "50 mm controller envelope with a vibration-isolated material preset.", metrics: ["50 × 50 mm", "68 g", "isolated"], tags: ["autopilot", "isolated", "avionics"], applyMode: "replace-or-add",
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .05, y: .018, z: .05 } }, mass: { mode: "explicit", massKg: .068 }, material: { baseColor: "#43d49b", metalness: .2, roughness: .34 }, tags: ["flight-controller", "vibration-isolated", "serviceable"] },
  },
  {
    id: "sensor-rtk", group: "avionics", kind: "sensor", name: "Dual-band RTK GNSS",
    summary: "Editable GNSS module envelope for survey and precision navigation.", metrics: ["42 mm", "46 g", "RTK"], tags: ["gnss", "rtk", "survey"], applyMode: "add", sensor: { type: "gps", model: "Dual-band RTK GNSS" },
    component: { geometry: { primitive: "cylinder", sizeM: { x: .042, y: .018, z: .042 }, radiusM: .021, lengthM: .018 }, transform: { positionM: { x: -.06, y: .13, z: 0 } }, mass: { mode: "explicit", massKg: .046 }, material: { baseColor: "#5da7ff", metalness: .24, roughness: .28 }, tags: ["gnss", "rtk", "navigation"] },
  },
  {
    id: "sensor-lidar", group: "avionics", kind: "sensor", name: "360° ranging LiDAR",
    summary: "Rotating range-sensor envelope with an isolated top mount.", metrics: ["80 mm", "190 g", "360°"], tags: ["lidar", "navigation", "inspection"], applyMode: "add", sensor: { type: "lidar", model: "360-degree ranging lidar" },
    component: { geometry: { primitive: "cylinder", sizeM: { x: .08, y: .055, z: .08 }, radiusM: .04, lengthM: .055 }, transform: { positionM: { x: -.05, y: .15, z: 0 } }, mass: { mode: "explicit", massKg: .19 }, material: { baseColor: "#4d91ed", metalness: .28, roughness: .3 }, tags: ["lidar", "obstacle-avoidance", "isolated"] },
  },
  {
    id: "gimbal-survey", group: "mission", kind: "camera-gimbal", name: "Survey mapping gimbal",
    summary: "Stabilized camera envelope for mapping and oblique capture studies.", metrics: ["280 g", "3-axis", "mapping"], tags: ["camera", "survey", "gimbal"], applyMode: "replace-or-add", sensor: { type: "camera", model: "Stabilized survey camera" },
    component: { geometry: { primitive: "sphere", sizeM: { x: .07, y: .07, z: .07 }, radiusM: .035, lengthM: .07 }, transform: { positionM: { x: .13, y: -.085, z: 0 } }, mass: { mode: "explicit", massKg: .28 }, material: { baseColor: "#36cbea", metalness: .42, roughness: .24 }, tags: ["camera", "stabilized", "survey"] },
  },
  {
    id: "payload-quick-release", group: "mission", kind: "payload", name: "Quick-release payload bay",
    summary: "Generic mission payload envelope with editable mass and dimensions.", metrics: ["160 mm", "1.0 kg", "quick release"], tags: ["payload", "modular", "bay"], applyMode: "add",
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .16, y: .1, z: .13 } }, transform: { positionM: { x: -.06, y: -.115, z: 0 } }, mass: { mode: "explicit", massKg: 1 }, material: { baseColor: "#f0a03b", metalness: .34, roughness: .3 }, tags: ["payload", "quick-release", "mission-bay"] },
  },
  {
    id: "gear-tall", group: "mission", kind: "landing-gear", name: "Tall landing skid set",
    summary: "Raises ground clearance for gimbals and underslung payloads.", metrics: ["320 mm", "70 g each", "fleet apply"], tags: ["landing", "clearance", "payload"], applyMode: "fleet",
    component: { geometry: { primitive: "rounded-box", sizeM: { x: .32, y: .03, z: .03 }, radiusM: .015, lengthM: .32 }, transform: { positionM: { x: 0, y: -.16, z: .11 } }, mass: { mode: "explicit", massKg: .07 }, material: { baseColor: "#696274", metalness: .58, roughness: .3 }, tags: ["landing-gear", "payload-clearance", "replaceable"] },
  },
];

function applyComponentPreset(component: VehicleComponentDraft, entry: VehicleCatalogEntry) {
  const preset = entry.component;
  component.name = entry.name;
  component.source = "template";
  if (preset.geometry) component.geometry = { ...component.geometry, ...preset.geometry, sizeM: preset.geometry.sizeM ? { ...preset.geometry.sizeM } : component.geometry.sizeM };
  if (preset.transform) component.transform = {
    ...component.transform,
    ...preset.transform,
    positionM: preset.transform.positionM ? { ...preset.transform.positionM } : component.transform.positionM,
    rotationDeg: preset.transform.rotationDeg ? { ...preset.transform.rotationDeg } : component.transform.rotationDeg,
    scale: preset.transform.scale ? { ...preset.transform.scale } : component.transform.scale,
  };
  if (preset.material) component.material = { ...component.material, ...preset.material };
  if (preset.mass) component.mass = { ...component.mass, ...preset.mass };
  component.tags = [...(preset.tags ?? entry.tags)];
}

function ensureSensor(draft: VehicleModelDraft, entry: VehicleCatalogEntry) {
  if (!entry.sensor) return;
  const exists = draft.sensors.some((sensor) => sensor.type === entry.sensor!.type && sensor.model === entry.sensor!.model);
  if (!exists) draft.sensors.push({ id: crypto.randomUUID(), ...entry.sensor, enabled: true });
}

export function applyVehicleCatalogEntry(
  draft: VehicleModelDraft,
  entryId: string,
): { draft: VehicleModelDraft; selectedComponentId: string | null; affectedCount: number } {
  const entry = VEHICLE_COMPONENT_CATALOG.find((candidate) => candidate.id === entryId);
  if (!entry) return { draft, selectedComponentId: null, affectedCount: 0 };
  let next = structuredClone(draft);
  let affected: VehicleComponentDraft[] = [];

  if (entry.applyMode === "architecture" && entry.architecture) {
    next = rebuildVehicleRotorArchitecture(next, entry.architecture);
    const frame = next.components.find((component) => component.kind === "frame");
    if (frame) { applyComponentPreset(frame, entry); affected = [frame]; }
  } else if (entry.applyMode === "fleet") {
    affected = next.components.filter((component) => component.kind === entry.kind && !component.locked);
    const instanceName = entry.name.replace(/\s+set$/iu, "");
    affected.forEach((component, index) => {
      applyComponentPreset(component, entry);
      component.name = `${instanceName} ${index + 1}`;
    });
    if (entry.kind === "landing-gear") {
      affected.forEach((component, index) => { component.transform.positionM.z = index % 2 === 0 ? -.11 : .11; });
    }
  } else {
    const existing = entry.applyMode === "replace-or-add"
      ? next.components.find((component) => component.kind === entry.kind)
      : undefined;
    const component = existing ?? createVehicleComponent(entry.kind, entry.name);
    if (!existing) {
      component.parentId = next.components.find((candidate) => candidate.kind === "frame")?.id ?? null;
      next.components.push(component);
    }
    applyComponentPreset(component, entry);
    affected = [component];
  }

  if (entry.propulsion) next.propulsion = { ...next.propulsion, ...entry.propulsion };
  ensureSensor(next, entry);
  next.body.massKg = calculateVehicleDiagnostics(next).totalMassKg;
  next.updatedAt = new Date().toISOString();
  return { draft: next, selectedComponentId: affected[0]?.id ?? null, affectedCount: affected.length };
}

export function applyVehicleMaterialPreset(
  draft: VehicleModelDraft,
  componentId: string,
  presetId: string,
): VehicleModelDraft {
  const preset = VEHICLE_MATERIAL_PRESETS.find((candidate) => candidate.id === presetId);
  const next = structuredClone(draft);
  const component = next.components.find((candidate) => candidate.id === componentId);
  if (!component || component.locked) return draft;
  if (!preset) {
    if (presetId) return draft;
    component.mass.massKg = getVehicleComponentMassProperties(component).massKg;
    component.mass.mode = "explicit";
    component.tags = component.tags.filter((tag) => !tag.startsWith("material:"));
    next.body.massKg = calculateVehicleDiagnostics(next).totalMassKg;
    next.updatedAt = new Date().toISOString();
    return next;
  }
  component.mass.mode = "density";
  component.mass.densityKgM3 = preset.densityKgM3;
  component.material.baseColor = preset.baseColor;
  component.material.metalness = preset.metalness;
  component.material.roughness = preset.roughness;
  component.tags = [...new Set([...component.tags.filter((tag) => !tag.startsWith("material:")), `material:${preset.id}`])];
  next.body.massKg = calculateVehicleDiagnostics(next).totalMassKg;
  next.updatedAt = new Date().toISOString();
  return next;
}
