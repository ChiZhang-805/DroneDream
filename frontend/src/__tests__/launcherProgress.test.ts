import { describe, expect, it } from "vitest";

import {
  LAUNCHER_PROGRESS_CHECKPOINTS,
  launcherProgressFromEvidence,
} from "../desktop/launcherProgress";
import type { RuntimeStatusReport } from "../desktop/bridge";

describe("launcher progress contract", () => {
  const runtime = (statuses: Array<"ready" | "stopped">): RuntimeStatusReport => ({
    runtimeName: "DroneDreamRuntime",
    installed: true,
    running: true,
    ready: statuses.every((status) => status === "ready"),
    version: "2026.08",
    dataRoot: "E:\\DroneDream",
    components: statuses.map((status, index) => ({
      id: `component-${index}`,
      label: `Component ${index}`,
      status,
      required: true,
    })),
    diagnostics: [],
  });

  it("keeps missing or blocked Runtime states at zero", () => {
    expect(launcherProgressFromEvidence({
      enabled: false,
      prerequisitesFresh: true,
      runtimeFresh: true,
      runtime: null,
      runtimeAccessStatus: "blocked",
      complete: false,
    })).toBe(0);
    expect(launcherProgressFromEvidence({
      enabled: true,
      blocked: true,
      prerequisitesFresh: true,
      runtimeFresh: true,
      runtime: runtime(["ready"]),
      runtimeAccessStatus: "ready",
      complete: false,
    })).toBe(0);
  });

  it("advances only when fresh readiness evidence exists", () => {
    const partial = runtime(["ready", "stopped"]);
    expect(launcherProgressFromEvidence({
      enabled: true,
      prerequisitesFresh: true,
      runtimeFresh: true,
      runtime: partial,
      runtimeAccessStatus: "checking",
      complete: false,
    })).toBeGreaterThan(LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRunning);
    expect(launcherProgressFromEvidence({
      enabled: true,
      prerequisitesFresh: true,
      runtimeFresh: true,
      runtime: runtime(["ready", "ready"]),
      runtimeAccessStatus: "ready",
      complete: false,
    })).toBe(LAUNCHER_PROGRESS_CHECKPOINTS.runtimeAccess);
  });

  it("reserves 100 percent for the complete local readiness contract", () => {
    expect(launcherProgressFromEvidence({
      enabled: true,
      prerequisitesFresh: true,
      runtimeFresh: true,
      runtime: runtime(["ready"]),
      runtimeAccessStatus: "ready",
      complete: true,
    })).toBe(100);
  });
});
