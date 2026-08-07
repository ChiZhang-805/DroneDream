export const VEHICLE_MODEL_SCHEMA_VERSION = 1 as const;
export const MAX_VEHICLE_SENSORS = 32;
export const MAX_PARAMETER_FAMILIES = 64;
export const VEHICLE_MODEL_LIMITS = Object.freeze({
  massKg: 1_000,
  bodyDimensionM: 50,
  armLengthM: 25,
  propellerDiameterM: 10,
  maximumThrustPerMotorN: 100_000,
  batteryCapacityMah: 1_000_000,
});

export type VehicleClass =
  | "multicopter-small"
  | "multicopter-medium"
  | "multicopter-research";
export type AutopilotFamily = "px4" | "ardupilot" | "crazyflie";
export type VehiclePackTargetEdition = "sim" | "lab" | "field";
export type BodyShape = "box" | "cylinder";

export interface VehicleSensorDraft {
  id: string;
  type: "imu" | "gps" | "barometer" | "magnetometer" | "camera" | "lidar";
  model: string;
  enabled: boolean;
}

export interface VehicleModelDraft {
  schemaVersion: typeof VEHICLE_MODEL_SCHEMA_VERSION;
  draftId: string;
  revision: number;
  name: string;
  manufacturer: string;
  vehicleClass: VehicleClass;
  body: {
    shape: BodyShape;
    massKg: number;
    lengthM: number;
    widthM: number;
    heightM: number;
  };
  propulsion: {
    motorCount: 4 | 6 | 8;
    armLengthM: number;
    propellerDiameterM: number;
    maximumThrustPerMotorN: number;
    batteryCells: number;
    batteryCapacityMah: number;
  };
  sensors: VehicleSensorDraft[];
  autopilot: {
    family: AutopilotFamily;
    controllerModel: string;
    firmwareVersion: string;
  };
  controlTarget: {
    primary: "position" | "velocity" | "attitude";
    parameterFamilies: string[];
  };
  targetEditions: VehiclePackTargetEdition[];
  notes: string;
  createdAt: string;
  updatedAt: string;
}

export interface VehicleModelValidationIssue {
  field: string;
  code: string;
  message: string;
}

function finitePositive(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function finitePositiveAtMost(value: number, maximum: number): boolean {
  return finitePositive(value) && value <= maximum;
}

export function validateVehicleModel(
  draft: VehicleModelDraft,
): VehicleModelValidationIssue[] {
  const issues: VehicleModelValidationIssue[] = [];
  const requireText = (field: string, value: string, maximum: number) => {
    const normalized = value.trim();
    if (!normalized) issues.push({ field, code: "required", message: "Required" });
    else if (normalized.length > maximum) {
      issues.push({ field, code: "too-long", message: `Maximum ${maximum} characters` });
    }
  };
  const requirePositive = (field: string, value: number) => {
    if (!finitePositive(value)) {
      issues.push({ field, code: "positive-number", message: "Must be greater than zero" });
    }
  };
  const requireBoundedPositive = (field: string, value: number, maximum: number) => {
    if (!finitePositiveAtMost(value, maximum)) {
      issues.push({
        field,
        code: "bounded-positive-number",
        message: `Must be greater than zero and no more than ${maximum}`,
      });
    }
  };

  requireText("name", draft.name, 96);
  requireText("manufacturer", draft.manufacturer, 96);
  if (draft.schemaVersion !== VEHICLE_MODEL_SCHEMA_VERSION) {
    issues.push({ field: "schemaVersion", code: "unsupported-schema", message: "Unsupported model schema" });
  }
  if (!Number.isInteger(draft.revision) || draft.revision < 1) {
    issues.push({ field: "revision", code: "invalid-revision", message: "Revision must be a positive integer" });
  }
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(draft.draftId)) {
    issues.push({ field: "draftId", code: "invalid-draft-id", message: "Draft identity is invalid" });
  }
  requireText("autopilot.controllerModel", draft.autopilot.controllerModel, 96);
  requireText("autopilot.firmwareVersion", draft.autopilot.firmwareVersion, 64);
  requireBoundedPositive("body.massKg", draft.body.massKg, VEHICLE_MODEL_LIMITS.massKg);
  requireBoundedPositive("body.lengthM", draft.body.lengthM, VEHICLE_MODEL_LIMITS.bodyDimensionM);
  requireBoundedPositive("body.widthM", draft.body.widthM, VEHICLE_MODEL_LIMITS.bodyDimensionM);
  requireBoundedPositive("body.heightM", draft.body.heightM, VEHICLE_MODEL_LIMITS.bodyDimensionM);
  requireBoundedPositive("propulsion.armLengthM", draft.propulsion.armLengthM, VEHICLE_MODEL_LIMITS.armLengthM);
  requireBoundedPositive("propulsion.propellerDiameterM", draft.propulsion.propellerDiameterM, VEHICLE_MODEL_LIMITS.propellerDiameterM);
  requireBoundedPositive(
    "propulsion.maximumThrustPerMotorN",
    draft.propulsion.maximumThrustPerMotorN,
    VEHICLE_MODEL_LIMITS.maximumThrustPerMotorN,
  );
  requirePositive("propulsion.batteryCells", draft.propulsion.batteryCells);
  requireBoundedPositive(
    "propulsion.batteryCapacityMah",
    draft.propulsion.batteryCapacityMah,
    VEHICLE_MODEL_LIMITS.batteryCapacityMah,
  );
  if (!Number.isInteger(draft.propulsion.batteryCells) || draft.propulsion.batteryCells > 16) {
    issues.push({ field: "propulsion.batteryCells", code: "invalid-cell-count", message: "Battery cells must be an integer from 1 to 16" });
  }
  if (draft.notes.length > 4096) {
    issues.push({ field: "notes", code: "too-long", message: "Maximum 4096 characters" });
  }
  if (draft.controlTarget.parameterFamilies.some(
    (family) => !family.trim() || family !== family.trim() || family.length > 64,
  )) {
    issues.push({ field: "controlTarget.parameterFamilies", code: "invalid-family", message: "Parameter families must contain 1 to 64 characters" });
  }
  const normalizedFamilies = draft.controlTarget.parameterFamilies
    .map((family) => family.trim().toUpperCase());
  if (
    draft.controlTarget.parameterFamilies.length > MAX_PARAMETER_FAMILIES
    || new Set(normalizedFamilies).size !== normalizedFamilies.length
  ) {
    issues.push({ field: "controlTarget.parameterFamilies", code: "invalid-family-set", message: `Use no more than ${MAX_PARAMETER_FAMILIES} unique parameter families` });
  }
  if (draft.sensors.length < 1 || draft.sensors.length > MAX_VEHICLE_SENSORS) {
    issues.push({ field: "sensors", code: "invalid-sensor-count", message: `Use 1 to ${MAX_VEHICLE_SENSORS} sensors` });
  }
  if (
    new Set(draft.sensors.map((sensor) => sensor.id)).size !== draft.sensors.length
  ) {
    issues.push({ field: "sensors", code: "duplicate-sensor", message: "Sensor identities must be unique" });
  }
  for (const sensor of draft.sensors) {
    requireText(`sensors.${sensor.id}.id`, sensor.id, 128);
    requireText(`sensors.${sensor.id}.model`, sensor.model, 96);
  }
  for (const [field, timestamp] of [["createdAt", draft.createdAt], ["updatedAt", draft.updatedAt]] as const) {
    if (!Number.isFinite(Date.parse(timestamp))) {
      issues.push({ field, code: "invalid-timestamp", message: "Timestamp must use a valid ISO date-time" });
    }
  }

  const totalThrust = draft.propulsion.motorCount
    * draft.propulsion.maximumThrustPerMotorN;
  const weight = draft.body.massKg * 9.80665;
  if (finitePositive(totalThrust) && finitePositive(weight) && totalThrust / weight < 1.6) {
    issues.push({
      field: "propulsion.maximumThrustPerMotorN",
      code: "insufficient-thrust-margin",
      message: "Total thrust-to-weight ratio must be at least 1.6 for this draft contract",
    });
  }
  if (draft.sensors.filter((sensor) => sensor.enabled && sensor.type === "imu").length === 0) {
    issues.push({ field: "sensors", code: "imu-required", message: "At least one IMU is required" });
  }
  if (
    draft.targetEditions.length === 0
    || draft.targetEditions.length > 3
    || new Set(draft.targetEditions).size !== draft.targetEditions.length
  ) {
    issues.push({
      field: "targetEditions",
      code: "target-required",
      message: "Select at least one target Edition",
    });
  }
  if (draft.targetEditions.includes("field") && draft.autopilot.family === "crazyflie") {
    issues.push({
      field: "targetEditions",
      code: "field-adapter-unavailable",
      message: "The Crazyflie Field adapter is planned and cannot be exported as compatible",
    });
  }
  return issues;
}

export function createVehicleModelDraft(now = new Date()): VehicleModelDraft {
  const timestamp = now.toISOString();
  return {
    schemaVersion: VEHICLE_MODEL_SCHEMA_VERSION,
    draftId: crypto.randomUUID(),
    revision: 1,
    name: "Custom quadrotor",
    manufacturer: "Custom",
    vehicleClass: "multicopter-medium",
    body: {
      shape: "box",
      massKg: 1.5,
      lengthM: 0.28,
      widthM: 0.22,
      heightM: 0.12,
    },
    propulsion: {
      motorCount: 4,
      armLengthM: 0.25,
      propellerDiameterM: 0.254,
      maximumThrustPerMotorN: 9,
      batteryCells: 4,
      batteryCapacityMah: 5000,
    },
    sensors: [
      { id: crypto.randomUUID(), type: "imu", model: "Generic IMU", enabled: true },
      { id: crypto.randomUUID(), type: "gps", model: "Generic GNSS", enabled: true },
      { id: crypto.randomUUID(), type: "barometer", model: "Generic barometer", enabled: true },
    ],
    autopilot: {
      family: "px4",
      controllerModel: "Pixhawk compatible",
      firmwareVersion: "v1.16.0",
    },
    controlTarget: {
      primary: "position",
      parameterFamilies: ["MPC_XY", "MPC_Z", "MC_ROLL", "MC_PITCH", "MC_YAW"],
    },
    targetEditions: ["sim", "lab"],
    notes: "",
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}
