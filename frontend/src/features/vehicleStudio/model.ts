export const VEHICLE_MODEL_SCHEMA_VERSION = 2 as const;
export const MAX_VEHICLE_SENSORS = 32;
export const MAX_PARAMETER_FAMILIES = 64;
export const MAX_VEHICLE_COMPONENTS = 256;
export const VEHICLE_MODEL_LIMITS = Object.freeze({
  massKg: 1_000,
  bodyDimensionM: 50,
  armLengthM: 25,
  propellerDiameterM: 10,
  maximumThrustPerMotorN: 100_000,
  batteryCapacityMah: 1_000_000,
});

export type VehicleClass = "multicopter-small" | "multicopter-medium" | "multicopter-research";
export type AutopilotFamily = "px4" | "ardupilot" | "crazyflie";
export type VehiclePackTargetEdition = "sim" | "lab" | "field";
export type BodyShape = "box" | "cylinder";
export type VehicleComponentKind =
  | "fuselage" | "frame" | "arm" | "motor" | "propeller" | "landing-gear"
  | "battery" | "flight-controller" | "sensor" | "payload" | "camera-gimbal" | "custom";
export type VehiclePrimitive = "box" | "rounded-box" | "cylinder" | "sphere" | "capsule" | "cone";

export interface VehicleVector3 { x: number; y: number; z: number }
export interface VehicleSensorDraft {
  id: string;
  type: "imu" | "gps" | "barometer" | "magnetometer" | "camera" | "lidar";
  model: string;
  enabled: boolean;
}
export interface VehicleComponentDraft {
  id: string;
  name: string;
  kind: VehicleComponentKind;
  parentId: string | null;
  geometry: {
    primitive: VehiclePrimitive;
    sizeM: VehicleVector3;
    radiusM: number;
    lengthM: number;
    meshUri: string;
  };
  transform: { positionM: VehicleVector3; rotationDeg: VehicleVector3; scale: VehicleVector3 };
  material: { baseColor: string; metalness: number; roughness: number; opacity: number };
  mass: { mode: "explicit" | "density"; massKg: number; densityKgM3: number };
  visible: boolean;
  locked: boolean;
  source: "manual" | "template" | "ai";
  tags: string[];
}
export interface VehicleConstraintDraft {
  id: string;
  type: "attach" | "mirror" | "radial-array" | "clearance" | "balance";
  componentIds: string[];
  axis: "x" | "y" | "z";
  value: number;
  enabled: boolean;
}

export interface VehicleModelDraft {
  schemaVersion: typeof VEHICLE_MODEL_SCHEMA_VERSION;
  draftId: string;
  revision: number;
  name: string;
  manufacturer: string;
  vehicleClass: VehicleClass;
  body: { shape: BodyShape; massKg: number; lengthM: number; widthM: number; heightM: number };
  propulsion: {
    motorCount: 4 | 6 | 8;
    armLengthM: number;
    propellerDiameterM: number;
    maximumThrustPerMotorN: number;
    batteryCells: number;
    batteryCapacityMah: number;
  };
  sensors: VehicleSensorDraft[];
  autopilot: { family: AutopilotFamily; controllerModel: string; firmwareVersion: string };
  controlTarget: { primary: "position" | "velocity" | "attitude"; parameterFamilies: string[] };
  targetEditions: VehiclePackTargetEdition[];
  components: VehicleComponentDraft[];
  constraints: VehicleConstraintDraft[];
  designParameters: { units: "metric"; gridM: number; symmetry: "none" | "x" | "z" };
  notes: string;
  createdAt: string;
  updatedAt: string;
}

export interface LegacyVehicleModelDraftV1 {
  schemaVersion: 1;
  draftId: string;
  revision: number;
  name: string;
  manufacturer: string;
  vehicleClass: VehicleClass;
  body: VehicleModelDraft["body"];
  propulsion: VehicleModelDraft["propulsion"];
  sensors: VehicleSensorDraft[];
  autopilot: VehicleModelDraft["autopilot"];
  controlTarget: VehicleModelDraft["controlTarget"];
  targetEditions: VehiclePackTargetEdition[];
  notes: string;
  createdAt: string;
  updatedAt: string;
}

export interface VehicleModelValidationIssue { field: string; code: string; message: string }
export type VehicleDesignMission = "survey" | "endurance" | "payload" | "agility" | "inspection";
export interface VehicleDesignBrief {
  name: string;
  mission: VehicleDesignMission;
  motorCount?: 4 | 6 | 8;
  payloadKg?: number;
  targetFlightMinutes?: number;
  operatingEnvironment?: "indoor" | "outdoor" | "windy";
  camera?: boolean;
  lidar?: boolean;
}
export interface VehicleAiDesignResult {
  draft: VehicleModelDraft;
  decisions: string[];
}
export interface VehicleEngineeringDiagnostics {
  componentCount: number;
  totalMassKg: number;
  centerOfMassM: VehicleVector3;
  centerOfMassOffsetM: number;
  balanceScore: number;
  thrustToWeight: number;
  spanM: number;
  minimumRotorClearanceM: number;
  rotorDiskAreaM2: number;
  batteryEnergyWh: number;
  estimatedHoverMinutes: number;
  projectedAreaM2: number;
  engineeringWarnings: string[];
  visibleComponentCount: number;
}

export interface VehicleComponentMassProperties {
  volumeM3: number;
  massKg: number;
}

const ZERO = (): VehicleVector3 => ({ x: 0, y: 0, z: 0 });
const ONE = (): VehicleVector3 => ({ x: 1, y: 1, z: 1 });
const uuid = () => crypto.randomUUID();
const colorByKind: Record<VehicleComponentKind, string> = {
  fuselage: "#6d4aff", frame: "#2b2340", arm: "#393252", motor: "#16131f",
  propeller: "#e548b7", "landing-gear": "#6e6680", battery: "#31d4d2",
  "flight-controller": "#50e3a4", sensor: "#61a7ff", payload: "#f5a742",
  "camera-gimbal": "#35d6f0", custom: "#9b72ff",
};

function makeComponent(input: Partial<VehicleComponentDraft> & Pick<VehicleComponentDraft, "name" | "kind">): VehicleComponentDraft {
  const kind = input.kind;
  return {
    id: input.id ?? uuid(), name: input.name, kind, parentId: input.parentId ?? null,
    geometry: input.geometry ?? { primitive: "rounded-box", sizeM: { x: .12, y: .06, z: .12 }, radiusM: .03, lengthM: .12, meshUri: "" },
    transform: input.transform ?? { positionM: ZERO(), rotationDeg: ZERO(), scale: ONE() },
    material: input.material ?? { baseColor: colorByKind[kind], metalness: .35, roughness: .42, opacity: 1 },
    mass: input.mass ?? { mode: "explicit", massKg: .05, densityKgM3: 1200 },
    visible: input.visible ?? true, locked: input.locked ?? false, source: input.source ?? "manual", tags: input.tags ?? [],
  };
}

export function createVehicleComponent(kind: VehicleComponentKind, name?: string): VehicleComponentDraft {
  const component = makeComponent({ name: name ?? kind.replaceAll("-", " "), kind });
  const geometry = component.geometry;
  if (kind === "fuselage") Object.assign(geometry, { primitive: "capsule", sizeM: { x: .34, y: .14, z: .2 }, radiusM: .1, lengthM: .34 });
  if (kind === "frame") Object.assign(geometry, { primitive: "rounded-box", sizeM: { x: .24, y: .035, z: .18 } });
  if (kind === "arm") Object.assign(geometry, { primitive: "rounded-box", sizeM: { x: .28, y: .028, z: .035 } });
  if (kind === "motor") Object.assign(geometry, { primitive: "cylinder", sizeM: { x: .055, y: .055, z: .055 }, radiusM: .028, lengthM: .055 });
  if (kind === "propeller") Object.assign(geometry, { primitive: "rounded-box", sizeM: { x: .254, y: .008, z: .026 } });
  if (kind === "landing-gear") Object.assign(geometry, { primitive: "capsule", sizeM: { x: .3, y: .025, z: .025 }, radiusM: .012, lengthM: .3 });
  if (kind === "battery") Object.assign(geometry, { primitive: "rounded-box", sizeM: { x: .14, y: .045, z: .055 } });
  if (kind === "flight-controller") Object.assign(geometry, { primitive: "rounded-box", sizeM: { x: .05, y: .012, z: .05 } });
  if (kind === "sensor") Object.assign(geometry, { primitive: "cylinder", sizeM: { x: .025, y: .018, z: .025 }, radiusM: .013, lengthM: .018 });
  if (kind === "camera-gimbal") Object.assign(geometry, { primitive: "sphere", sizeM: { x: .055, y: .055, z: .055 }, radiusM: .028 });
  return component;
}

function appendRotorLayout(
  parts: VehicleComponentDraft[],
  count: 4 | 6 | 8,
  armLengthM = .27,
  propellerDiameterM = .254,
  frameId: string | null = null,
) {
  for (let index = 0; index < count; index += 1) {
    const angle = index * 360 / count + (count === 4 ? 45 : 0);
    const rad = angle * Math.PI / 180;
    const arm = createVehicleComponent("arm", `Arm ${index + 1}`);
    arm.parentId = frameId;
    arm.mass.massKg = .055;
    arm.geometry.sizeM.x = Math.max(.08, armLengthM - .02);
    arm.transform.rotationDeg.y = -angle;
    arm.transform.positionM = { x: Math.cos(rad) * armLengthM * .48, y: 0, z: Math.sin(rad) * armLengthM * .48 };
    parts.push(arm);
    const motor = createVehicleComponent("motor", `Motor ${index + 1}`);
    motor.parentId = arm.id;
    motor.mass.massKg = .055;
    motor.transform.positionM = { x: Math.cos(rad) * armLengthM, y: .025, z: Math.sin(rad) * armLengthM };
    parts.push(motor);
    const prop = createVehicleComponent("propeller", `Propeller ${index + 1}`);
    prop.parentId = motor.id;
    prop.mass.massKg = .014;
    prop.geometry.sizeM.x = propellerDiameterM;
    prop.transform.positionM = { x: Math.cos(rad) * armLengthM, y: .062, z: Math.sin(rad) * armLengthM };
    prop.transform.rotationDeg.y = angle;
    parts.push(prop);
  }
}

function defaultComponents(
  motorCount: 4 | 6 | 8 = 4,
  armLengthM = .27,
  propellerDiameterM = .254,
): VehicleComponentDraft[] {
  const parts: VehicleComponentDraft[] = [];
  const frame = createVehicleComponent("frame", "Carbon center frame"); frame.mass.massKg = .22; parts.push(frame);
  const fuselage = createVehicleComponent("fuselage", "Aerodynamic canopy"); fuselage.parentId = frame.id; fuselage.mass.massKg = .28; fuselage.transform.positionM.y = .055; parts.push(fuselage);
  const battery = createVehicleComponent("battery", "4S flight battery"); battery.parentId = frame.id; battery.mass.massKg = .46; battery.transform.positionM.y = -.035; parts.push(battery);
  const controller = createVehicleComponent("flight-controller", "Pixhawk flight controller"); controller.parentId = frame.id; controller.mass.massKg = .055; controller.transform.positionM.y = .025; parts.push(controller);
  const camera = createVehicleComponent("camera-gimbal", "Survey camera gimbal"); camera.parentId = frame.id; camera.mass.massKg = .09; camera.transform.positionM = { x: .12, y: -.07, z: 0 }; parts.push(camera);
  appendRotorLayout(parts, motorCount, armLengthM, propellerDiameterM, frame.id);
  for (const [index, z] of [-.095, .095].entries()) {
    const gear = createVehicleComponent("landing-gear", `Landing skid ${index + 1}`);
    gear.parentId = frame.id; gear.mass.massKg = .045; gear.transform.positionM = { x: 0, y: -.12, z }; parts.push(gear);
  }
  return parts;
}

function finitePositive(value: number): boolean { return Number.isFinite(value) && value > 0; }
function finitePositiveAtMost(value: number, maximum: number): boolean { return finitePositive(value) && value <= maximum; }
function validVector(value: VehicleVector3): boolean { return [value.x, value.y, value.z].every(Number.isFinite); }

function scaledGeometry(component: VehicleComponentDraft) {
  const scale = component.transform.scale;
  return {
    x: Math.abs(component.geometry.sizeM.x * scale.x),
    y: Math.abs(component.geometry.sizeM.y * scale.y),
    z: Math.abs(component.geometry.sizeM.z * scale.z),
    radius: Math.abs(component.geometry.radiusM * Math.max(scale.x, scale.z)),
    length: Math.abs(component.geometry.lengthM * scale.y),
  };
}

export function calculateVehicleComponentVolumeM3(component: VehicleComponentDraft): number {
  const geometry = scaledGeometry(component);
  switch (component.geometry.primitive) {
    case "sphere": return 4 / 3 * Math.PI * geometry.radius ** 3;
    case "cylinder": return Math.PI * geometry.radius ** 2 * geometry.length;
    case "capsule": return Math.PI * geometry.radius ** 2 * geometry.length + 4 / 3 * Math.PI * geometry.radius ** 3;
    case "cone": return Math.PI * geometry.radius ** 2 * geometry.length / 3;
    default: return geometry.x * geometry.y * geometry.z;
  }
}

export function getVehicleComponentMassProperties(component: VehicleComponentDraft): VehicleComponentMassProperties {
  const volumeM3 = calculateVehicleComponentVolumeM3(component);
  const massKg = component.mass.mode === "density"
    ? volumeM3 * component.mass.densityKgM3
    : component.mass.massKg;
  return { volumeM3, massKg };
}

export function getVehicleComponentDescendantIds(draft: VehicleModelDraft, componentId: string): Set<string> {
  const descendants = new Set<string>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const component of draft.components) {
      if (component.parentId && (component.parentId === componentId || descendants.has(component.parentId)) && !descendants.has(component.id)) {
        descendants.add(component.id);
        changed = true;
      }
    }
  }
  return descendants;
}

export function canSetVehicleComponentParent(draft: VehicleModelDraft, componentId: string, parentId: string | null): boolean {
  if (parentId === null) return true;
  if (parentId === componentId || !draft.components.some((component) => component.id === parentId)) return false;
  return !getVehicleComponentDescendantIds(draft, componentId).has(parentId);
}

export function calculateVehicleDiagnostics(draft: VehicleModelDraft): VehicleEngineeringDiagnostics {
  // Visibility is a viewport concern. Hidden parts remain physical members of
  // the saved/exported assembly and therefore must participate in every
  // engineering calculation.
  const physicalComponents = draft.components;
  const effectiveMasses = new Map(physicalComponents.map((component) => [component.id, getVehicleComponentMassProperties(component).massKg]));
  const totalMassKg = physicalComponents.reduce((sum, component) => sum + (Number.isFinite(effectiveMasses.get(component.id)) ? effectiveMasses.get(component.id)! : 0), 0);
  const centerOfMassM = totalMassKg > 0 ? physicalComponents.reduce((sum, component) => ({
    x: sum.x + component.transform.positionM.x * effectiveMasses.get(component.id)! / totalMassKg,
    y: sum.y + component.transform.positionM.y * effectiveMasses.get(component.id)! / totalMassKg,
    z: sum.z + component.transform.positionM.z * effectiveMasses.get(component.id)! / totalMassKg,
  }), ZERO()) : ZERO();
  const spanM = physicalComponents.reduce((maximum, component) => Math.max(maximum,
    Math.abs(component.transform.positionM.x) * 2 + scaledGeometry(component).x,
    Math.abs(component.transform.positionM.z) * 2 + scaledGeometry(component).z,
  ), 0);
  const engineeringMassKg = Math.max(totalMassKg, Number.isFinite(draft.body.massKg) ? draft.body.massKg : 0);
  const centerOfMassOffsetM = Math.hypot(centerOfMassM.x, centerOfMassM.z);
  const balanceReferenceM = Math.max(.02, spanM * .08);
  const balanceScore = Math.max(0, Math.min(100, 100 * (1 - centerOfMassOffsetM / balanceReferenceM)));
  const rotors = physicalComponents.filter((component) => component.kind === "propeller").map((component) => {
    const geometry = scaledGeometry(component);
    return {
      x: component.transform.positionM.x,
      z: component.transform.positionM.z,
      radius: Math.max(geometry.x, geometry.z, component.geometry.radiusM * 2) / 2,
    };
  });
  let minimumRotorClearanceM = Number.POSITIVE_INFINITY;
  for (let first = 0; first < rotors.length; first += 1) {
    for (let second = first + 1; second < rotors.length; second += 1) {
      const distance = Math.hypot(rotors[first].x - rotors[second].x, rotors[first].z - rotors[second].z);
      minimumRotorClearanceM = Math.min(minimumRotorClearanceM, distance - rotors[first].radius - rotors[second].radius);
    }
  }
  if (!Number.isFinite(minimumRotorClearanceM)) minimumRotorClearanceM = 0;
  const rotorDiskAreaM2 = rotors.reduce((sum, rotor) => sum + Math.PI * rotor.radius ** 2, 0);
  const batteryEnergyWh = draft.propulsion.batteryCells * 3.7 * draft.propulsion.batteryCapacityMah / 1_000;
  const weightN = engineeringMassKg * 9.80665;
  const inducedPowerW = rotorDiskAreaM2 > 0 && weightN > 0
    ? weightN ** 1.5 / Math.sqrt(2 * 1.225 * rotorDiskAreaM2)
    : 0;
  const estimatedElectricalPowerW = inducedPowerW > 0 ? inducedPowerW / .62 + 28 : 0;
  const estimatedHoverMinutes = estimatedElectricalPowerW > 0
    ? batteryEnergyWh * .8 / estimatedElectricalPowerW * 60
    : 0;
  const projectedAreaM2 = physicalComponents.reduce((sum, component) => {
    const geometry = scaledGeometry(component);
    return sum + geometry.x * geometry.z * (component.kind === "propeller" ? .08 : .72);
  }, 0);
  const engineeringWarnings: string[] = [];
  if (minimumRotorClearanceM < .01) engineeringWarnings.push("Rotor disk clearance is below 10 mm.");
  if (centerOfMassOffsetM > balanceReferenceM * .5) engineeringWarnings.push("The projected center of mass is materially off the thrust centroid.");
  if (estimatedHoverMinutes > 0 && estimatedHoverMinutes < 8) engineeringWarnings.push("Estimated hover endurance is below eight minutes.");
  const thrustToWeight = engineeringMassKg > 0 ? draft.propulsion.motorCount * draft.propulsion.maximumThrustPerMotorN / (engineeringMassKg * 9.80665) : 0;
  if (thrustToWeight < 1.8) engineeringWarnings.push("Thrust margin is below the preferred 1.8:1 engineering target.");
  return {
    componentCount: draft.components.length,
    visibleComponentCount: draft.components.filter((component) => component.visible).length,
    totalMassKg,
    centerOfMassM, centerOfMassOffsetM, balanceScore, spanM, minimumRotorClearanceM,
    rotorDiskAreaM2, batteryEnergyWh, estimatedHoverMinutes, projectedAreaM2, engineeringWarnings,
    thrustToWeight,
  };
}

export function validateVehicleModel(draft: VehicleModelDraft): VehicleModelValidationIssue[] {
  const issues: VehicleModelValidationIssue[] = [];
  const requireText = (field: string, value: string, maximum: number) => {
    const normalized = value.trim();
    if (!normalized) issues.push({ field, code: "required", message: "Required" });
    else if (normalized.length > maximum) issues.push({ field, code: "too-long", message: `Maximum ${maximum} characters` });
  };
  const bounded = (field: string, value: number, maximum: number) => {
    if (!finitePositiveAtMost(value, maximum)) issues.push({ field, code: "bounded-positive-number", message: `Must be greater than zero and no more than ${maximum}` });
  };
  requireText("name", draft.name, 96); requireText("manufacturer", draft.manufacturer, 96);
  if (draft.schemaVersion !== 2) issues.push({ field: "schemaVersion", code: "unsupported-schema", message: "Unsupported model schema" });
  if (!Number.isInteger(draft.revision) || draft.revision < 1) issues.push({ field: "revision", code: "invalid-revision", message: "Revision must be a positive integer" });
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(draft.draftId)) issues.push({ field: "draftId", code: "invalid-draft-id", message: "Draft identity is invalid" });
  requireText("autopilot.controllerModel", draft.autopilot.controllerModel, 96); requireText("autopilot.firmwareVersion", draft.autopilot.firmwareVersion, 64);
  bounded("body.massKg", draft.body.massKg, VEHICLE_MODEL_LIMITS.massKg); bounded("body.lengthM", draft.body.lengthM, VEHICLE_MODEL_LIMITS.bodyDimensionM); bounded("body.widthM", draft.body.widthM, VEHICLE_MODEL_LIMITS.bodyDimensionM); bounded("body.heightM", draft.body.heightM, VEHICLE_MODEL_LIMITS.bodyDimensionM);
  bounded("propulsion.armLengthM", draft.propulsion.armLengthM, VEHICLE_MODEL_LIMITS.armLengthM); bounded("propulsion.propellerDiameterM", draft.propulsion.propellerDiameterM, VEHICLE_MODEL_LIMITS.propellerDiameterM); bounded("propulsion.maximumThrustPerMotorN", draft.propulsion.maximumThrustPerMotorN, VEHICLE_MODEL_LIMITS.maximumThrustPerMotorN); bounded("propulsion.batteryCapacityMah", draft.propulsion.batteryCapacityMah, VEHICLE_MODEL_LIMITS.batteryCapacityMah);
  if (!Number.isInteger(draft.propulsion.batteryCells) || draft.propulsion.batteryCells < 1 || draft.propulsion.batteryCells > 16) issues.push({ field: "propulsion.batteryCells", code: "invalid-cell-count", message: "Battery cells must be an integer from 1 to 16" });
  if (draft.notes.length > 4096) issues.push({ field: "notes", code: "too-long", message: "Maximum 4096 characters" });
  const families = draft.controlTarget.parameterFamilies.map((family) => family.trim().toUpperCase());
  if (families.length > MAX_PARAMETER_FAMILIES || new Set(families).size !== families.length || families.some((family) => !family || family.length > 64)) issues.push({ field: "controlTarget.parameterFamilies", code: "invalid-family-set", message: `Use no more than ${MAX_PARAMETER_FAMILIES} unique parameter families` });
  if (draft.sensors.length < 1 || draft.sensors.length > MAX_VEHICLE_SENSORS) issues.push({ field: "sensors", code: "invalid-sensor-count", message: `Use 1 to ${MAX_VEHICLE_SENSORS} sensors` });
  if (new Set(draft.sensors.map((sensor) => sensor.id)).size !== draft.sensors.length) issues.push({ field: "sensors", code: "duplicate-sensor", message: "Sensor identities must be unique" });
  if (!draft.sensors.some((sensor) => sensor.enabled && sensor.type === "imu")) issues.push({ field: "sensors", code: "imu-required", message: "At least one IMU is required" });
  if (draft.targetEditions.length === 0 || draft.targetEditions.length > 3 || new Set(draft.targetEditions).size !== draft.targetEditions.length) issues.push({ field: "targetEditions", code: "target-required", message: "Select at least one target Edition" });
  if (draft.targetEditions.includes("field") && draft.autopilot.family === "crazyflie") issues.push({ field: "targetEditions", code: "field-adapter-unavailable", message: "The Crazyflie Field adapter is planned and cannot be exported as compatible" });
  if (!Array.isArray(draft.components) || draft.components.length < 1 || draft.components.length > MAX_VEHICLE_COMPONENTS) issues.push({ field: "components", code: "invalid-component-count", message: `Use 1 to ${MAX_VEHICLE_COMPONENTS} components` });
  const ids = new Set<string>();
  for (const component of draft.components) {
    if (!component.id || ids.has(component.id)) issues.push({ field: "components", code: "duplicate-component", message: "Component identities must be unique" });
    ids.add(component.id); requireText(`components.${component.id}.name`, component.name, 96);
    if (!validVector(component.transform.positionM) || !validVector(component.transform.rotationDeg) || !validVector(component.transform.scale)) issues.push({ field: `components.${component.id}.transform`, code: "invalid-transform", message: "Transform values must be finite" });
    else if (![component.transform.scale.x, component.transform.scale.y, component.transform.scale.z].every(finitePositive)) issues.push({ field: `components.${component.id}.transform.scale`, code: "invalid-scale", message: "Scale values must be greater than zero" });
    if (!validVector(component.geometry.sizeM) || ![component.geometry.sizeM.x, component.geometry.sizeM.y, component.geometry.sizeM.z].every(finitePositive)) issues.push({ field: `components.${component.id}.geometry`, code: "invalid-geometry", message: "Geometry dimensions must be positive" });
    if (![component.geometry.radiusM, component.geometry.lengthM].every(finitePositive)) issues.push({ field: `components.${component.id}.geometry`, code: "invalid-radius-or-length", message: "Radius and length must be greater than zero" });
    if (component.mass.mode === "density") bounded(`components.${component.id}.mass.densityKgM3`, component.mass.densityKgM3, 30_000);
    else bounded(`components.${component.id}.mass.massKg`, component.mass.massKg, VEHICLE_MODEL_LIMITS.massKg);
    const effectiveMass = getVehicleComponentMassProperties(component).massKg;
    if (!finitePositiveAtMost(effectiveMass, VEHICLE_MODEL_LIMITS.massKg)) issues.push({ field: `components.${component.id}.mass`, code: "invalid-effective-mass", message: `Calculated mass must be greater than zero and no more than ${VEHICLE_MODEL_LIMITS.massKg}` });
    if (!/^#[0-9a-f]{6}$/i.test(component.material.baseColor)) issues.push({ field: `components.${component.id}.material`, code: "invalid-color", message: "Material color must be #RRGGBB" });
    if (![component.material.metalness, component.material.roughness, component.material.opacity].every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) issues.push({ field: `components.${component.id}.material`, code: "invalid-material-range", message: "Metalness, roughness, and opacity must be between zero and one" });
    if (!Array.isArray(component.tags) || component.tags.length > 16 || component.tags.some((tag) => !tag.trim() || tag.length > 32)) issues.push({ field: `components.${component.id}.tags`, code: "invalid-tags", message: "Use no more than 16 non-empty tags of at most 32 characters" });
  }
  for (const component of draft.components) {
    if (component.parentId && !ids.has(component.parentId)) issues.push({ field: `components.${component.id}.parentId`, code: "missing-parent", message: "Parent component is missing" });
    if (component.parentId === component.id) issues.push({ field: `components.${component.id}.parentId`, code: "self-parent", message: "A component cannot be its own parent" });
    const visited = new Set<string>([component.id]);
    let cursor = component.parentId;
    while (cursor) {
      if (visited.has(cursor)) { issues.push({ field: `components.${component.id}.parentId`, code: "assembly-cycle", message: "Assembly hierarchy contains a cycle" }); break; }
      visited.add(cursor);
      cursor = draft.components.find((candidate) => candidate.id === cursor)?.parentId ?? null;
    }
  }
  if (!finitePositiveAtMost(draft.designParameters.gridM, 1)) issues.push({ field: "designParameters.gridM", code: "invalid-grid", message: "Grid spacing must be greater than zero and no more than one metre" });
  const constraintIds = new Set<string>();
  for (const constraint of draft.constraints) {
    if (!constraint.id || constraintIds.has(constraint.id)) issues.push({ field: "constraints", code: "duplicate-constraint", message: "Constraint identities must be unique" });
    constraintIds.add(constraint.id);
    if (constraint.componentIds.length === 0 || constraint.componentIds.some((id) => !ids.has(id)) || new Set(constraint.componentIds).size !== constraint.componentIds.length) issues.push({ field: `constraints.${constraint.id}.componentIds`, code: "invalid-constraint-components", message: "Constraint component references must exist and be unique" });
    if (!Number.isFinite(constraint.value)) issues.push({ field: `constraints.${constraint.id}.value`, code: "invalid-constraint-value", message: "Constraint value must be finite" });
    if (constraint.type === "mirror" && constraint.componentIds.length !== 2) issues.push({ field: `constraints.${constraint.id}.componentIds`, code: "mirror-pair-required", message: "Mirror constraints require exactly two components" });
    if (constraint.type === "radial-array" && constraint.componentIds.length < 2) issues.push({ field: `constraints.${constraint.id}.componentIds`, code: "array-members-required", message: "Radial arrays require at least two components" });
  }
  const diagnostics = calculateVehicleDiagnostics(draft);
  if (!finitePositive(diagnostics.thrustToWeight) || diagnostics.thrustToWeight < 1.6) issues.push({ field: "propulsion.maximumThrustPerMotorN", code: "insufficient-thrust-margin", message: "Total thrust-to-weight ratio must be at least 1.6 for this draft contract" });
  if (diagnostics.minimumRotorClearanceM < 0) issues.push({ field: "components", code: "rotor-disk-intersection", message: "Rotor disks intersect; increase arm length or reduce propeller diameter" });
  for (const [field, timestamp] of [["createdAt", draft.createdAt], ["updatedAt", draft.updatedAt]] as const) if (!Number.isFinite(Date.parse(timestamp))) issues.push({ field, code: "invalid-timestamp", message: "Timestamp must use a valid ISO date-time" });
  return issues;
}

export function createVehicleModelDraft(now = new Date()): VehicleModelDraft {
  const timestamp = now.toISOString();
  const components = defaultComponents();
  const totalMass = components.reduce((sum, component) => sum + component.mass.massKg, 0);
  return {
    schemaVersion: 2, draftId: uuid(), revision: 1, name: "Custom quadrotor", manufacturer: "Custom", vehicleClass: "multicopter-medium",
    body: { shape: "box", massKg: totalMass, lengthM: .34, widthM: .2, heightM: .14 },
    propulsion: { motorCount: 4, armLengthM: .27, propellerDiameterM: .254, maximumThrustPerMotorN: 9, batteryCells: 4, batteryCapacityMah: 5000 },
    sensors: [
      { id: uuid(), type: "imu", model: "Generic IMU", enabled: true },
      { id: uuid(), type: "gps", model: "Generic GNSS", enabled: true },
      { id: uuid(), type: "barometer", model: "Generic barometer", enabled: true },
    ],
    autopilot: { family: "px4", controllerModel: "Pixhawk compatible", firmwareVersion: "v1.16.0" },
    controlTarget: { primary: "position", parameterFamilies: ["MPC_XY", "MPC_Z", "MC_ROLL", "MC_PITCH", "MC_YAW"] },
    targetEditions: ["sim", "lab"], components, constraints: [], designParameters: { units: "metric", gridM: .01, symmetry: "x" },
    notes: "", createdAt: timestamp, updatedAt: timestamp,
  };
}

function createEngineeringConstraints(components: VehicleComponentDraft[]): VehicleConstraintDraft[] {
  const byKind = (kind: VehicleComponentKind) => components.filter((component) => component.kind === kind).map((component) => component.id);
  const constraints: VehicleConstraintDraft[] = [];
  for (const kind of ["arm", "motor", "propeller"] as VehicleComponentKind[]) {
    const ids = byKind(kind);
    if (ids.length > 1) constraints.push({ id: uuid(), type: "radial-array", componentIds: ids, axis: "y", value: ids.length, enabled: true });
  }
  const propellers = byKind("propeller");
  if (propellers.length > 1) constraints.push({ id: uuid(), type: "clearance", componentIds: propellers, axis: "y", value: .01, enabled: true });
  const balanced = components.filter((component) => !["propeller", "arm"].includes(component.kind)).map((component) => component.id);
  if (balanced.length > 1) constraints.push({ id: uuid(), type: "balance", componentIds: balanced, axis: "y", value: .015, enabled: true });
  for (const component of components) {
    if (component.parentId) constraints.push({ id: uuid(), type: "attach", componentIds: [component.parentId, component.id], axis: "y", value: 0, enabled: true });
  }
  return constraints;
}

export function rebuildVehicleRotorArchitecture(
  draft: VehicleModelDraft,
  propulsion: Pick<VehicleModelDraft["propulsion"], "motorCount" | "armLengthM" | "propellerDiameterM">,
  now = new Date(),
): VehicleModelDraft {
  const next = structuredClone(draft);
  const removedIds = new Set(next.components
    .filter((component) => ["arm", "motor", "propeller"].includes(component.kind))
    .map((component) => component.id));
  let discoveredChild = true;
  while (discoveredChild) {
    discoveredChild = false;
    for (const component of next.components) {
      if (component.parentId && removedIds.has(component.parentId) && !removedIds.has(component.id)) {
        removedIds.add(component.id);
        discoveredChild = true;
      }
    }
  }
  next.components = next.components.filter((component) => !removedIds.has(component.id));
  const frame = next.components.find((component) => component.kind === "frame");
  if (!frame) throw new Error("A frame component is required before rebuilding the rotor architecture.");
  appendRotorLayout(
    next.components,
    propulsion.motorCount,
    propulsion.armLengthM,
    propulsion.propellerDiameterM,
    frame.id,
  );
  next.propulsion = { ...next.propulsion, ...propulsion };
  next.constraints = createEngineeringConstraints(next.components);
  next.body.massKg = calculateVehicleDiagnostics(next).totalMassKg;
  next.updatedAt = now.toISOString();
  return next;
}

export function createVehicleModelFromBrief(brief: VehicleDesignBrief, now = new Date()): VehicleAiDesignResult {
  const motorCount = brief.motorCount ?? (brief.mission === "payload" ? 8 : brief.mission === "survey" || brief.mission === "endurance" ? 6 : 4);
  const targetFlightMinutes = Math.max(6, Math.min(60, brief.targetFlightMinutes ?? (brief.mission === "endurance" ? 32 : 18)));
  const payloadKg = Math.max(0, Math.min(12, brief.payloadKg ?? (brief.mission === "payload" ? 2 : .35)));
  const propellerDiameterM = motorCount === 8 ? .305 : brief.mission === "endurance" ? .381 : motorCount === 6 ? .33 : .279;
  // Adjacent motors on a regular N-gon are 2r*sin(pi/N) apart. Size the arm
  // radius from that chord, not from a quad-only diameter ratio, so assisted
  // hex/octo layouts never begin with intersecting rotor disks.
  const minimumRotorClearanceM = .018;
  const clearanceBoundArmLengthM = (propellerDiameterM + minimumRotorClearanceM)
    / (2 * Math.sin(Math.PI / motorCount));
  const armLengthM = Math.max(clearanceBoundArmLengthM, motorCount === 8 ? .42 : motorCount === 6 ? .36 : .3);
  const batteryCells = motorCount >= 6 || payloadKg > 1 ? 6 : 4;
  const batteryCapacityMah = Math.round(Math.max(5_000, Math.min(30_000, targetFlightMinutes * (motorCount * 150 + payloadKg * 900))) / 100) * 100;
  const components = defaultComponents(motorCount, armLengthM, propellerDiameterM);
  const frame = components.find((component) => component.kind === "frame");
  const battery = components.find((component) => component.kind === "battery");
  const camera = components.find((component) => component.kind === "camera-gimbal");
  if (frame) {
    frame.geometry.sizeM = { x: motorCount >= 6 ? .3 : .25, y: .038, z: motorCount >= 6 ? .22 : .18 };
    frame.mass.massKg = .17 + motorCount * .018;
    frame.tags = ["primary-structure", "carbon-laminate"];
  }
  if (battery) {
    battery.name = `${batteryCells}S ${batteryCapacityMah} mAh energy pack`;
    battery.geometry.sizeM = { x: .145 + batteryCapacityMah / 160_000, y: .045 + batteryCells * .002, z: .06 + batteryCapacityMah / 300_000 };
    battery.mass.massKg = batteryCapacityMah * batteryCells * .0000165;
    battery.tags = ["energy-storage", "serviceable"];
  }
  if (camera && brief.camera === false) components.splice(components.indexOf(camera), 1);
  else if (camera) {
    camera.name = brief.mission === "inspection" ? "Inspection zoom gimbal" : "Survey mapping gimbal";
    camera.mass.massKg = brief.mission === "survey" ? .28 : .16;
    camera.tags = ["payload", "stabilized", brief.mission];
  }
  if (payloadKg > .45) {
    const payload = createVehicleComponent("payload", "Mission payload bay");
    payload.parentId = frame?.id ?? null;
    payload.geometry.primitive = "rounded-box";
    payload.geometry.sizeM = { x: .16, y: .1, z: .13 };
    payload.transform.positionM = { x: -.06, y: -.105, z: 0 };
    payload.mass.massKg = payloadKg;
    payload.tags = ["payload", "quick-release"];
    components.push(payload);
  }
  if (brief.lidar) {
    const lidar = createVehicleComponent("sensor", "360-degree lidar");
    lidar.parentId = frame?.id ?? null;
    lidar.geometry = { primitive: "cylinder", sizeM: { x: .08, y: .055, z: .08 }, radiusM: .04, lengthM: .055, meshUri: "" };
    lidar.transform.positionM = { x: -.05, y: .13, z: 0 };
    lidar.mass.massKg = .19;
    lidar.tags = ["lidar", "navigation", "obstacle-avoidance"];
    components.push(lidar);
  }
  for (const component of components) component.source = "ai";
  const timestamp = now.toISOString();
  const totalMassKg = components.reduce((sum, component) => sum + getVehicleComponentMassProperties(component).massKg, 0);
  const draft: VehicleModelDraft = {
    ...createVehicleModelDraft(now),
    draftId: uuid(),
    name: brief.name.trim() || `${brief.mission[0].toUpperCase()}${brief.mission.slice(1)} multirotor`,
    manufacturer: "DroneDream assisted design",
    vehicleClass: motorCount === 4 && totalMassKg < 2 ? "multicopter-small" : "multicopter-research",
    body: { shape: "box", massKg: totalMassKg, lengthM: motorCount >= 6 ? .4 : .34, widthM: motorCount >= 6 ? .25 : .2, heightM: .16 },
    propulsion: { motorCount, armLengthM, propellerDiameterM, maximumThrustPerMotorN: Math.max(12, (totalMassKg * 9.80665 * 2.1) / motorCount), batteryCells, batteryCapacityMah },
    sensors: [
      { id: uuid(), type: "imu", model: "Triple-redundant IMU", enabled: true },
      { id: uuid(), type: "gps", model: "Dual-band RTK GNSS", enabled: brief.operatingEnvironment !== "indoor" },
      { id: uuid(), type: "barometer", model: "Temperature-compensated barometer", enabled: true },
      ...(brief.camera === false ? [] : [{ id: uuid(), type: "camera" as const, model: "Stabilized mission camera", enabled: true }]),
      ...(brief.lidar ? [{ id: uuid(), type: "lidar" as const, model: "360-degree ranging lidar", enabled: true }] : []),
    ],
    components,
    constraints: createEngineeringConstraints(components),
    targetEditions: ["sim", "lab"],
    notes: `Mission: ${brief.mission}. Target hover endurance: ${targetFlightMinutes} min. Payload allowance: ${payloadKg.toFixed(2)} kg. Environment: ${brief.operatingEnvironment ?? "outdoor"}.`,
    createdAt: timestamp,
    updatedAt: timestamp,
  };
  draft.body.massKg = calculateVehicleDiagnostics(draft).totalMassKg;
  return {
    draft,
    decisions: [
      `${motorCount}-motor layout selected for ${brief.mission} redundancy and disk loading.`,
      `${propellerDiameterM.toFixed(3)} m propellers paired with ${armLengthM.toFixed(3)} m arms to preserve rotor clearance.`,
      `${batteryCells}S ${batteryCapacityMah} mAh energy system sized for a ${targetFlightMinutes}-minute design target.`,
      payloadKg > 0 ? `${payloadKg.toFixed(2)} kg mission payload is represented as an editable assembly component.` : "No external mission payload was requested.",
    ],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isLegacyVehicleModelDraft(value: unknown): value is LegacyVehicleModelDraftV1 {
  return isRecord(value)
    && value.schemaVersion === 1
    && typeof value.draftId === "string"
    && typeof value.name === "string"
    && typeof value.manufacturer === "string"
    && isRecord(value.body)
    && isRecord(value.propulsion)
    && [4, 6, 8].includes(Number(value.propulsion.motorCount))
    && Array.isArray(value.sensors)
    && isRecord(value.autopilot)
    && isRecord(value.controlTarget)
    && Array.isArray(value.targetEditions)
    && typeof value.createdAt === "string"
    && typeof value.updatedAt === "string";
}

export function migrateVehicleModelDraft(value: unknown): VehicleModelDraft {
  if (isRecord(value) && value.schemaVersion === VEHICLE_MODEL_SCHEMA_VERSION) {
    return structuredClone(value) as unknown as VehicleModelDraft;
  }
  if (!isLegacyVehicleModelDraft(value)) {
    throw new Error("Unsupported vehicle model schema");
  }
  const legacy = structuredClone(value);
  const components = defaultComponents(
    legacy.propulsion.motorCount,
    legacy.propulsion.armLengthM,
    legacy.propulsion.propellerDiameterM,
  );
  const frame = components.find((component) => component.kind === "frame");
  const fuselage = components.find((component) => component.kind === "fuselage");
  if (frame) {
    frame.geometry.sizeM = {
      x: legacy.body.lengthM,
      y: Math.min(legacy.body.heightM * .34, legacy.body.heightM),
      z: legacy.body.widthM,
    };
  }
  if (fuselage) {
    fuselage.geometry.primitive = legacy.body.shape === "cylinder" ? "capsule" : "rounded-box";
    fuselage.geometry.sizeM = {
      x: legacy.body.lengthM,
      y: legacy.body.heightM,
      z: legacy.body.widthM,
    };
  }
  const generatedMassKg = components.reduce((sum, component) => sum + component.mass.massKg, 0);
  const massScale = legacy.body.massKg / generatedMassKg;
  for (const component of components) component.mass.massKg *= massScale;
  // Put the floating-point remainder on one component so the migrated assembly
  // preserves the legacy total exactly rather than silently gaining mass.
  const migratedMassKg = components.reduce((sum, component) => sum + component.mass.massKg, 0);
  if (fuselage) fuselage.mass.massKg += legacy.body.massKg - migratedMassKg;
  return {
    ...legacy,
    schemaVersion: VEHICLE_MODEL_SCHEMA_VERSION,
    components,
    constraints: [],
    designParameters: { units: "metric", gridM: .01, symmetry: "x" },
  };
}

export function addVehicleComponent(draft: VehicleModelDraft, kind: VehicleComponentKind): VehicleModelDraft {
  const next = structuredClone(draft); const component = createVehicleComponent(kind); component.parentId = next.components.find((candidate) => candidate.kind === "frame")?.id ?? null; next.components.push(component); next.updatedAt = new Date().toISOString(); return next;
}
export function updateVehicleComponent(draft: VehicleModelDraft, id: string, updater: (component: VehicleComponentDraft) => void): VehicleModelDraft {
  const next = structuredClone(draft); const component = next.components.find((item) => item.id === id); if (component && !component.locked) updater(component); next.updatedAt = new Date().toISOString(); return next;
}
export function setVehicleComponentLocked(draft: VehicleModelDraft, id: string, locked: boolean): VehicleModelDraft {
  const next = structuredClone(draft); const component = next.components.find((item) => item.id === id); if (component) component.locked = locked; next.updatedAt = new Date().toISOString(); return next;
}
export function removeVehicleComponent(draft: VehicleModelDraft, id: string): VehicleModelDraft {
  const next = structuredClone(draft); const removed = new Set([id]); let changed = true;
  while (changed) { changed = false; for (const component of next.components) if (component.parentId && removed.has(component.parentId) && !removed.has(component.id)) { removed.add(component.id); changed = true; } }
  next.components = next.components.filter((component) => !removed.has(component.id)); next.constraints = next.constraints.filter((constraint) => constraint.componentIds.every((componentId) => !removed.has(componentId))); next.updatedAt = new Date().toISOString(); return next;
}
export function setVehicleComponentParent(draft: VehicleModelDraft, id: string, parentId: string | null): VehicleModelDraft {
  if (!canSetVehicleComponentParent(draft, id, parentId)) return draft;
  return updateVehicleComponent(draft, id, (component) => { component.parentId = parentId; });
}
export function addVehicleConstraint(draft: VehicleModelDraft, constraint: Omit<VehicleConstraintDraft, "id">): VehicleModelDraft {
  const next = structuredClone(draft); next.constraints.push({ ...constraint, id: uuid() }); next.updatedAt = new Date().toISOString(); return next;
}
export function updateVehicleConstraint(draft: VehicleModelDraft, id: string, updater: (constraint: VehicleConstraintDraft) => void): VehicleModelDraft {
  const next = structuredClone(draft); const constraint = next.constraints.find((candidate) => candidate.id === id); if (constraint) updater(constraint); next.updatedAt = new Date().toISOString(); return next;
}
export function removeVehicleConstraint(draft: VehicleModelDraft, id: string): VehicleModelDraft {
  const next = structuredClone(draft); next.constraints = next.constraints.filter((constraint) => constraint.id !== id); next.updatedAt = new Date().toISOString(); return next;
}
export function duplicateVehicleComponent(draft: VehicleModelDraft, id: string): VehicleModelDraft {
  const original = draft.components.find((component) => component.id === id); if (!original) return draft;
  const next = structuredClone(draft); const copy = structuredClone(original); copy.id = uuid(); copy.name = `${original.name} copy`; copy.transform.positionM.x += .04; copy.locked = false; copy.source = "manual"; next.components.push(copy); next.updatedAt = new Date().toISOString(); return next;
}
export function mirrorVehicleComponent(draft: VehicleModelDraft, id: string, axis: "x" | "z" = "x"): VehicleModelDraft {
  const original = draft.components.find((component) => component.id === id); if (!original) return draft;
  const next = duplicateVehicleComponent(draft, id); const copy = next.components.at(-1)!; copy.name = `${original.name} mirror`; copy.transform.positionM[axis] = -original.transform.positionM[axis]; copy.transform.rotationDeg.y = -original.transform.rotationDeg.y;
  next.constraints.push({ id: uuid(), type: "mirror", componentIds: [id, copy.id], axis, value: 0, enabled: true }); return next;
}
export function radialArrayVehicleComponent(draft: VehicleModelDraft, id: string, count: 4 | 6 | 8): VehicleModelDraft {
  const original = draft.components.find((component) => component.id === id); if (!original) return draft;
  // Keep the original component identity as the first array member. Other
  // constraints, child parts and revision history may already refer to it;
  // replacing every member with a fresh id would silently sever that assembly
  // contract and make the draft impossible to persist.
  const next = structuredClone(draft);
  const radius = Math.max(.08, Math.hypot(original.transform.positionM.x, original.transform.positionM.z)); const ids: string[] = [];
  const originalIndex = next.components.findIndex((component) => component.id === id);
  for (let index = 0; index < count; index += 1) {
    const copy = structuredClone(original);
    copy.id = index === 0 ? original.id : uuid();
    copy.name = `${original.name.replace(/\s+\d+$/u, "")} ${index + 1}`;
    const angle = index * 360 / count;
    const rad = angle * Math.PI / 180;
    copy.transform.positionM.x = Math.cos(rad) * radius;
    copy.transform.positionM.z = Math.sin(rad) * radius;
    copy.transform.rotationDeg.y = angle;
    if (index === 0) next.components[originalIndex] = copy;
    else next.components.push(copy);
    ids.push(copy.id);
  }
  next.constraints.push({ id: uuid(), type: "radial-array", componentIds: ids, axis: "y", value: count, enabled: true }); next.updatedAt = new Date().toISOString(); return next;
}
