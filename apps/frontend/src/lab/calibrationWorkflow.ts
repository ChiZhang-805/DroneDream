import { validateEvidenceTree } from "./evidenceInput";

export const MAX_LAB_CALIBRATION_INPUT_BYTES = 256 * 1024;

const SHA256 = /^[a-f0-9]{64}$/;
const COMMIT = /^[a-f0-9]{40}$/;
const IDENTIFIER = /^[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,127}$/;
const FORBIDDEN_FIELD = /(api[-_]?key|authorization|cookie|email|header|password|secret|token)/i;

export type LabObjective = "tracking" | "stability" | "energy" | "robustness";
export type CalibrationPhaseStatus = "complete" | "ready" | "pending" | "blocked";

export interface CalibrationMetrics {
  trackingRmseM: number;
  maxErrorM: number;
  energyWh: number;
  overshootCount: number;
}

export interface LabCalibrationInput {
  fileName: string;
  jobId: string;
  cycleOrdinal: number;
  commonCoreCommit: string;
  editionManifestSha256: string;
  vehiclePackId: string;
  controllerIdentity: string;
  firmwareIdentity: string;
  simulationReceiptHash: string;
  realObservationReceiptHash: string;
  parameterCandidateHash: string;
  objectiveContractHash: string;
  constraintContractHash: string;
  holdoutContractHash: string;
  metricNormalizationReceiptHash: string;
  sourceKind: "historical-import" | "test-fixture";
  simulation: CalibrationMetrics;
  realObservation: CalibrationMetrics;
  authorityDecision: "deny";
  grantsHardwareAuthority: false;
}

export interface MetricGap {
  key: keyof CalibrationMetrics;
  simulation: number;
  real: number;
  absolute: number;
  percent: number;
  withinTolerance: boolean;
}

export interface CalibrationStage {
  id: string;
  status: CalibrationPhaseStatus;
}

export interface LabCalibrationAnalysis {
  objective: LabObjective;
  tolerancePercent: number;
  cycleBudget: number;
  gaps: MetricGap[];
  aggregateGapPercent: number;
  gapWithinTolerance: boolean;
  recommendations: string[];
  stages: CalibrationStage[];
  qualificationDecision: "deny";
  qualificationReason: "zero-validated-vehicle-packs" | "gap-outside-tolerance";
  nextAction: "revise-model-and-resimulate" | "await-independent-holdout";
  presentationOnly: true;
  grantsHardwareAuthority: false;
}

export class LabCalibrationInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LabCalibrationInputError";
  }
}

/** Reject arrays/scalars before interpreting receipt fields; not a trust decision. */
function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new LabCalibrationInputError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

/** Unknown fields are not silently retained in a calibration contract. */
function assertExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new LabCalibrationInputError(`${label} fields do not match the supported schema.`);
  }
}

/** Bound recursive work and reject credentials before interpreting imported data. */
function assertNoSensitiveFields(value: unknown): void {
  validateEvidenceTree(value, LabCalibrationInputError, FORBIDDEN_FIELD);
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new LabCalibrationInputError(`${label} must be a non-empty string.`);
  }
  return value.trim();
}

function identifierValue(value: unknown, label: string): string {
  const identifier = stringValue(value, label);
  if (!IDENTIFIER.test(identifier)) {
    throw new LabCalibrationInputError(`${label} is invalid.`);
  }
  return identifier;
}

/** Normalize content identifiers; matching digest syntax does not verify a receipt. */
function shaValue(value: unknown, label: string): string {
  const sha = stringValue(value, label).toLowerCase();
  if (!SHA256.test(sha)) {
    throw new LabCalibrationInputError(`${label} must be a lowercase SHA-256 value.`);
  }
  return sha;
}

function metricValue(value: unknown, label: string, integer = false): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new LabCalibrationInputError(`${label} must be a finite non-negative number.`);
  }
  if (integer && !Number.isSafeInteger(value)) {
    throw new LabCalibrationInputError(`${label} must be an integer.`);
  }
  // Percentages divide by at least 0.001 and multiply by 100. This is a
  // representability bound, not a claim about physically valid sensor ranges.
  if (value > Number.MAX_VALUE / 100_000) {
    throw new LabCalibrationInputError(`${label} exceeds the finite analysis range.`);
  }
  return value;
}

/** Retain metric units and reject invalid counters before percentage arithmetic. */
function parseMetrics(value: unknown, label: string): CalibrationMetrics {
  const metrics = objectValue(value, label);
  assertExactKeys(
    metrics,
    ["trackingRmseM", "maxErrorM", "energyWh", "overshootCount"],
    label,
  );
  return {
    trackingRmseM: metricValue(metrics.trackingRmseM, `${label} tracking RMSE`),
    maxErrorM: metricValue(metrics.maxErrorM, `${label} max error`),
    energyWh: metricValue(metrics.energyWh, `${label} energy`),
    overshootCount: metricValue(
      metrics.overshootCount,
      `${label} overshoot count`,
      true,
    ),
  };
}

/** Parse a bounded historical/test import; hashes remain claims, never flight permission. */
export function parseLabCalibrationInput(
  fileName: string,
  source: string,
): LabCalibrationInput {
  const bytes = new TextEncoder().encode(source).byteLength;
  if (bytes === 0) throw new LabCalibrationInputError("The calibration input is empty.");
  if (bytes > MAX_LAB_CALIBRATION_INPUT_BYTES) {
    throw new LabCalibrationInputError("The calibration input exceeds 256 KiB.");
  }

  let decoded: unknown;
  try {
    decoded = JSON.parse(source);
  } catch {
    throw new LabCalibrationInputError("The calibration input is not valid JSON.");
  }
  assertNoSensitiveFields(decoded);
  const receipt = objectValue(decoded, "Calibration input");
  assertExactKeys(
    receipt,
    [
      "schemaVersion",
      "kind",
      "editionId",
      "jobId",
      "cycleOrdinal",
      "source",
      "vehicle",
      "evidence",
      "simulation",
      "realObservation",
      "authority",
    ],
    "Calibration input",
  );
  if (
    receipt.schemaVersion !== 1
    || receipt.kind !== "dronedream-lab-calibration-input"
    || receipt.editionId !== "lab"
  ) {
    throw new LabCalibrationInputError("The calibration input identity is unsupported.");
  }

  const sourceBinding = objectValue(receipt.source, "Source binding");
  const vehicle = objectValue(receipt.vehicle, "Vehicle binding");
  const evidence = objectValue(receipt.evidence, "Evidence binding");
  const authority = objectValue(receipt.authority, "Authority binding");
  assertExactKeys(
    sourceBinding,
    ["kind", "commonCoreCommit", "editionManifestSha256"],
    "Source binding",
  );
  assertExactKeys(
    vehicle,
    ["vehiclePackId", "controllerIdentity", "firmwareIdentity"],
    "Vehicle binding",
  );
  assertExactKeys(
    evidence,
    [
      "simulationReceiptHash",
      "realObservationReceiptHash",
      "parameterCandidateHash",
      "objectiveContractHash",
      "constraintContractHash",
      "holdoutContractHash",
      "metricNormalizationReceiptHash",
    ],
    "Evidence binding",
  );
  assertExactKeys(authority, ["decision", "grantsHardwareAuthority"], "Authority binding");
  if (authority.decision !== "deny" || authority.grantsHardwareAuthority !== false) {
    throw new LabCalibrationInputError("Imported calibration evidence must not grant authority.");
  }
  const sourceKind = sourceBinding.kind;
  if (sourceKind !== "historical-import" && sourceKind !== "test-fixture") {
    throw new LabCalibrationInputError("Source kind must be historical-import or test-fixture.");
  }
  const commonCoreCommit = stringValue(
    sourceBinding.commonCoreCommit,
    "Common-core commit",
  ).toLowerCase();
  if (!COMMIT.test(commonCoreCommit)) {
    throw new LabCalibrationInputError("Common-core commit must be a full Git commit.");
  }
  const cycleOrdinal = metricValue(receipt.cycleOrdinal, "Cycle ordinal", true);
  if (cycleOrdinal < 1 || cycleOrdinal > 1000) {
    throw new LabCalibrationInputError("Cycle ordinal must be between 1 and 1000.");
  }

  return {
    fileName,
    jobId: identifierValue(receipt.jobId, "Job ID"),
    cycleOrdinal,
    commonCoreCommit,
    editionManifestSha256: shaValue(
      sourceBinding.editionManifestSha256,
      "Edition manifest hash",
    ),
    vehiclePackId: identifierValue(vehicle.vehiclePackId, "Vehicle Pack ID"),
    controllerIdentity: identifierValue(vehicle.controllerIdentity, "Controller identity"),
    firmwareIdentity: identifierValue(vehicle.firmwareIdentity, "Firmware identity"),
    simulationReceiptHash: shaValue(
      evidence.simulationReceiptHash,
      "Simulation receipt hash",
    ),
    realObservationReceiptHash: shaValue(
      evidence.realObservationReceiptHash,
      "Real observation receipt hash",
    ),
    parameterCandidateHash: shaValue(
      evidence.parameterCandidateHash,
      "Parameter candidate hash",
    ),
    objectiveContractHash: shaValue(
      evidence.objectiveContractHash,
      "Objective contract hash",
    ),
    constraintContractHash: shaValue(
      evidence.constraintContractHash,
      "Constraint contract hash",
    ),
    holdoutContractHash: shaValue(
      evidence.holdoutContractHash,
      "Holdout contract hash",
    ),
    metricNormalizationReceiptHash: shaValue(
      evidence.metricNormalizationReceiptHash,
      "Metric normalization receipt hash",
    ),
    sourceKind,
    simulation: parseMetrics(receipt.simulation, "Simulation metrics"),
    realObservation: parseMetrics(receipt.realObservation, "Real observation metrics"),
    authorityDecision: "deny",
    grantsHardwareAuthority: false,
  };
}

/** Round display values only after checking that intermediate arithmetic remained finite. */
function round(value: number): number {
  if (!Number.isFinite(value)) throw new LabCalibrationInputError("Metric analysis overflowed.");
  return Number(value.toFixed(3));
}

/** Compare supplied summaries locally, without running training, simulation or hardware. */
export function analyzeLabCalibration(
  input: LabCalibrationInput,
  objective: LabObjective,
  tolerancePercent: number,
  cycleBudget: number,
): LabCalibrationAnalysis {
  if (!["tracking", "stability", "energy", "robustness"].includes(objective)) {
    throw new LabCalibrationInputError("Calibration objective is unsupported.");
  }
  // Callers can mutate parsed objects. Validate again before computing a new result.
  const simulationMetrics = parseMetrics(input.simulation, "Simulation metrics");
  const realMetrics = parseMetrics(input.realObservation, "Real observation metrics");
  if (!Number.isFinite(tolerancePercent) || tolerancePercent < 1 || tolerancePercent > 100) {
    throw new LabCalibrationInputError("Gap tolerance must be between 1 and 100 percent.");
  }
  if (!Number.isInteger(cycleBudget) || cycleBudget < 1 || cycleBudget > 12) {
    throw new LabCalibrationInputError("Cycle budget must be between 1 and 12.");
  }
  const keys: (keyof CalibrationMetrics)[] = [
    "trackingRmseM",
    "maxErrorM",
    "energyWh",
    "overshootCount",
  ];
  const gaps = keys.map((key) => {
    const simulation = simulationMetrics[key];
    const real = realMetrics[key];
    const absolute = Math.abs(real - simulation);
    const denominator = Math.max(Math.abs(simulation), key === "overshootCount" ? 1 : 0.001);
    const percent = (absolute / denominator) * 100;
    return {
      key,
      simulation,
      real,
      absolute: round(absolute),
      percent: round(percent),
      withinTolerance: percent <= tolerancePercent,
    };
  });
  const aggregateGapPercent = round(
    gaps.reduce((total, gap) => total + gap.percent / gaps.length, 0),
  );
  const gapWithinTolerance = gaps.every((gap) => gap.withinTolerance);
  const recommendations: string[] = [];
  if (!gaps[0]?.withinTolerance || !gaps[1]?.withinTolerance) {
    recommendations.push("revise-aerodynamic-drag-and-sensor-noise");
  }
  if (!gaps[2]?.withinTolerance) {
    recommendations.push("revise-payload-battery-and-motor-efficiency");
  }
  if (!gaps[3]?.withinTolerance) {
    recommendations.push("revise-actuator-delay-and-controller-damping");
  }
  if (recommendations.length === 0) {
    recommendations.push("freeze-calibrated-model-for-independent-holdout");
  }

  return {
    objective,
    tolerancePercent,
    cycleBudget,
    gaps,
    aggregateGapPercent,
    gapWithinTolerance,
    recommendations,
    stages: [
      { id: "objective-and-constraints", status: "complete" },
      { id: "simulation-search", status: "complete" },
      { id: "controlled-real-observation", status: "complete" },
      { id: "sim-real-gap-analysis", status: "complete" },
      {
        id: "real-sim-model-calibration",
        status: gapWithinTolerance ? "complete" : "ready",
      },
      { id: "resimulation", status: gapWithinTolerance ? "complete" : "pending" },
      { id: "independent-holdout", status: gapWithinTolerance ? "ready" : "blocked" },
      { id: "qualification-and-evidence", status: "blocked" },
      { id: "field-handoff", status: "blocked" },
    ],
    qualificationDecision: "deny",
    qualificationReason: gapWithinTolerance
      ? "zero-validated-vehicle-packs"
      : "gap-outside-tolerance",
    nextAction: gapWithinTolerance
      ? "await-independent-holdout"
      : "revise-model-and-resimulate",
    presentationOnly: true,
    grantsHardwareAuthority: false,
  };
}

/** Recompute the draft's conclusions from current inputs; no imported allow state survives. */
export function buildLabCalibrationDraftReceipt(
  input: LabCalibrationInput,
  analysis: LabCalibrationAnalysis,
): Record<string, unknown> {
  analysis = analyzeLabCalibration(input, analysis.objective, analysis.tolerancePercent,
                                  analysis.cycleBudget);
  return {
    schemaVersion: 1,
    kind: "dronedream-lab-calibration-draft-receipt",
    editionId: "lab",
    trusted: false,
    jobId: input.jobId,
    cycleOrdinal: input.cycleOrdinal,
    source: {
      commonCoreCommit: input.commonCoreCommit,
      editionManifestSha256: input.editionManifestSha256,
      sourceKind: input.sourceKind,
    },
    vehicle: {
      vehiclePackId: input.vehiclePackId,
      controllerIdentity: input.controllerIdentity,
      firmwareIdentity: input.firmwareIdentity,
    },
    evidence: {
      simulationReceiptHash: input.simulationReceiptHash,
      realObservationReceiptHash: input.realObservationReceiptHash,
      parameterCandidateHash: input.parameterCandidateHash,
      objectiveContractHash: input.objectiveContractHash,
      constraintContractHash: input.constraintContractHash,
      holdoutContractHash: input.holdoutContractHash,
      metricNormalizationReceiptHash: input.metricNormalizationReceiptHash,
    },
    analysis: {
      objective: analysis.objective,
      tolerancePercent: analysis.tolerancePercent,
      cycleBudget: analysis.cycleBudget,
      aggregateGapPercent: analysis.aggregateGapPercent,
      gapWithinTolerance: analysis.gapWithinTolerance,
      gaps: analysis.gaps,
      recommendations: analysis.recommendations,
      nextAction: analysis.nextAction,
    },
    qualification: {
      decision: analysis.qualificationDecision,
      reason: analysis.qualificationReason,
      independentHoldoutSatisfied: false,
      validatedVehiclePackCount: 0,
    },
    authority: {
      presentationOnly: true,
      grantsHardwareAuthority: false,
      native: "missing",
      backend: "missing",
      runtime: "missing",
      operator: "missing",
    },
  };
}

/** Fixed code-unit ordering makes draft serialization independent of the user's locale. */
function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, child]) => [key, sortJson(child)]),
  );
}

/** Export an unsigned, explicitly denied draft, not trusted qualification evidence. */
export function serializeLabCalibrationDraftReceipt(
  input: LabCalibrationInput,
  analysis: LabCalibrationAnalysis,
): string {
  return `${JSON.stringify(sortJson(buildLabCalibrationDraftReceipt(input, analysis)), null, 2)}\n`;
}
