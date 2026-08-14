import type {
  VehicleComponentDraft,
  VehicleModelDraft,
  VehiclePackTargetEdition,
  VehicleVector3,
} from "./model";
import {
  getVehicleComponentMassProperties,
  MAX_VEHICLE_COMPONENTS,
  MAX_PARAMETER_FAMILIES,
  MAX_VEHICLE_SENSORS,
  validateVehicleModel,
} from "./model";

export const VEHICLE_PACK_DRAFT_KIND = "dronedream-vehicle-pack-draft-envelope" as const;
export const VEHICLE_PACK_DRAFT_VERSION = "2.0.0" as const;
const MAX_ARTIFACT_UTF8_BYTES = 1_048_576;

export interface VehiclePackDraftArtifact {
  path: string;
  mediaType: "application/json" | "model/sdf+xml";
  encoding: "utf-8";
  content: string;
  sha256: string;
}

export interface VehiclePackDraftPayload {
  schemaVersion: 2;
  kind: typeof VEHICLE_PACK_DRAFT_KIND;
  transportVersion: typeof VEHICLE_PACK_DRAFT_VERSION;
  sourceEdition: "universal";
  packId: string;
  packVersion: string;
  model: VehicleModelDraft;
  targetEditions: VehiclePackTargetEdition[];
  artifacts: VehiclePackDraftArtifact[];
  compatibility: {
    autopilotFamily: string;
    controllerModel: string;
    firmwareVersion: string;
    simulationGeometryGenerated: true;
    simulationExecutionReady: false;
    hardwareAdapterValidated: false;
  };
  authority: {
    draftOnly: true;
    signed: false;
    validated: false;
    frontendIsAuthority: false;
    grantsSimulationExecution: false;
    grantsHardwareAuthority: false;
  };
}

export interface VehiclePackDraftEnvelope {
  payload: VehiclePackDraftPayload;
  integrity: {
    canonicalization: "dronedream-sorted-json-v1";
    payloadSha256: string;
  };
}

export interface VehiclePackDraftReceiverInspection {
  inspectionVersion: 1;
  kind: "dronedream-vehicle-pack-draft-receiver-inspection";
  targetEdition: VehiclePackTargetEdition;
  packId: string;
  packVersion: string;
  payloadSha256: string;
  decision: "verified-draft-only";
  receiverInspectionIsAuthority: false;
  promotionAllowed: false;
  grantsSimulationExecution: false;
  grantsHardwareAuthority: false;
  requiredNextGate: "edition-compatibility-and-signed-validation";
}

export class VehiclePackDraftError extends Error {}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, sorted(child)]),
    );
  }
  return value;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(sorted(value));
}

export async function sha256Text(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function safeId(name: string): string {
  const normalized = name
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 56);
  return normalized || "custom-vehicle";
}

function componentInertia(component: VehicleComponentDraft) {
  const mass = getVehicleComponentMassProperties(component).massKg;
  const scaled = scaledComponentGeometry(component);
  // Vehicle Studio uses X/right, Y/up, Z/forward. SDF uses X/right,
  // Y/forward, Z/up, so keep the engineering axes mapped consistently.
  const x = scaled.size.x;
  const y = scaled.size.z;
  const z = scaled.size.y;
  if (component.geometry.primitive === "sphere") {
    const moment = 2 * mass * scaled.radius ** 2 / 5;
    return { ixx: moment, iyy: moment, izz: moment };
  }
  if (component.geometry.primitive === "cone") {
    const axial = 3 * mass * scaled.radius ** 2 / 10;
    const transverse = 3 * mass * scaled.radius ** 2 / 20 + 3 * mass * scaled.length ** 2 / 80;
    // Primitive length is aligned to Vehicle Studio Y / SDF Z.
    return { ixx: transverse, iyy: transverse, izz: axial };
  }
  if (["cylinder", "capsule"].includes(component.geometry.primitive)) {
    const axial = mass * scaled.radius ** 2 / 2;
    const transverse = mass * (3 * scaled.radius ** 2 + scaled.length ** 2) / 12;
    // Primitive length is aligned to Vehicle Studio Y / SDF Z.
    return { ixx: transverse, iyy: transverse, izz: axial };
  }
  return {
    ixx: mass * (y ** 2 + z ** 2) / 12,
    iyy: mass * (x ** 2 + z ** 2) / 12,
    izz: mass * (x ** 2 + y ** 2) / 12,
  };
}

function scaledComponentGeometry(component: VehicleComponentDraft) {
  const scale = component.transform.scale;
  return {
    size: {
      x: Math.abs(component.geometry.sizeM.x * scale.x),
      y: Math.abs(component.geometry.sizeM.y * scale.y),
      z: Math.abs(component.geometry.sizeM.z * scale.z),
    },
    radius: Math.abs(component.geometry.radiusM * Math.max(scale.x, scale.z)),
    length: Math.abs(component.geometry.lengthM * scale.y),
  };
}

function number(value: number): string {
  return Number(value.toFixed(8)).toString();
}

function radians(value: number): string {
  return number(value * Math.PI / 180);
}

function pose(component: VehicleComponentDraft): string {
  const position = component.transform.positionM;
  const rotation = component.transform.rotationDeg;
  return `${number(position.x)} ${number(position.z)} ${number(position.y)} ${radians(rotation.x)} ${radians(rotation.z)} ${radians(rotation.y)}`;
}

function componentGeometry(component: VehicleComponentDraft): string {
  const { primitive, meshUri } = component.geometry;
  if (meshUri.trim()) {
    return `<mesh><uri>${escapeXml(meshUri.trim())}</uri><scale>${number(component.transform.scale.x)} ${number(component.transform.scale.z)} ${number(component.transform.scale.y)}</scale></mesh>`;
  }
  const scaled = scaledComponentGeometry(component);
  if (primitive === "sphere") return `<sphere><radius>${number(scaled.radius)}</radius></sphere>`;
  if (primitive === "capsule") {
    return `<capsule><radius>${number(scaled.radius)}</radius><length>${number(scaled.length)}</length></capsule>`;
  }
  if (primitive === "cone") {
    return `<cone><radius>${number(scaled.radius)}</radius><length>${number(scaled.length)}</length></cone>`;
  }
  if (primitive === "cylinder") {
    return `<cylinder><radius>${number(scaled.radius)}</radius><length>${number(scaled.length)}</length></cylinder>`;
  }
  return `<box><size>${number(scaled.size.x)} ${number(scaled.size.z)} ${number(scaled.size.y)}</size></box>`;
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function colorRgba(hex: string, opacity: number): string {
  const value = Number.parseInt(hex.slice(1), 16);
  return `${number(((value >> 16) & 255) / 255)} ${number(((value >> 8) & 255) / 255)} ${number((value & 255) / 255)} ${number(opacity)}`;
}

function componentLink(component: VehicleComponentDraft, linkName: string): string {
  const inertia = componentInertia(component);
  const mass = getVehicleComponentMassProperties(component).massKg;
  const geometry = componentGeometry(component);
  const color = colorRgba(component.material.baseColor, component.material.opacity);
  const collision = component.kind === "propeller" ? "" : `\n      <collision name="collision"><geometry>${geometry}</geometry></collision>`;
  return `    <link name="${linkName}">
      <pose>${pose(component)}</pose>
      <inertial><mass>${number(mass)}</mass><inertia><ixx>${number(inertia.ixx)}</ixx><iyy>${number(inertia.iyy)}</iyy><izz>${number(inertia.izz)}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>${collision}
      <visual name="visual"><geometry>${geometry}</geometry><material><ambient>${color}</ambient><diffuse>${color}</diffuse><specular>${number(component.material.metalness)} ${number(component.material.metalness)} ${number(component.material.metalness)} 1</specular></material></visual>
    </link>`;
}

export function generateGazeboSdf(draft: VehicleModelDraft): string {
  const components = draft.components;
  const names = new Map(components.map((component, index) => [component.id, `part_${String(index + 1).padStart(3, "0")}_${safeId(component.name)}`]));
  const links = components.map((component) => componentLink(component, names.get(component.id)!));
  const joints = components.map((component) => {
    const child = names.get(component.id)!;
    const parent = component.parentId ? names.get(component.parentId) : undefined;
    return `    <joint name="joint_${child}" type="fixed"><parent>${parent ?? "base_link"}</parent><child>${child}</child></joint>`;
  });
  return `<?xml version="1.0"?>
<sdf version="1.10">
  <model name="${safeId(draft.name)}">
    <static>false</static>
    <link name="base_link"><inertial><mass>0.001</mass><inertia><ixx>0.000001</ixx><iyy>0.000001</iyy><izz>0.000001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial></link>
${links.join("\n")}
${joints.join("\n")}
  </model>
</sdf>
`;
}

async function artifact(
  path: string,
  mediaType: VehiclePackDraftArtifact["mediaType"],
  content: string,
): Promise<VehiclePackDraftArtifact> {
  return { path, mediaType, encoding: "utf-8", content, sha256: await sha256Text(content) };
}

export async function buildVehiclePackDraft(
  draft: VehicleModelDraft,
): Promise<VehiclePackDraftEnvelope> {
  const model = structuredClone(draft);
  const issues = validateVehicleModel(model);
  if (issues.length > 0) {
    throw new VehiclePackDraftError(`Vehicle model has ${issues.length} validation issue(s)`);
  }
  const packId = `custom-${safeId(model.name)}-${model.draftId.slice(0, 8).toLowerCase()}`;
  const modelJson = `${JSON.stringify(model, null, 2)}\n`;
  const sdf = generateGazeboSdf(model);
  const artifacts = await Promise.all([
    artifact("model/vehicle-model.json", "application/json", modelJson),
    artifact("model/model.sdf", "model/sdf+xml", sdf),
  ]);
  const payload: VehiclePackDraftPayload = {
    schemaVersion: 2,
    kind: VEHICLE_PACK_DRAFT_KIND,
    transportVersion: VEHICLE_PACK_DRAFT_VERSION,
    sourceEdition: "universal",
    packId,
    packVersion: `0.1.${Math.max(0, model.revision - 1)}`,
    model,
    targetEditions: [...model.targetEditions].sort(),
    artifacts,
    compatibility: {
      autopilotFamily: model.autopilot.family,
      controllerModel: model.autopilot.controllerModel,
      firmwareVersion: model.autopilot.firmwareVersion,
      simulationGeometryGenerated: true,
      simulationExecutionReady: false,
      hardwareAdapterValidated: false,
    },
    authority: {
      draftOnly: true,
      signed: false,
      validated: false,
      frontendIsAuthority: false,
      grantsSimulationExecution: false,
      grantsHardwareAuthority: false,
    },
  };
  return {
    payload,
    integrity: {
      canonicalization: "dronedream-sorted-json-v1",
      payloadSha256: await sha256Text(canonicalJson(payload)),
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new VehiclePackDraftError(`${label} contains unknown or missing fields`);
  }
}

export function assertVehicleModelShape(value: unknown): asserts value is VehicleModelDraft {
  if (!isRecord(value)) throw new VehiclePackDraftError("Vehicle model is malformed");
  assertExactKeys(value, [
    "schemaVersion", "draftId", "revision", "name", "manufacturer", "vehicleClass",
    "body", "propulsion", "sensors", "autopilot", "controlTarget", "targetEditions",
    "components", "constraints", "designParameters", "notes", "createdAt", "updatedAt",
  ], "Vehicle model");
  if (
    value.schemaVersion !== 2
    || typeof value.draftId !== "string"
    || !Number.isInteger(value.revision)
    || Number(value.revision) < 1
    || typeof value.name !== "string"
    || typeof value.manufacturer !== "string"
    || !["multicopter-small", "multicopter-medium", "multicopter-research"].includes(String(value.vehicleClass))
    || typeof value.notes !== "string"
    || typeof value.createdAt !== "string"
    || typeof value.updatedAt !== "string"
  ) {
    throw new VehiclePackDraftError("Vehicle model identity is malformed");
  }
  if (!isRecord(value.body)) throw new VehiclePackDraftError("Vehicle body is malformed");
  const body = value.body;
  assertExactKeys(body, ["shape", "massKg", "lengthM", "widthM", "heightM"], "Vehicle body");
  if (
    !["box", "cylinder"].includes(String(body.shape))
    || ["massKg", "lengthM", "widthM", "heightM"].some((key) => typeof body[key] !== "number")
  ) throw new VehiclePackDraftError("Vehicle body is malformed");
  if (!isRecord(value.propulsion)) throw new VehiclePackDraftError("Vehicle propulsion is malformed");
  const propulsion = value.propulsion;
  assertExactKeys(propulsion, [
    "motorCount", "armLengthM", "propellerDiameterM", "maximumThrustPerMotorN",
    "batteryCells", "batteryCapacityMah",
  ], "Vehicle propulsion");
  if (
    ![4, 6, 8].includes(Number(propulsion.motorCount))
    || ["armLengthM", "propellerDiameterM", "maximumThrustPerMotorN", "batteryCells", "batteryCapacityMah"]
      .some((key) => typeof propulsion[key] !== "number")
  ) throw new VehiclePackDraftError("Vehicle propulsion is malformed");
  if (
    !Array.isArray(value.sensors)
    || value.sensors.length < 1
    || value.sensors.length > MAX_VEHICLE_SENSORS
  ) throw new VehiclePackDraftError("Vehicle sensors are malformed");
  const sensorIds = new Set<string>();
  for (const sensor of value.sensors) {
    if (!isRecord(sensor)) throw new VehiclePackDraftError("Vehicle sensor is malformed");
    assertExactKeys(sensor, ["id", "type", "model", "enabled"], "Vehicle sensor");
    if (
      typeof sensor.id !== "string"
      || !["imu", "gps", "barometer", "magnetometer", "camera", "lidar"].includes(String(sensor.type))
      || typeof sensor.model !== "string"
      || typeof sensor.enabled !== "boolean"
    ) throw new VehiclePackDraftError("Vehicle sensor is malformed");
    if (sensorIds.has(sensor.id)) {
      throw new VehiclePackDraftError("Vehicle sensor identities contain duplicates");
    }
    sensorIds.add(sensor.id);
  }
  if (!isRecord(value.autopilot)) throw new VehiclePackDraftError("Vehicle autopilot is malformed");
  assertExactKeys(value.autopilot, ["family", "controllerModel", "firmwareVersion"], "Vehicle autopilot");
  if (
    !["px4", "ardupilot", "crazyflie"].includes(String(value.autopilot.family))
    || typeof value.autopilot.controllerModel !== "string"
    || typeof value.autopilot.firmwareVersion !== "string"
  ) throw new VehiclePackDraftError("Vehicle autopilot is malformed");
  if (!isRecord(value.controlTarget)) throw new VehiclePackDraftError("Vehicle control target is malformed");
  assertExactKeys(value.controlTarget, ["primary", "parameterFamilies"], "Vehicle control target");
  if (
    !["position", "velocity", "attitude"].includes(String(value.controlTarget.primary))
    || !Array.isArray(value.controlTarget.parameterFamilies)
    || value.controlTarget.parameterFamilies.length > MAX_PARAMETER_FAMILIES
    || value.controlTarget.parameterFamilies.some((item) => typeof item !== "string")
    || new Set(value.controlTarget.parameterFamilies).size !== value.controlTarget.parameterFamilies.length
  ) throw new VehiclePackDraftError("Vehicle control target is malformed");
  if (
    !Array.isArray(value.targetEditions)
    || value.targetEditions.length < 1
    || value.targetEditions.some((item) => !["sim", "lab", "field"].includes(String(item)))
    || new Set(value.targetEditions).size !== value.targetEditions.length
  ) throw new VehiclePackDraftError("Vehicle target Editions are malformed");
  assertComponentShape(value.components);
  assertConstraintShape(value.constraints, new Set(value.components.map((component) => component.id)));
  if (!isRecord(value.designParameters)) throw new VehiclePackDraftError("Vehicle design parameters are malformed");
  assertExactKeys(value.designParameters, ["units", "gridM", "symmetry"], "Vehicle design parameters");
  if (
    value.designParameters.units !== "metric"
    || typeof value.designParameters.gridM !== "number"
    || !Number.isFinite(value.designParameters.gridM)
    || value.designParameters.gridM <= 0
    || !["none", "x", "z"].includes(String(value.designParameters.symmetry))
  ) throw new VehiclePackDraftError("Vehicle design parameters are malformed");
}

function assertVector(value: unknown, label: string): asserts value is VehicleVector3 {
  if (!isRecord(value)) throw new VehiclePackDraftError(`${label} is malformed`);
  assertExactKeys(value, ["x", "y", "z"], label);
  if ([value.x, value.y, value.z].some((item) => typeof item !== "number" || !Number.isFinite(item))) {
    throw new VehiclePackDraftError(`${label} is malformed`);
  }
}

function assertComponentShape(value: unknown): asserts value is VehicleComponentDraft[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_VEHICLE_COMPONENTS) {
    throw new VehiclePackDraftError("Vehicle components are malformed");
  }
  const ids = new Set<string>();
  const parentIds: Array<string | null> = [];
  for (const component of value) {
    if (!isRecord(component)) throw new VehiclePackDraftError("Vehicle component is malformed");
    assertExactKeys(component, ["id", "name", "kind", "parentId", "geometry", "transform", "material", "mass", "visible", "locked", "source", "tags"], "Vehicle component");
    if (
      typeof component.id !== "string" || !component.id || ids.has(component.id)
      || typeof component.name !== "string" || !component.name
      || !["fuselage", "frame", "arm", "motor", "propeller", "landing-gear", "battery", "flight-controller", "sensor", "payload", "camera-gimbal", "custom"].includes(String(component.kind))
      || !(component.parentId === null || typeof component.parentId === "string")
      || typeof component.visible !== "boolean" || typeof component.locked !== "boolean"
      || !["manual", "template", "ai"].includes(String(component.source))
      || !Array.isArray(component.tags) || component.tags.some((tag) => typeof tag !== "string")
    ) throw new VehiclePackDraftError("Vehicle component identity is malformed");
    ids.add(component.id); parentIds.push(component.parentId as string | null);
    if (!isRecord(component.geometry)) throw new VehiclePackDraftError("Vehicle component geometry is malformed");
    assertExactKeys(component.geometry, ["primitive", "sizeM", "radiusM", "lengthM", "meshUri"], "Vehicle component geometry");
    assertVector(component.geometry.sizeM, "Vehicle component size");
    if (
      !["box", "rounded-box", "cylinder", "sphere", "capsule", "cone"].includes(String(component.geometry.primitive))
      || typeof component.geometry.radiusM !== "number" || component.geometry.radiusM <= 0
      || typeof component.geometry.lengthM !== "number" || component.geometry.lengthM <= 0
      || typeof component.geometry.meshUri !== "string"
      || Object.values(component.geometry.sizeM).some((item) => item <= 0)
    ) throw new VehiclePackDraftError("Vehicle component geometry is malformed");
    if (!isRecord(component.transform)) throw new VehiclePackDraftError("Vehicle component transform is malformed");
    assertExactKeys(component.transform, ["positionM", "rotationDeg", "scale"], "Vehicle component transform");
    assertVector(component.transform.positionM, "Vehicle component position");
    assertVector(component.transform.rotationDeg, "Vehicle component rotation");
    assertVector(component.transform.scale, "Vehicle component scale");
    if (Object.values(component.transform.scale).some((item) => item <= 0)) throw new VehiclePackDraftError("Vehicle component scale is malformed");
    if (!isRecord(component.material)) throw new VehiclePackDraftError("Vehicle component material is malformed");
    assertExactKeys(component.material, ["baseColor", "metalness", "roughness", "opacity"], "Vehicle component material");
    if (
      typeof component.material.baseColor !== "string" || !/^#[0-9a-f]{6}$/i.test(component.material.baseColor)
      || [component.material.metalness, component.material.roughness, component.material.opacity].some((item) => typeof item !== "number" || item < 0 || item > 1)
    ) throw new VehiclePackDraftError("Vehicle component material is malformed");
    if (!isRecord(component.mass)) throw new VehiclePackDraftError("Vehicle component mass is malformed");
    assertExactKeys(component.mass, ["mode", "massKg", "densityKgM3"], "Vehicle component mass");
    if (
      !["explicit", "density"].includes(String(component.mass.mode))
      || [component.mass.massKg, component.mass.densityKgM3].some((item) => typeof item !== "number" || !Number.isFinite(item) || item <= 0)
    ) throw new VehiclePackDraftError("Vehicle component mass is malformed");
  }
  if (parentIds.some((parentId) => parentId !== null && !ids.has(parentId))) {
    throw new VehiclePackDraftError("Vehicle component parent is missing");
  }
}

function assertConstraintShape(value: unknown, componentIds: Set<string>) {
  if (!Array.isArray(value)) throw new VehiclePackDraftError("Vehicle constraints are malformed");
  const ids = new Set<string>();
  for (const constraint of value) {
    if (!isRecord(constraint)) throw new VehiclePackDraftError("Vehicle constraint is malformed");
    assertExactKeys(constraint, ["id", "type", "componentIds", "axis", "value", "enabled"], "Vehicle constraint");
    if (
      typeof constraint.id !== "string" || !constraint.id || ids.has(constraint.id)
      || !["attach", "mirror", "radial-array", "clearance", "balance"].includes(String(constraint.type))
      || !Array.isArray(constraint.componentIds) || constraint.componentIds.some((id) => typeof id !== "string" || !componentIds.has(id))
      || !["x", "y", "z"].includes(String(constraint.axis))
      || typeof constraint.value !== "number" || !Number.isFinite(constraint.value)
      || typeof constraint.enabled !== "boolean"
    ) throw new VehiclePackDraftError("Vehicle constraint is malformed");
    ids.add(constraint.id);
  }
}

export async function verifyVehiclePackDraft(
  value: unknown,
): Promise<VehiclePackDraftEnvelope> {
  if (!isRecord(value) || !isRecord(value.payload) || !isRecord(value.integrity)) {
    throw new VehiclePackDraftError("Vehicle Pack draft envelope is malformed");
  }
  assertExactKeys(value, ["payload", "integrity"], "Vehicle Pack envelope");
  assertExactKeys(value.payload, [
    "schemaVersion", "kind", "transportVersion", "sourceEdition", "packId",
    "packVersion", "model", "targetEditions", "artifacts", "compatibility", "authority",
  ], "Vehicle Pack payload");
  assertExactKeys(value.integrity, ["canonicalization", "payloadSha256"], "Vehicle Pack integrity");
  const payload = value.payload as unknown as VehiclePackDraftPayload;
  const integrity = value.integrity as unknown as VehiclePackDraftEnvelope["integrity"];
  if (
    payload.schemaVersion !== 2
    || payload.kind !== VEHICLE_PACK_DRAFT_KIND
    || payload.transportVersion !== VEHICLE_PACK_DRAFT_VERSION
    || payload.sourceEdition !== "universal"
  ) {
    throw new VehiclePackDraftError("Vehicle Pack draft identity is unsupported");
  }
  assertVehicleModelShape(payload.model);
  const expectedPackId = `custom-${safeId(payload.model.name)}-${payload.model.draftId.slice(0, 8).toLowerCase()}`;
  const expectedPackVersion = `0.1.${Math.max(0, payload.model.revision - 1)}`;
  if (
    payload.packId !== expectedPackId
    || payload.packVersion !== expectedPackVersion
  ) throw new VehiclePackDraftError("Vehicle Pack draft name or version is unsupported");
  if (
    !Array.isArray(payload.targetEditions)
    || payload.targetEditions.join("|") !== [...payload.model.targetEditions].sort().join("|")
  ) throw new VehiclePackDraftError("Vehicle Pack target Editions drifted from the model");
  if (!isRecord(payload.compatibility)) {
    throw new VehiclePackDraftError("Vehicle Pack compatibility is malformed");
  }
  assertExactKeys(payload.compatibility, [
    "autopilotFamily", "controllerModel", "firmwareVersion",
    "simulationGeometryGenerated", "simulationExecutionReady", "hardwareAdapterValidated",
  ], "Vehicle Pack compatibility");
  if (
    payload.compatibility.autopilotFamily !== payload.model.autopilot.family
    || payload.compatibility.controllerModel !== payload.model.autopilot.controllerModel
    || payload.compatibility.firmwareVersion !== payload.model.autopilot.firmwareVersion
    || payload.compatibility.simulationGeometryGenerated !== true
    || payload.compatibility.simulationExecutionReady !== false
    || payload.compatibility.hardwareAdapterValidated !== false
  ) throw new VehiclePackDraftError("Vehicle Pack compatibility drifted from the model");
  if (
    !isRecord(payload.authority)
    || payload.authority.draftOnly !== true
    || payload.authority.signed !== false
    || payload.authority.validated !== false
    || payload.authority.frontendIsAuthority !== false
    || payload.authority.grantsSimulationExecution !== false
    || payload.authority.grantsHardwareAuthority !== false
  ) {
    throw new VehiclePackDraftError("Vehicle Pack authority boundary is invalid");
  }
  assertExactKeys(payload.authority, [
    "draftOnly", "signed", "validated", "frontendIsAuthority",
    "grantsSimulationExecution", "grantsHardwareAuthority",
  ], "Vehicle Pack authority");
  if (!Array.isArray(payload.artifacts) || payload.artifacts.length !== 2) {
    throw new VehiclePackDraftError("Vehicle Pack draft artifacts are incomplete");
  }
  const expectedArtifacts = new Map([
    ["model/vehicle-model.json", "application/json"],
    ["model/model.sdf", "model/sdf+xml"],
  ]);
  const verifiedArtifacts = new Map<string, string>();
  for (const item of payload.artifacts) {
    if (!isRecord(item)) throw new VehiclePackDraftError("Vehicle Pack artifact is malformed");
    assertExactKeys(item, ["path", "mediaType", "encoding", "content", "sha256"], "Vehicle Pack artifact");
    if (
      expectedArtifacts.get(item.path) !== item.mediaType
      || item.encoding !== "utf-8"
      || typeof item.content !== "string"
      || new TextEncoder().encode(item.content).byteLength > MAX_ARTIFACT_UTF8_BYTES
      || !/^[0-9a-f]{64}$/.test(item.sha256)
    ) throw new VehiclePackDraftError("Vehicle Pack artifact identity is invalid");
    expectedArtifacts.delete(item.path);
    verifiedArtifacts.set(item.path, item.content);
    if (await sha256Text(item.content) !== item.sha256) {
      throw new VehiclePackDraftError(`Vehicle Pack artifact hash mismatch: ${item.path}`);
    }
  }
  if (expectedArtifacts.size !== 0) throw new VehiclePackDraftError("Vehicle Pack artifacts are incomplete");
  const expectedModelJson = `${JSON.stringify(payload.model, null, 2)}\n`;
  const expectedSdf = generateGazeboSdf(payload.model);
  if (
    verifiedArtifacts.get("model/vehicle-model.json") !== expectedModelJson
    || verifiedArtifacts.get("model/model.sdf") !== expectedSdf
  ) {
    throw new VehiclePackDraftError("Vehicle Pack artifacts drifted from the declared model");
  }
  const expected = await sha256Text(canonicalJson(payload));
  if (
    integrity.canonicalization !== "dronedream-sorted-json-v1"
    || integrity.payloadSha256 !== expected
  ) {
    throw new VehiclePackDraftError("Vehicle Pack payload hash mismatch");
  }
  if (validateVehicleModel(payload.model).length > 0) {
    throw new VehiclePackDraftError("Vehicle Pack contains an invalid vehicle model");
  }
  return { payload, integrity };
}

export async function inspectVehiclePackDraftForEdition(
  value: unknown,
  targetEdition: VehiclePackTargetEdition,
): Promise<VehiclePackDraftReceiverInspection> {
  const envelope = await verifyVehiclePackDraft(value);
  if (!envelope.payload.targetEditions.includes(targetEdition)) {
    throw new VehiclePackDraftError(
      `Vehicle Pack draft is not addressed to DroneDream · ${targetEdition.toUpperCase()}`,
    );
  }
  return {
    inspectionVersion: 1,
    kind: "dronedream-vehicle-pack-draft-receiver-inspection",
    targetEdition,
    packId: envelope.payload.packId,
    packVersion: envelope.payload.packVersion,
    payloadSha256: envelope.integrity.payloadSha256,
    decision: "verified-draft-only",
    receiverInspectionIsAuthority: false,
    promotionAllowed: false,
    grantsSimulationExecution: false,
    grantsHardwareAuthority: false,
    requiredNextGate: "edition-compatibility-and-signed-validation",
  };
}
