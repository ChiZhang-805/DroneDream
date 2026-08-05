import {
  FIELD_CATALOG,
  type FieldValidationStatus,
} from "./catalog";

export const FIELD_HARDWARE_ACTIONS = [
  "parameter-write",
  "rollback-apply",
  "takeover",
  "emergency-stop",
  "arm",
  "flight",
] as const;

export type FieldHardwareAction = (typeof FIELD_HARDWARE_ACTIONS)[number];
export type FieldObservationState =
  | "offline"
  | "device-missing"
  | "unknown-device"
  | "firmware-drift"
  | "recognized-unvalidated";

export interface FieldQuorumObservation {
  vehiclePackReceipt: "missing" | "invalid" | "expired" | "verified";
  controllerMatch: "missing" | "mismatch" | "verified";
  firmwareMatch: "missing" | "drift" | "verified";
}

export interface FieldDeviceObservation {
  schemaVersion: 1;
  source: "fake-readonly";
  state: FieldObservationState;
  observedAt: string;
  deviceId: string | null;
  vehiclePackId: string | null;
  controller: string | null;
  firmwareVersion: string | null;
  validationTier: FieldValidationStatus | null;
  quorum: FieldQuorumObservation;
}

export type FieldSafetyBlocker =
  | "field.registry.zero-validated-packs"
  | "field.quorum.vehicle-pack-receipt-missing"
  | "field.quorum.controller-match-missing"
  | "field.quorum.firmware-match-missing"
  | "field.device.offline"
  | "field.device.missing"
  | "field.device.unknown"
  | "field.device.firmware-drift"
  | "field.device.pack-unvalidated";

export interface FieldSafetyDecision {
  frontendIsAuthority: false;
  observationGrantsAuthority: false;
  validatedPackCount: number;
  threeLayerQuorum: "missing" | "verified";
  readOnlyObservationAllowed: true;
  actions: Record<FieldHardwareAction, false>;
  blockers: FieldSafetyBlocker[];
}

export const FIELD_VALIDATED_PACK_COUNT = FIELD_CATALOG.vehiclePacks.filter(
  (pack) => pack.validationStatus === "validated",
).length;

function observationBlocker(state: FieldObservationState): FieldSafetyBlocker {
  const blockers: Record<FieldObservationState, FieldSafetyBlocker> = {
    offline: "field.device.offline",
    "device-missing": "field.device.missing",
    "unknown-device": "field.device.unknown",
    "firmware-drift": "field.device.firmware-drift",
    "recognized-unvalidated": "field.device.pack-unvalidated",
  };
  return blockers[state];
}

export function evaluateFieldSafety(
  observation: FieldDeviceObservation,
): FieldSafetyDecision {
  const blockers = new Set<FieldSafetyBlocker>([
    observationBlocker(observation.state),
  ]);

  if (FIELD_VALIDATED_PACK_COUNT === 0) {
    blockers.add("field.registry.zero-validated-packs");
  }
  if (observation.quorum.vehiclePackReceipt !== "verified") {
    blockers.add("field.quorum.vehicle-pack-receipt-missing");
  }
  if (observation.quorum.controllerMatch !== "verified") {
    blockers.add("field.quorum.controller-match-missing");
  }
  if (observation.quorum.firmwareMatch !== "verified") {
    blockers.add("field.quorum.firmware-match-missing");
  }

  const threeLayerQuorum = observation.quorum.vehiclePackReceipt === "verified"
    && observation.quorum.controllerMatch === "verified"
    && observation.quorum.firmwareMatch === "verified"
    ? "verified"
    : "missing";

  return {
    frontendIsAuthority: false,
    observationGrantsAuthority: false,
    validatedPackCount: FIELD_VALIDATED_PACK_COUNT,
    threeLayerQuorum,
    readOnlyObservationAllowed: true,
    actions: Object.fromEntries(
      FIELD_HARDWARE_ACTIONS.map((action) => [action, false]),
    ) as Record<FieldHardwareAction, false>,
    blockers: [...blockers].sort(),
  };
}

export const FIELD_OBSERVATION_FIXTURES: Record<
  FieldObservationState,
  FieldDeviceObservation
> = {
  offline: {
    schemaVersion: 1,
    source: "fake-readonly",
    state: "offline",
    observedAt: "2026-08-05T00:00:00Z",
    deviceId: null,
    vehiclePackId: null,
    controller: null,
    firmwareVersion: null,
    validationTier: null,
    quorum: {
      vehiclePackReceipt: "missing",
      controllerMatch: "missing",
      firmwareMatch: "missing",
    },
  },
  "device-missing": {
    schemaVersion: 1,
    source: "fake-readonly",
    state: "device-missing",
    observedAt: "2026-08-05T00:00:00Z",
    deviceId: null,
    vehiclePackId: null,
    controller: null,
    firmwareVersion: null,
    validationTier: null,
    quorum: {
      vehiclePackReceipt: "missing",
      controllerMatch: "missing",
      firmwareMatch: "missing",
    },
  },
  "unknown-device": {
    schemaVersion: 1,
    source: "fake-readonly",
    state: "unknown-device",
    observedAt: "2026-08-05T00:00:00Z",
    deviceId: "demo:unknown-controller",
    vehiclePackId: null,
    controller: "Unknown controller",
    firmwareVersion: "unknown",
    validationTier: null,
    quorum: {
      vehiclePackReceipt: "missing",
      controllerMatch: "mismatch",
      firmwareMatch: "missing",
    },
  },
  "firmware-drift": {
    schemaVersion: 1,
    source: "fake-readonly",
    state: "firmware-drift",
    observedAt: "2026-08-05T00:00:00Z",
    deviceId: "demo:pixhawk-6c",
    vehiclePackId: "holybro-s500-v2-pixhawk6c",
    controller: "Holybro Pixhawk 6C",
    firmwareVersion: "PX4 1.18.0-dev",
    validationTier: "contract-only",
    quorum: {
      vehiclePackReceipt: "missing",
      controllerMatch: "verified",
      firmwareMatch: "drift",
    },
  },
  "recognized-unvalidated": {
    schemaVersion: 1,
    source: "fake-readonly",
    state: "recognized-unvalidated",
    observedAt: "2026-08-05T00:00:00Z",
    deviceId: "demo:pixhawk-6c",
    vehiclePackId: "holybro-s500-v2-pixhawk6c",
    controller: "Holybro Pixhawk 6C",
    firmwareVersion: "PX4 1.16.0",
    validationTier: "contract-only",
    quorum: {
      vehiclePackReceipt: "missing",
      controllerMatch: "verified",
      firmwareMatch: "verified",
    },
  },
};
