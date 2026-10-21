import type { FieldHarnessJobRequest } from "./bridge";

/** Validate objects from JSON, without pretending their contents are measured evidence. */
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Bound recorded-data analysis; passing this check never permits a hardware write. */
export function validateFieldHarnessRequest(request: FieldHarnessJobRequest): void {
  // Reject malformed roots before any property reads, allocation or native call.
  if (!record(request) || !record(request.parameterBounds) || !Array.isArray(request.trials)) {
    throw new Error("Field Harness request is outside its bounded contract.");
  }
  // Rust limits String bytes, not UTF-16 code units. Match that boundary so
  // non-ASCII objectives do not pass the form only to fail during native dispatch.
  const identities = [
    [request.jobName, 80], [request.objective, 240], [request.deviceObservationId, 160],
    [request.vehiclePackId, 160], [request.controllerId, 160],
    [request.firmwareVersion, 160], [request.adapterId, 160],
  ] as const;
  const encoder = new TextEncoder();
  if (
    identities.some(([value, limit]) => typeof value !== "string" || value.trim() !== value
      || value.length === 0 || value.length > limit || /[\p{Cc}]/u.test(value)
      || encoder.encode(value).length > limit)
    || !/^[a-f0-9]{64}$/.test(request.observationSha256)
    || !/^[a-f0-9]{64}$/.test(request.snapshotSha256)
    || !Number.isFinite(request.targetScore)
    || request.targetScore < 0.01
    || request.targetScore > 1
    || !Number.isInteger(request.maxIterations)
    || request.maxIterations < 2
    || request.maxIterations > 32
    || request.trials.length < 3
    || request.trials.length > 32
    || request.trials.length > request.maxIterations + 1
  ) {
    throw new Error("Field Harness request is outside its bounded contract.");
  }
  const names = Object.keys(request.parameterBounds).sort();
  if (names.length === 0 || names.length > 64) {
    throw new Error("Field Harness parameter bounds are empty or oversized.");
  }
  for (const name of names) {
    const bound = request.parameterBounds[name];
    if (
      !record(bound)
      || !/^[A-Za-z0-9_.:-]{1,80}$/.test(name)
      || !Number.isFinite(bound.min)
      || !Number.isFinite(bound.max)
      || !Number.isFinite(bound.maxStep)
      || bound.min >= bound.max
      || bound.min < -1_000_000 || bound.max > 1_000_000
      || bound.maxStep < 0.000_001 || bound.maxStep > 1_000_000
      || !Number.isFinite(bound.max - bound.min)
      || bound.maxStep > bound.max - bound.min
    ) {
      throw new Error(`Field Harness parameter bound ${name} is invalid.`);
    }
  }
  const trialIds = new Set<string>();
  for (const trial of request.trials) {
    if (!record(trial) || !record(trial.parameters) || !record(trial.metrics)
      || typeof trial.trialId !== "string" || typeof trial.independentHoldout !== "boolean"
      || trialIds.has(trial.trialId)) {
      throw new Error("Field Harness trial identity or parameter set is invalid.");
    }
    trialIds.add(trial.trialId);
    const trialNames = Object.keys(trial.parameters).sort();
    if (
      trial.trialId.trim() !== trial.trialId
      || trial.trialId.length === 0
      || trial.trialId.length > 80
      || /[\p{Cc}]/u.test(trial.trialId) || encoder.encode(trial.trialId).length > 80
      || !/^[a-f0-9]{64}$/.test(trial.telemetrySha256)
      || trialNames.join("\n") !== names.join("\n")
    ) {
      throw new Error("Field Harness trial identity or parameter set is invalid.");
    }
    for (const name of names) {
      const parameter = trial.parameters[name];
      const bound = request.parameterBounds[name];
      if (!Number.isFinite(parameter) || parameter < bound.min || parameter > bound.max) {
        throw new Error(`Field Harness trial parameter ${name} is outside its bound.`);
      }
    }
    const metrics = trial.metrics;
    if (
      ![metrics.trackingError, metrics.overshootPercent, metrics.controlEffort]
        .every((metric) => Number.isFinite(metric) && metric >= 0 && metric <= 1_000)
      || !Number.isSafeInteger(metrics.constraintViolations)
      || metrics.constraintViolations < 0
      || metrics.constraintViolations > 65_535
      || !Number.isSafeInteger(metrics.emergencyInterventions)
      || metrics.emergencyInterventions < 0
      || metrics.emergencyInterventions > 65_535
    ) {
      throw new Error("Field Harness trial metrics are invalid.");
    }
  }
  // A held-out record cannot reuse telemetry already consumed by training.
  const holdout = request.trials.at(-1);
  if (holdout && request.trials.slice(0, -1).some((trial) => trial.telemetrySha256 === holdout.telemetrySha256)) {
    throw new Error("Field Harness holdout telemetry must be independent of training.");
  }
  if (
    request.trials.filter((trial) => trial.independentHoldout).length !== 1
    || request.trials.at(-1)?.independentHoldout !== true
  ) {
    throw new Error("Field Harness requires one final independent holdout trial.");
  }
}
