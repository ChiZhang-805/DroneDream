import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRuntimeInstallProgress, validateDistributionPlan } from "../desktop/bridge";

/** A native-operation fixture, not an installation or a real disk modification. */
function snapshot(updatedAt: string) {
  return {
    operationId: "test-operation", phase: "downloading", bytesDownloaded: 0,
    bytesTotal: 100, currentPart: 1, totalParts: 1, message: null, error: null,
    resumable: true, requiresRestart: false, targetRoot: "Q:\\DroneDream",
    installedVersion: null, updatedAt,
  };
}

describe("Desktop receipt timestamps", () => {
  beforeEach(() => { delete window.__TAURI__; });

  it.each([
    "2026-02-30T12:00:00Z", "2026-02-29T12:00:00Z", "2100-02-29T12:00:00Z",
    "2026-04-31T12:00:00Z", "2026-09-11T24:00:00Z", "2026-09-11T12:00:00",
    "2026-09-11T12:00:00+24:00", "2026-09-11T12:00:00+08:60",
  ])("rejects normalized or timezone-ambiguous instants: %s", async (updatedAt) => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => snapshot(updatedAt)) } };
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/ISO 8601/);
  });

  it.each([
    "2024-02-29T12:00:00Z", "2000-02-29T12:00:00.123Z",
    "2026-09-11T12:00:00+08:00", "2026-09-11T12:00:00.123456789-07:00",
  ])("preserves valid zoned instants without local-time conversion: %s", async (updatedAt) => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => snapshot(updatedAt)) } };
    await expect(getRuntimeInstallProgress()).resolves.toEqual(snapshot(updatedAt));
  });

  it.each(["::", "Vendor::", "::Model", " Vendor::Model", "Vendor:: Model", `${"厂".repeat(54)}::Model`])(
    "rejects empty or oversized controller namespaces before IPC: %s", (controllerKey) => {
      const invoke = vi.fn();
      window.__TAURI__ = { core: { invoke } };
      expect(() => validateDistributionPlan({
        selection: { schemaVersion: 1, editionId: "field", region: "global",
          vehiclePackId: "pack", controllerKey, optionalModules: [] },
        rollbackReference: null,
      })).toThrow(/controller/);
      expect(invoke).not.toHaveBeenCalled();
    },
  );
});
