import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  discoverFieldDevices,
  getFieldTuningStatus,
  prepareFieldHardwareTuning,
} from "../desktop/bridge";

const deviceReport = {
  schemaVersion: 1,
  kind: "dronedream-field-device-discovery-report",
  editionId: "field",
  source: "windows-serial-registry-readonly",
  supported: true,
  portOpenAttempts: 0,
  writeAttempts: 0,
  hardwareAuthority: false,
  devices: [
    {
      observationId: "a".repeat(64),
      portName: "COM7",
      registryValueNameSha256: "f".repeat(64),
      transport: "windows-serial-registry-readonly",
      portOpened: false,
      validationStatus: "unknown-unvalidated",
      hardwareAuthority: false,
    },
  ],
  diagnostics: ["Observed ports remain unopened and unvalidated."],
};

describe("Field desktop bridge", () => {
  beforeEach(() => {
    delete window.__TAURI__;
  });

  it("accepts read-only discovery while preserving zero hardware authority", async () => {
    const invoke = vi.fn(async () => deviceReport);
    window.__TAURI__ = { core: { invoke } };

    await expect(discoverFieldDevices()).resolves.toEqual(deviceReport);
    expect(invoke).toHaveBeenCalledWith("discover_field_devices", undefined);
  });

  it.each([
    { portOpenAttempts: 1 },
    { writeAttempts: 1 },
    { hardwareAuthority: true },
    { devices: [{ ...deviceReport.devices[0], portOpened: true }] },
    { devices: [{ ...deviceReport.devices[0], hardwareAuthority: true }] },
  ])("rejects discovery responses that claim device authority: %o", async (drift) => {
    const invoke = vi.fn(async () => ({ ...deviceReport, ...drift }));
    window.__TAURI__ = { core: { invoke } };

    await expect(discoverFieldDevices()).rejects.toThrow();
  });

  it("rejects any tuning status that weakens the source-bound denial", async () => {
    const invoke = vi.fn(async () => ({
      schemaVersion: 1,
      kind: "dronedream-field-tuning-status",
      editionId: "field",
      executionDomain: "real-hardware",
      runtimeProfile: "field-lightweight",
      sourceCommit: "b".repeat(40),
      enginePackId: `sha256:${"c".repeat(64)}`,
      contractSha256: "d".repeat(64),
      simulationSupported: false,
      modelRole: "proposal-only",
      harnessRole: "bounded-execution-evidence-and-rollback",
      demoAvailable: true,
      hardwareAuthority: false,
      validatedPackCount: 1,
      blockers: ["field.registry.zero-validated-packs"],
    }));
    window.__TAURI__ = { core: { invoke } };

    await expect(getFieldTuningStatus()).rejects.toThrow(/source-bound safety denial/i);
  });

  it("accepts a future nonzero registry count without granting execution authority", async () => {
    const response = {
      schemaVersion: 1,
      kind: "dronedream-field-tuning-status",
      editionId: "field",
      executionDomain: "real-hardware",
      runtimeProfile: "field-lightweight",
      sourceCommit: "b".repeat(40),
      enginePackId: `sha256:${"c".repeat(64)}`,
      contractSha256: "d".repeat(64),
      simulationSupported: false,
      modelRole: "proposal-only",
      harnessRole: "bounded-execution-evidence-and-rollback",
      demoAvailable: true,
      hardwareAuthority: false,
      validatedPackCount: 1,
      blockers: ["field.device.transport-unavailable", "field.quorum.missing"],
    };
    const invoke = vi.fn(async () => response);
    window.__TAURI__ = { core: { invoke } };

    await expect(getFieldTuningStatus()).resolves.toEqual(response);
  });

  it("rejects a native hardware plan that claims execution authority", async () => {
    const invoke = vi.fn(async () => ({
      schemaVersion: 1,
      kind: "dronedream-field-hardware-tuning-plan",
      editionId: "field",
      executionDomain: "real-hardware",
      requestSha256: "e".repeat(64),
      canExecute: true,
      hardwareAuthority: true,
      requiredEvidence: [
        "validated-vehicle-pack",
        "controller-and-firmware-match",
        "parameter-snapshot",
        "transaction-rollback",
        "operator-confirmation",
        "preflight",
        "safety-zone",
        "control-takeover",
        "emergency-stop",
      ],
      blockers: [],
    }));
    window.__TAURI__ = { core: { invoke } };

    await expect(prepareFieldHardwareTuning({
      deviceId: "device-fixture",
      vehiclePackId: "pack-fixture",
      controllerId: "controller-fixture",
      firmwareVersion: "1.0.0",
      objective: "Bounded bench tuning",
    })).rejects.toThrow();
  });
});
