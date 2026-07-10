import {
  probeRuntimeStatus,
  probeSystemPrerequisites,
} from "./bridge";
import type {
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "./bridge";

export const MINIMUM_MEMORY_BYTES = 15 * 1024 ** 3;

export interface DesktopReadinessSnapshot {
  prerequisites: SystemPrerequisiteReport;
  runtime: RuntimeStatusReport;
  ready: boolean;
}

export function isRuntimeFullyReady(report: RuntimeStatusReport | null): boolean {
  const requiredComponents = report?.components.filter((component) => component.required) ?? [];
  return Boolean(
    report?.ready &&
    report.installed &&
    report.running &&
    requiredComponents.length > 0 &&
    requiredComponents.every((component) => component.status === "ready"),
  );
}

export function isRuntimeConfirmedMissing(report: RuntimeStatusReport | null): boolean {
  const requiredComponents = report?.components.filter((component) => component.required) ?? [];
  return Boolean(
    report &&
    !report.installed &&
    !report.running &&
    !report.ready &&
    requiredComponents.length > 0 &&
    requiredComponents.every((component) => component.status === "missing"),
  );
}

export function isOverallDesktopReady(
  prerequisites: SystemPrerequisiteReport | null,
  runtime: RuntimeStatusReport | null,
): boolean {
  return Boolean(
    prerequisites &&
    prerequisites.platform.toLowerCase() === "windows" &&
    prerequisites.supported &&
    prerequisites.windows &&
    prerequisites.memory &&
    prerequisites.memory.totalBytes >= MINIMUM_MEMORY_BYTES &&
    prerequisites.wsl.executableAvailable &&
    isRuntimeFullyReady(runtime),
  );
}

export async function probeOverallDesktopReadiness(): Promise<DesktopReadinessSnapshot> {
  const [prerequisites, runtime] = await Promise.all([
    probeSystemPrerequisites(),
    probeRuntimeStatus(),
  ]);
  return {
    prerequisites,
    runtime,
    ready: isOverallDesktopReady(prerequisites, runtime),
  };
}
