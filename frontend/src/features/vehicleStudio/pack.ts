import type {
  VehicleModelDraft,
  VehiclePackTargetEdition,
} from "./model";
import {
  MAX_PARAMETER_FAMILIES,
  MAX_VEHICLE_SENSORS,
  validateVehicleModel,
} from "./model";

export const VEHICLE_PACK_DRAFT_KIND = "dronedream-vehicle-pack-draft-envelope" as const;
export const VEHICLE_PACK_DRAFT_VERSION = "1.0.0" as const;
const MAX_ARTIFACT_UTF8_BYTES = 1_048_576;

export interface VehiclePackDraftArtifact {
  path: string;
  mediaType: "application/json" | "model/sdf+xml";
  encoding: "utf-8";
  content: string;
  sha256: string;
}

export interface VehiclePackDraftPayload {
  schemaVersion: 1;
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

function bodyInertia(draft: VehicleModelDraft, mass: number) {
  if (draft.body.shape === "cylinder") {
    const radius = draft.body.widthM / 2;
    return {
      ixx: mass * (3 * radius ** 2 + draft.body.heightM ** 2) / 12,
      iyy: mass * (3 * radius ** 2 + draft.body.heightM ** 2) / 12,
      izz: mass * radius ** 2 / 2,
    };
  }
  return {
    ixx: mass * (draft.body.widthM ** 2 + draft.body.heightM ** 2) / 12,
    iyy: mass * (draft.body.lengthM ** 2 + draft.body.heightM ** 2) / 12,
    izz: mass * (draft.body.lengthM ** 2 + draft.body.widthM ** 2) / 12,
  };
}

export function generateGazeboSdf(draft: VehicleModelDraft): string {
  const rotorMass = Math.min(0.01, draft.body.massKg / (draft.propulsion.motorCount * 20));
  const baseMass = draft.body.massKg - rotorMass * draft.propulsion.motorCount;
  const inertia = bodyInertia(draft, baseMass);
  const geometry = draft.body.shape === "box"
    ? `<box><size>${draft.body.lengthM} ${draft.body.widthM} ${draft.body.heightM}</size></box>`
    : `<cylinder><radius>${draft.body.widthM / 2}</radius><length>${draft.body.heightM}</length></cylinder>`;
  const rotorLinks = Array.from({ length: draft.propulsion.motorCount }, (_, index) => {
    const angle = (Math.PI * 2 * index) / draft.propulsion.motorCount;
    const x = Math.cos(angle) * draft.propulsion.armLengthM;
    const y = Math.sin(angle) * draft.propulsion.armLengthM;
    return `    <link name="rotor_${index}"><pose>${x.toFixed(6)} ${y.toFixed(6)} 0 0 0 0</pose><inertial><mass>${rotorMass}</mass><inertia><ixx>0.00001</ixx><iyy>0.00001</iyy><izz>0.00002</izz></inertia></inertial><visual name="visual"><geometry><cylinder><radius>${(draft.propulsion.propellerDiameterM / 2).toFixed(6)}</radius><length>0.002</length></cylinder></geometry></visual></link>\n    <joint name="rotor_${index}_fixed" type="fixed"><parent>base_link</parent><child>rotor_${index}</child></joint>`;
  }).join("\n");
  return `<?xml version="1.0"?>\n<sdf version="1.10">\n  <model name="${safeId(draft.name)}">\n    <link name="base_link">\n      <inertial><mass>${baseMass}</mass><inertia><ixx>${inertia.ixx}</ixx><iyy>${inertia.iyy}</iyy><izz>${inertia.izz}</izz></inertia></inertial>\n      <collision name="collision"><geometry>${geometry}</geometry></collision>\n      <visual name="visual"><geometry>${geometry}</geometry></visual>\n    </link>\n${rotorLinks}\n  </model>\n</sdf>\n`;
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
    schemaVersion: 1,
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
    "notes", "createdAt", "updatedAt",
  ], "Vehicle model");
  if (
    value.schemaVersion !== 1
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
    payload.schemaVersion !== 1
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
