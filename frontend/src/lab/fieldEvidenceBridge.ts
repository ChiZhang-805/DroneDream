import type { LabEvidencePreview } from "./evidencePreview";

export const FIELD_PRODUCT_SOURCE = "2f8fa28564dab7b1ff264c853705535373cb9068";
export const FIELD_PRODUCT_TREE = "afb7b4db584bf71e03d2f0b707b8b992e96bc7e7";
export const FIELD_EDITION_MANIFEST_SHA256 =
  "cbd2c3a10843601469f91ef7d097c72459becaa6e60c387e39b721e76680bd08";
export const FIELD_TUNING_CONTRACT_SHA256 =
  "141a29cc9425c3857ddcf477e41d168184095adc9c7031deb16ef474b40f8815";
export const LAB_COMMON_CORE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9";
export const MAX_FIELD_RECEIPT_BYTES = 512 * 1024;

const SHA256 = /^[a-f0-9]{64}$/;
const COMMIT = /^[a-f0-9]{40}$/;
const ENGINE_PACK = /^sha256:[a-f0-9]{64}$/;
const JOB_ID = /^(?:field|lab)-harness-[a-z0-9-]{1,82}$/;
const PARAMETER = /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}$/;
const RFC3339_SECONDS_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const FORBIDDEN_FIELD = /(api[-_]?key|authorization|cookie|email|header|password|secret|token)/i;
const QUALIFICATION_REASON =
  "Recorded evidence can guide the next bounded trial but never grants hardware authority";

export interface FieldHarnessMetrics {
  trackingError: number;
  overshootPercent: number;
  controlEffort: number;
  constraintViolations: number;
  emergencyInterventions: number;
}

export interface FieldHarnessTrialReceipt {
  trialId: string;
  telemetrySha256: string;
  candidateSha256: string;
  parameters: Record<string, number>;
  metrics: FieldHarnessMetrics;
  score: number;
  accepted: boolean;
  failureClass: string;
  independentHoldout: boolean;
}

export interface FieldHarnessReceipt {
  fileName: string;
  editionId: "field" | "lab";
  jobId: string;
  sourceCommit: string;
  enginePackId: string;
  requestSha256: string;
  deviceObservationId: string;
  observationSha256: string;
  snapshotSha256: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  trials: FieldHarnessTrialReceipt[];
  selectedCandidateSha256: string;
  proposedCandidateSha256: string;
  holdoutTrialId: string;
  qualificationStatus: "recorded-evidence-passed" | "recorded-evidence-rejected";
  recordedEvidencePassed: boolean;
  blockers: string[];
  receiptSha256: string;
  receiptIntegrityVerified: true;
  hardwareValid: false;
  hardwareAuthority: false;
  hardwareActionsPerformed: 0;
  providerRequests: 0;
}

export interface LabSimFieldBridgeDecision {
  state: "waiting-for-evidence" | "mismatch-denied" | "normalization-required";
  identityMatched: boolean;
  candidateLineageMatched: boolean;
  calibrationReady: false;
  qualificationDecision: "deny";
  hardwareAuthority: false;
  blockers: string[];
  bindings: {
    commonCoreCommit: string | null;
    vehiclePackId: string | null;
    parameterCandidateHash: string | null;
    fieldReceiptSha256: string | null;
    fieldObservationSha256: string | null;
    fieldSnapshotSha256: string | null;
    controllerIdentity: string | null;
    firmwareIdentity: string | null;
  };
}

export class FieldEvidenceBridgeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FieldEvidenceBridgeError";
  }
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new FieldEvidenceBridgeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function assertExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new FieldEvidenceBridgeError(`${label} fields do not match the Field receipt schema.`);
  }
}

function assertNoSensitiveFields(value: unknown, path = "receipt"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoSensitiveFields(item, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (FORBIDDEN_FIELD.test(key)) {
      throw new FieldEvidenceBridgeError(`Sensitive field is not allowed at ${path}.${key}.`);
    }
    assertNoSensitiveFields(child, `${path}.${key}`);
  }
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new FieldEvidenceBridgeError(`${label} must be a non-empty string.`);
  }
  return value.trim();
}

function safeText(value: unknown, label: string, maximumLength: number): string {
  const text = stringValue(value, label);
  const containsControlCharacter = [...text].some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
  if (text.length > maximumLength || containsControlCharacter) {
    throw new FieldEvidenceBridgeError(`${label} is invalid or too long.`);
  }
  return text;
}

function shaValue(value: unknown, label: string): string {
  const sha = stringValue(value, label).toLowerCase();
  if (!SHA256.test(sha)) {
    throw new FieldEvidenceBridgeError(`${label} must be a lowercase SHA-256 value.`);
  }
  return sha;
}

function finiteNumber(value: unknown, label: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum) {
    throw new FieldEvidenceBridgeError(`${label} must be a finite number at least ${minimum}.`);
  }
  return value;
}

function integerValue(value: unknown, label: string, minimum = 0): number {
  const number = finiteNumber(value, label, minimum);
  if (!Number.isInteger(number)) {
    throw new FieldEvidenceBridgeError(`${label} must be an integer.`);
  }
  return number;
}

function boundedNumber(value: unknown, label: string, minimum: number, maximum: number): number {
  const number = finiteNumber(value, label, minimum);
  if (number > maximum) {
    throw new FieldEvidenceBridgeError(`${label} must not exceed ${maximum}.`);
  }
  return number;
}

function boundedInteger(value: unknown, label: string, minimum: number, maximum: number): number {
  const number = integerValue(value, label, minimum);
  if (number > maximum) {
    throw new FieldEvidenceBridgeError(`${label} must not exceed ${maximum}.`);
  }
  return number;
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new FieldEvidenceBridgeError(`${label} must be boolean.`);
  }
  return value;
}

function parametersValue(value: unknown, label: string): Record<string, number> {
  const parameters = objectValue(value, label);
  if (Object.keys(parameters).length === 0 || Object.keys(parameters).length > 64) {
    throw new FieldEvidenceBridgeError(`${label} must contain 1-64 parameters.`);
  }
  return Object.fromEntries(Object.entries(parameters).map(([name, raw]) => {
    if (!PARAMETER.test(name)) {
      throw new FieldEvidenceBridgeError(`${label} contains an unsupported parameter name.`);
    }
    return [name, boundedNumber(raw, `${label}.${name}`, -1_000_000, 1_000_000)];
  }));
}

function parseMetrics(value: unknown, label: string): FieldHarnessMetrics {
  const metrics = objectValue(value, label);
  assertExactKeys(metrics, [
    "trackingError",
    "overshootPercent",
    "controlEffort",
    "constraintViolations",
    "emergencyInterventions",
  ], label);
  return {
    trackingError: boundedNumber(metrics.trackingError, `${label}.trackingError`, 0, 1_000),
    overshootPercent: boundedNumber(
      metrics.overshootPercent,
      `${label}.overshootPercent`,
      0,
      1_000,
    ),
    controlEffort: boundedNumber(metrics.controlEffort, `${label}.controlEffort`, 0, 1_000),
    constraintViolations: boundedInteger(
      metrics.constraintViolations,
      `${label}.constraintViolations`,
      0,
      65_535,
    ),
    emergencyInterventions: boundedInteger(
      metrics.emergencyInterventions,
      `${label}.emergencyInterventions`,
      0,
      65_535,
    ),
  };
}

function parseTrial(value: unknown, index: number): FieldHarnessTrialReceipt {
  const label = `Field trial ${index + 1}`;
  const trial = objectValue(value, label);
  assertExactKeys(trial, [
    "trialId",
    "telemetrySha256",
    "candidateSha256",
    "parameters",
    "metrics",
    "score",
    "accepted",
    "failureClass",
    "independentHoldout",
  ], label);
  return {
    trialId: safeText(trial.trialId, `${label} ID`, 80),
    telemetrySha256: shaValue(trial.telemetrySha256, `${label} telemetry hash`),
    candidateSha256: shaValue(trial.candidateSha256, `${label} candidate hash`),
    parameters: parametersValue(trial.parameters, `${label} parameters`),
    metrics: parseMetrics(trial.metrics, `${label} metrics`),
    score: boundedNumber(trial.score, `${label} score`, 0, 1_000_000),
    accepted: booleanValue(trial.accepted, `${label} accepted`),
    failureClass: safeText(trial.failureClass, `${label} failure class`, 64),
    independentHoldout: booleanValue(
      trial.independentHoldout,
      `${label} holdout marker`,
    ),
  };
}

function roundedScore(metrics: FieldHarnessMetrics): number {
  const safetyPenalty = metrics.constraintViolations * 10
    + metrics.emergencyInterventions * 100;
  return Math.round((
    metrics.trackingError * 0.68
    + (metrics.overshootPercent / 100) * 0.22
    + metrics.controlEffort * 0.1
    + safetyPenalty
  ) * 1_000_000) / 1_000_000;
}

function expectedFailureClass(
  metrics: FieldHarnessMetrics,
  score: number,
  targetScore: number,
): string {
  if (metrics.emergencyInterventions > 0) return "emergency-intervention";
  if (metrics.constraintViolations > 0) return "constraint-violation";
  return score > targetScore ? "objective-miss" : "none";
}

export function canonicalizeJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new FieldEvidenceBridgeError("Canonical JSON rejects non-finite numbers.");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalizeJson).join(",")}]`;
  }
  const object = objectValue(value, "Canonical JSON value");
  return `{${Object.keys(object).sort().map((key) => (
    `${JSON.stringify(key)}:${canonicalizeJson(object[key])}`
  )).join(",")}}`;
}

export async function sha256Text(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function assertCandidateHashes(trials: FieldHarnessTrialReceipt[]): Promise<void> {
  for (const trial of trials) {
    const actual = await sha256Text(canonicalizeJson(trial.parameters));
    if (actual !== trial.candidateSha256) {
      throw new FieldEvidenceBridgeError(`Candidate hash mismatch for ${trial.trialId}.`);
    }
  }
}

export async function parseFieldHarnessReceipt(
  fileName: string,
  source: string,
): Promise<FieldHarnessReceipt> {
  const bytes = new TextEncoder().encode(source).byteLength;
  if (bytes === 0) throw new FieldEvidenceBridgeError("The Field receipt is empty.");
  if (bytes > MAX_FIELD_RECEIPT_BYTES) {
    throw new FieldEvidenceBridgeError("The Field receipt exceeds 512 KiB.");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(source);
  } catch {
    throw new FieldEvidenceBridgeError("The Field receipt is not valid JSON.");
  }
  assertNoSensitiveFields(decoded);
  const receipt = objectValue(decoded, "Field receipt");
  assertExactKeys(receipt, [
    "schemaVersion", "kind", "jobId", "createdAt", "editionId", "executionDomain",
    "executionMode", "sourceCommit", "enginePackId", "requestSha256", "jobName",
    "objective", "targetScore", "deviceObservationId", "observationSha256", "snapshotSha256",
    "vehiclePackId", "controllerId", "firmwareVersion", "adapterId", "budget", "trials",
    "selectedCandidateSha256", "proposedParameters", "proposedCandidateSha256", "holdoutTrialId",
    "qualification", "blockers", "providerRequests", "deviceOpenAttempts", "hardwareWriteAttempts",
    "armAttempts", "flightAttempts", "hardwareAuthority", "receiptSha256",
  ], "Field receipt");
  if (
    receipt.schemaVersion !== 1
    || receipt.kind !== "dronedream-field-harness-job-receipt"
    || (receipt.editionId !== "field" && receipt.editionId !== "lab")
    || receipt.executionDomain !== "real-device-recorded-evidence"
    || receipt.executionMode !== "offline-evidence-replay-no-device-io"
  ) {
    throw new FieldEvidenceBridgeError("The Field receipt identity is unsupported.");
  }
  const editionId = receipt.editionId;
  const sourceCommit = stringValue(receipt.sourceCommit, "Recorded evidence source");
  const expectedSource = editionId === "field"
    ? FIELD_PRODUCT_SOURCE
    : import.meta.env.VITE_DRONEDREAM_SOURCE_COMMIT;
  if (!COMMIT.test(sourceCommit) || !expectedSource || sourceCommit !== expectedSource) {
    throw new FieldEvidenceBridgeError(
      "The recorded evidence is not bound to the accepted product source.",
    );
  }
  const createdAt = stringValue(receipt.createdAt, "Field receipt timestamp");
  if (!RFC3339_SECONDS_UTC.test(createdAt) || Number.isNaN(Date.parse(createdAt))) {
    throw new FieldEvidenceBridgeError("The Field receipt timestamp is invalid.");
  }
  const jobId = safeText(receipt.jobId, "Field job ID", 96);
  if (!JOB_ID.test(jobId)) {
    throw new FieldEvidenceBridgeError("The Field job ID is invalid.");
  }
  safeText(receipt.jobName, "Field job name", 80);
  safeText(receipt.objective, "Field objective", 240);
  const targetScore = boundedNumber(receipt.targetScore, "Field target score", 0.01, 1);
  const enginePackId = stringValue(receipt.enginePackId, "Engine Pack ID");
  if (!ENGINE_PACK.test(enginePackId)) {
    throw new FieldEvidenceBridgeError("Engine Pack ID must be a SHA-256 content identifier.");
  }
  const budget = objectValue(receipt.budget, "Field budget");
  assertExactKeys(
    budget,
    ["maxIterations", "usedTrainingTrials", "usedHoldoutTrials", "remainingIterations"],
    "Field budget",
  );
  const maxIterations = integerValue(budget.maxIterations, "Field iteration budget", 2);
  const usedTrainingTrials = integerValue(budget.usedTrainingTrials, "Field training trials", 2);
  const usedHoldoutTrials = integerValue(budget.usedHoldoutTrials, "Field holdout trials", 1);
  const remainingIterations = integerValue(
    budget.remainingIterations,
    "Field remaining iterations",
  );
  if (
    maxIterations > 32
    || usedHoldoutTrials !== 1
    || usedTrainingTrials > 31
    || usedTrainingTrials > maxIterations
    || remainingIterations !== maxIterations - usedTrainingTrials
  ) {
    throw new FieldEvidenceBridgeError("The Field trial budget is invalid.");
  }
  const rawTrials = receipt.trials;
  if (!Array.isArray(rawTrials) || rawTrials.length !== usedTrainingTrials + 1 || rawTrials.length > 32) {
    throw new FieldEvidenceBridgeError("Field trials do not match the recorded budget.");
  }
  const trials = rawTrials.map(parseTrial);
  if (new Set(trials.map((trial) => trial.trialId)).size !== trials.length) {
    throw new FieldEvidenceBridgeError("Field trial IDs must be unique.");
  }
  const parameterNames = Object.keys(trials[0]?.parameters ?? {}).sort().join("\u0000");
  if (trials.some((trial) => Object.keys(trial.parameters).sort().join("\u0000") !== parameterNames)) {
    throw new FieldEvidenceBridgeError("Field trial parameter sets do not match.");
  }
  for (const trial of trials) {
    const expectedScore = roundedScore(trial.metrics);
    const expectedAccepted = expectedScore <= targetScore
      && trial.metrics.constraintViolations === 0
      && trial.metrics.emergencyInterventions === 0;
    if (
      trial.score !== expectedScore
      || trial.accepted !== expectedAccepted
      || trial.failureClass !== expectedFailureClass(trial.metrics, expectedScore, targetScore)
    ) {
      throw new FieldEvidenceBridgeError(`Field trial semantics are invalid for ${trial.trialId}.`);
    }
  }
  await assertCandidateHashes(trials);
  const holdout = trials.at(-1);
  if (!holdout?.independentHoldout || trials.slice(0, -1).some((trial) => trial.independentHoldout)) {
    throw new FieldEvidenceBridgeError("Exactly one final independent Field holdout is required.");
  }
  const selectedCandidateSha256 = shaValue(
    receipt.selectedCandidateSha256,
    "Selected candidate hash",
  );
  if (
    holdout.candidateSha256 !== selectedCandidateSha256
    || trials[0]?.candidateSha256 !== selectedCandidateSha256
    || trials.slice(0, -2).some((trial, index) => trial.score > trials[index + 1].score)
  ) {
    throw new FieldEvidenceBridgeError("Field holdout or best-candidate ordering is invalid.");
  }
  if (safeText(receipt.holdoutTrialId, "Holdout trial ID", 80) !== holdout.trialId) {
    throw new FieldEvidenceBridgeError("Field holdout trial identity drifted.");
  }
  const proposedParameters = parametersValue(receipt.proposedParameters, "Proposed parameters");
  const proposedCandidateSha256 = shaValue(
    receipt.proposedCandidateSha256,
    "Proposed candidate hash",
  );
  if (await sha256Text(canonicalizeJson(proposedParameters)) !== proposedCandidateSha256) {
    throw new FieldEvidenceBridgeError("Field proposed candidate hash mismatch.");
  }
  const qualification = objectValue(receipt.qualification, "Field qualification");
  assertExactKeys(
    qualification,
    ["status", "recordedEvidencePassed", "hardwareValid", "reason"],
    "Field qualification",
  );
  const qualificationStatus = stringValue(
    qualification.status,
    "Field qualification status",
  );
  if (
    qualificationStatus !== "recorded-evidence-passed"
    && qualificationStatus !== "recorded-evidence-rejected"
  ) {
    throw new FieldEvidenceBridgeError("Field qualification status is unsupported.");
  }
  const recordedEvidencePassed = booleanValue(
    qualification.recordedEvidencePassed,
    "Recorded evidence decision",
  );
  const expectedRecordedEvidencePassed = trials[0].accepted
    && holdout.accepted
    && holdout.candidateSha256 === selectedCandidateSha256;
  if (
    (qualificationStatus === "recorded-evidence-passed") !== recordedEvidencePassed
    || recordedEvidencePassed !== expectedRecordedEvidencePassed
  ) {
    throw new FieldEvidenceBridgeError("Field qualification status contradicts its decision.");
  }
  if (qualification.reason !== QUALIFICATION_REASON) {
    throw new FieldEvidenceBridgeError("Field qualification reason drifted.");
  }
  if (qualification.hardwareValid !== false || receipt.hardwareAuthority !== false) {
    throw new FieldEvidenceBridgeError("Field recorded evidence must not grant hardware authority.");
  }
  const actionFields = [
    receipt.deviceOpenAttempts,
    receipt.hardwareWriteAttempts,
    receipt.armAttempts,
    receipt.flightAttempts,
  ];
  if (actionFields.some((value) => value !== 0) || receipt.providerRequests !== 0) {
    throw new FieldEvidenceBridgeError("Field offline evidence contains an execution attempt.");
  }
  if (!Array.isArray(receipt.blockers) || !receipt.blockers.every((item) => typeof item === "string")) {
    throw new FieldEvidenceBridgeError("Field blockers are invalid.");
  }
  const blockers = receipt.blockers.map((item) => safeText(item, "Field blocker", 160));
  const requiredBlockers = [
    "field.registry.zero-validated-packs",
    "field.native-backend-runtime-quorum.missing",
    "field.operator-confirmation.missing",
  ];
  if (
    new Set(blockers).size !== blockers.length
    || requiredBlockers.some((blocker) => !blockers.includes(blocker))
    || (!recordedEvidencePassed && !blockers.includes("field.recorded-evidence.not-qualified"))
  ) {
    throw new FieldEvidenceBridgeError("Field blockers do not preserve the safety gate.");
  }
  const receiptSha256 = shaValue(receipt.receiptSha256, "Field receipt hash");
  const hashInput = { ...receipt, receiptSha256: "" };
  if (await sha256Text(canonicalizeJson(hashInput)) !== receiptSha256) {
    throw new FieldEvidenceBridgeError("Field receipt JCS integrity check failed.");
  }
  return {
    fileName,
    editionId,
    jobId,
    sourceCommit,
    enginePackId,
    requestSha256: shaValue(receipt.requestSha256, "Field request hash"),
    deviceObservationId: safeText(receipt.deviceObservationId, "Device observation ID", 160),
    observationSha256: shaValue(receipt.observationSha256, "Observation hash"),
    snapshotSha256: shaValue(receipt.snapshotSha256, "Snapshot hash"),
    vehiclePackId: safeText(receipt.vehiclePackId, "Vehicle Pack ID", 160),
    controllerId: safeText(receipt.controllerId, "Controller ID", 160),
    firmwareVersion: safeText(receipt.firmwareVersion, "Firmware version", 160),
    adapterId: safeText(receipt.adapterId, "Adapter ID", 160),
    trials,
    selectedCandidateSha256,
    proposedCandidateSha256,
    holdoutTrialId: holdout.trialId,
    qualificationStatus,
    recordedEvidencePassed,
    blockers,
    receiptSha256,
    receiptIntegrityVerified: true,
    hardwareValid: false,
    hardwareAuthority: false,
    hardwareActionsPerformed: 0,
    providerRequests: 0,
  };
}

export function evaluateSimFieldBridge(
  simulation: LabEvidencePreview | null,
  field: FieldHarnessReceipt | null,
  consumedFieldReceipts: ReadonlySet<string> = new Set(),
): LabSimFieldBridgeDecision {
  const bindings = {
    commonCoreCommit: simulation?.commonCoreCommit ?? null,
    vehiclePackId: simulation?.vehiclePackId ?? field?.vehiclePackId ?? null,
    parameterCandidateHash: simulation?.parameterCandidateHash ?? field?.selectedCandidateSha256 ?? null,
    fieldReceiptSha256: field?.receiptSha256 ?? null,
    fieldObservationSha256: field?.observationSha256 ?? null,
    fieldSnapshotSha256: field?.snapshotSha256 ?? null,
    controllerIdentity: field?.controllerId ?? null,
    firmwareIdentity: field?.firmwareVersion ?? null,
  };
  if (!simulation || !field) {
    return {
      state: "waiting-for-evidence",
      identityMatched: false,
      candidateLineageMatched: false,
      calibrationReady: false,
      qualificationDecision: "deny",
      hardwareAuthority: false,
      blockers: [
        ...(simulation ? [] : ["lab.sim-evidence.missing"]),
        ...(field ? [] : ["lab.field-evidence.missing"]),
      ],
      bindings,
    };
  }
  const mismatches = [
    ...(consumedFieldReceipts.has(field.receiptSha256)
      ? ["lab.field-evidence.replay-denied"]
      : []),
    ...(simulation.commonCoreCommit === LAB_COMMON_CORE_COMMIT
      ? []
      : ["lab.common-core.mismatch"]),
    ...(simulation.vehiclePackId === field.vehiclePackId
      ? []
      : ["lab.vehicle-pack.mismatch"]),
    ...(simulation.parameterCandidateHash === field.selectedCandidateSha256
      ? []
      : ["lab.parameter-candidate.mismatch"]),
    ...(field.recordedEvidencePassed ? [] : ["lab.field-recorded-evidence.rejected"]),
  ];
  if (mismatches.length > 0) {
    return {
      state: "mismatch-denied",
      identityMatched: false,
      candidateLineageMatched: false,
      calibrationReady: false,
      qualificationDecision: "deny",
      hardwareAuthority: false,
      blockers: mismatches,
      bindings,
    };
  }
  return {
    state: "normalization-required",
    identityMatched: false,
    candidateLineageMatched: true,
    calibrationReady: false,
    qualificationDecision: "deny",
    hardwareAuthority: false,
    blockers: [
      "lab.job-binding.missing",
      "lab.sim.controller-firmware-binding.unavailable",
      "lab.metric-normalization-receipt.missing",
      "lab.registry.zero-validated-packs",
      "lab.native-backend-runtime-quorum.missing",
    ],
    bindings,
  };
}
