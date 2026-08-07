import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  compareFieldParameterSnapshot,
  createFieldParameterSnapshot,
  discoverFieldDevices,
  getFieldAdapterCatalog,
  getFieldTuningStatus,
  inspectFieldAdapterFrame,
  inspectFieldProtocolFrame,
  installFieldAdapter,
  probeFieldMavlinkTelemetry,
  prepareFieldHardwareTuning,
  prepareFieldParameterRollback,
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

  it("accepts a source-bound adapter catalog and data-only install receipt", async () => {
    const catalog = {
      schemaVersion: 1,
      kind: "dronedream-field-adapter-catalog-report",
      catalogVersion: "1.0.0",
      editionId: "field",
      source: "source-bound-embedded-catalog",
      catalogSha256: "a".repeat(64),
      hardwareAuthority: false,
      executableExtensionLoading: false,
      entries: [{
        adapterId: "mavlink-common-v2",
        version: "1.0.0",
        displayName: { en: "MAVLink Common", "zh-CN": "MAVLink 通用协议" },
        vendor: "MAVLink",
        protocolFamily: "MAVLink 1/2 Common",
        implementationStatus: "available",
        deliveryMode: "embedded-managed",
        installable: true,
        installed: false,
        installedPackageSha256: null,
        supportedTransports: ["serial"],
        supportedPlatforms: ["windows"],
        packageSha256: "b".repeat(64),
        capabilities: {
          deviceDiscovery: "read-only",
          telemetryRead: "read-only",
          parameterRead: "quorum-required",
          parameterWrite: "quorum-required",
          arm: "quorum-required",
          flight: "quorum-required",
          autonomousTuning: "quorum-required",
        },
        safety: {
          installationGrantsAuthority: false,
          discoveryGrantsAuthority: false,
          requiresValidatedVehiclePackForWrites: true,
          requiresNativeBackendRuntimeOperatorQuorum: true,
        },
      }],
    };
    const receipt = {
      schemaVersion: 1,
      kind: "dronedream-field-adapter-install-receipt",
      editionId: "field",
      adapterId: "mavlink-common-v2",
      packageSha256: "b".repeat(64),
      state: "installed",
      executableCodeInstalled: false,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    };
    const invoke = vi.fn(async (command: string) => (
      command === "get_field_adapter_catalog" ? catalog : receipt
    ));
    window.__TAURI__ = { core: { invoke } };

    await expect(getFieldAdapterCatalog()).resolves.toEqual(catalog);
    await expect(installFieldAdapter({
      adapterId: "mavlink-common-v2",
      expectedPackageSha256: "b".repeat(64),
    })).resolves.toEqual(receipt);
  });

  it("accepts a passive MAVLink frame inspection and rejects authority drift", async () => {
    const inspection = {
      schemaVersion: 1,
      kind: "dronedream-field-adapter-frame-inspection",
      editionId: "field",
      adapterId: "mavlink-common-v2",
      protocolVersion: 2,
      systemId: 42,
      componentId: 1,
      sequence: 7,
      messageId: 0,
      messageName: "HEARTBEAT",
      frameSha256: "c".repeat(64),
      frameBytes: 21,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    };
    const invoke = vi.fn(async () => inspection);
    window.__TAURI__ = { core: { invoke } };

    await expect(inspectFieldAdapterFrame({
      adapterId: "mavlink-common-v2",
      frameBase64: "AQ==",
    })).resolves.toEqual(inspection);

    invoke.mockResolvedValueOnce({ ...inspection, hardwareWriteAttempts: 1 });
    await expect(inspectFieldAdapterFrame({
      adapterId: "mavlink-common-v2",
      frameBase64: "AQ==",
    })).rejects.toThrow();
  });

  it("accepts only bounded scalar offline protocol inspection fields", async () => {
    const inspection = {
      schemaVersion: 1,
      kind: "dronedream-field-protocol-frame-inspection",
      editionId: "field",
      adapterId: "crazyflie-crtp",
      protocolFamily: "CRTP",
      classification: "logging",
      fields: { port: 5, channel: 0, subsystem: "logging" },
      frameSha256: "d".repeat(64),
      frameBytes: 3,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    };
    const invoke = vi.fn(async () => inspection);
    window.__TAURI__ = { core: { invoke } };

    await expect(inspectFieldProtocolFrame({
      adapterId: "crazyflie-crtp",
      frameBase64: "XAE=",
    })).resolves.toEqual(inspection);
    expect(invoke).toHaveBeenCalledWith("inspect_field_protocol_frame", {
      request: { adapterId: "crazyflie-crtp", frameBase64: "XAE=" },
    });

    invoke.mockResolvedValueOnce({
      ...inspection,
      fields: { nested: {} },
    } as unknown as typeof inspection);
    await expect(inspectFieldProtocolFrame({
      adapterId: "crazyflie-crtp",
      frameBase64: "XAE=",
    })).rejects.toThrow();
  });

  it("accepts only a read-only bounded serial telemetry receipt", async () => {
    const receipt = {
      schemaVersion: 1,
      kind: "dronedream-field-mavlink-telemetry-probe-receipt",
      editionId: "field",
      adapterId: "mavlink-common-v2",
      observationId: "a".repeat(64),
      portName: "COM7",
      baudRate: 115_200,
      protocolVersion: 2,
      systemId: 42,
      componentId: 1,
      sequence: 7,
      messageId: 0,
      messageName: "HEARTBEAT",
      frameSha256: "c".repeat(64),
      frameBytes: 21,
      deviceOpenAttempts: 1,
      telemetryReadAttempts: 1,
      parameterReadAttempts: 0,
      hardwareWriteAttempts: 0,
      armAttempts: 0,
      flightAttempts: 0,
      hardwareAuthority: false,
    };
    const invoke = vi.fn(async () => receipt);
    window.__TAURI__ = { core: { invoke } };
    const request = {
      adapterId: "mavlink-common-v2" as const,
      expectedPackageSha256: "b".repeat(64),
      observationId: "a".repeat(64),
      portName: "COM7",
      baudRate: 115_200 as const,
      readDeadlineMs: 3_000,
      operatorConfirmedReadOnly: true as const,
    };

    await expect(probeFieldMavlinkTelemetry(request)).resolves.toEqual(receipt);
    expect(invoke).toHaveBeenCalledWith("probe_field_mavlink_telemetry", { request });
    invoke.mockResolvedValueOnce({ ...receipt, parameterReadAttempts: 1 });
    await expect(probeFieldMavlinkTelemetry(request)).rejects.toThrow();
  });

  it("accepts content-bound snapshots and keeps rollback execution denied", async () => {
    const parameters = { MC_ROLL_P: 6.5, MC_PITCH_P: 6.5 };
    const snapshot = {
      schemaVersion: 1,
      kind: "dronedream-field-parameter-snapshot",
      editionId: "field",
      executionDomain: "real-hardware",
      evidenceSource: "operator-imported-read-only",
      sourceCommit: "a".repeat(40),
      deviceObservationId: "observation-fixture",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      adapterId: "mavlink-common-v2",
      observationSha256: "b".repeat(64),
      parameterCount: 2,
      parameters,
      parameterSetSha256: "c".repeat(64),
      snapshotSha256: "d".repeat(64),
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    };
    const changes = [{ name: "MC_ROLL_P", before: 6.5, after: 6.8, delta: 0.3 }];
    const diff = {
      schemaVersion: 1,
      kind: "dronedream-field-parameter-diff",
      editionId: "field",
      snapshotSha256: "d".repeat(64),
      currentParameterSetSha256: "e".repeat(64),
      changedCount: 1,
      changes,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
      receiptSha256: "f".repeat(64),
    };
    const rollback = {
      schemaVersion: 1,
      kind: "dronedream-field-rollback-plan",
      editionId: "field",
      snapshotSha256: "d".repeat(64),
      planSha256: "1".repeat(64),
      changes,
      canExecute: false,
      hardwareAuthority: false,
      hardwareWriteAttempts: 0,
      requiredEvidence: [
        "hardware-validated-vehicle-pack",
        "controller-and-firmware-match",
        "signed-current-observation",
        "transactional-parameter-writer",
        "operator-confirmation",
        "native-backend-runtime-quorum",
      ],
      blockers: [
        "field.registry.zero-validated-packs",
        "field.snapshot.rollback-write-disabled",
      ],
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "create_field_parameter_snapshot") return snapshot;
      if (command === "compare_field_parameter_snapshot") return diff;
      return rollback;
    });
    window.__TAURI__ = { core: { invoke } };

    const snapshotRequest = {
      deviceObservationId: "observation-fixture",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      adapterId: "mavlink-common-v2",
      observationSha256: "b".repeat(64),
      parameters,
    };
    await expect(createFieldParameterSnapshot(snapshotRequest)).resolves.toEqual(snapshot);
    const diffRequest = { snapshotSha256: "d".repeat(64), currentParameters: { ...parameters, MC_ROLL_P: 6.8 } };
    await expect(compareFieldParameterSnapshot(diffRequest)).resolves.toEqual(diff);
    await expect(prepareFieldParameterRollback(diffRequest)).resolves.toEqual(rollback);

    invoke.mockResolvedValueOnce({
      ...diff,
      changes: [{ ...changes[0], delta: 9 }],
    });
    await expect(compareFieldParameterSnapshot(diffRequest)).rejects.toThrow(/delta/i);
    invoke.mockResolvedValueOnce({ ...rollback, canExecute: true });
    await expect(prepareFieldParameterRollback(diffRequest)).rejects.toThrow();
  });

  it.each([
    { hardwareAuthority: true },
    { executableExtensionLoading: true },
    { entries: [] },
  ])("rejects an adapter catalog that weakens its boundary: %o", async (drift) => {
    const invoke = vi.fn(async () => ({
      schemaVersion: 1,
      kind: "dronedream-field-adapter-catalog-report",
      catalogVersion: "1.0.0",
      editionId: "field",
      source: "source-bound-embedded-catalog",
      catalogSha256: "a".repeat(64),
      hardwareAuthority: false,
      executableExtensionLoading: false,
      entries: [{
        adapterId: "mavlink-common-v2",
        version: "1.0.0",
        displayName: { en: "MAVLink Common", "zh-CN": "MAVLink 通用协议" },
        vendor: "MAVLink",
        protocolFamily: "MAVLink 1/2 Common",
        implementationStatus: "available",
        deliveryMode: "embedded-managed",
        installable: true,
        installed: false,
        installedPackageSha256: null,
        supportedTransports: ["serial"],
        supportedPlatforms: ["windows"],
        packageSha256: "b".repeat(64),
        capabilities: {
          deviceDiscovery: "read-only",
          telemetryRead: "read-only",
          parameterRead: "quorum-required",
          parameterWrite: "quorum-required",
          arm: "quorum-required",
          flight: "quorum-required",
          autonomousTuning: "quorum-required",
        },
        safety: {
          installationGrantsAuthority: false,
          discoveryGrantsAuthority: false,
          requiresValidatedVehiclePackForWrites: true,
          requiresNativeBackendRuntimeOperatorQuorum: true,
        },
      }],
      ...drift,
    }));
    window.__TAURI__ = { core: { invoke } };

    await expect(getFieldAdapterCatalog()).rejects.toThrow();
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
