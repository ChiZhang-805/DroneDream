import type { FieldTuningDemoRequest } from "./bridge";

/** Validate before allocating fixture candidates or dispatching a native request. */
export function isFieldTuningDemoRequest(value: unknown): value is FieldTuningDemoRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const request = value as Record<string, unknown>;
  return typeof request.objective === "string"
    && request.objective.trim().length > 0
    && request.objective.length <= 120
    // Native String limits count UTF-8 bytes, including Chinese objectives.
    && new TextEncoder().encode(request.objective).length <= 120
    && typeof request.maxIterations === "number"
    && Number.isInteger(request.maxIterations)
    && request.maxIterations >= 2 && request.maxIterations <= 8
    && typeof request.targetScore === "number"
    && Number.isFinite(request.targetScore)
    && request.targetScore >= 0.15 && request.targetScore <= 0.9;
}
