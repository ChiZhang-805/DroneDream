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
  listFieldParameterSnapshots,
  loadFieldParameterSnapshot,
  probeFieldMavlinkTelemetry,
  prepareFieldPreflight,
  prepareFieldHardwareTuning,
  prepareFieldParameterRollback,
  runFieldHarnessJob,
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

  it("accepts a persisted recorded-evidence Harness receipt without authority drift", async () => {
    const parameters = { MC_ROLL_P: 6.4 };
    const trial = (id: string, holdout: boolean) => ({
      trialId: id,
      telemetrySha256: id === "holdout" ? "d".repeat(64) : "c".repeat(64),
      candidateSha256: "e".repeat(64),
      parameters,
      metrics: {
        trackingError: 0.3,
        overshootPercent: 7,
        controlEffort: 0.4,
        constraintViolations: 0,
        emergencyInterventions: 0,
      },
      score: 0.25,
      accepted: true,
      failureClass: "none",
      independentHoldout: holdout,
    });
    const receipt = {
      schemaVersion: 1,
      kind: "dronedream-field-harness-job-receipt",
      jobId: `field-harness-${"a".repeat(16)}-${"b".repeat(8)}`,
      createdAt: "2026-08-07T12:00:00Z",
      editionId: "field",
      executionDomain: "real-device-recorded-evidence",
      executionMode: "offline-evidence-replay-no-device-io",
      sourceCommit: "a".repeat(40),
      enginePackId: `sha256:${"b".repeat(64)}`,
      requestSha256: "c".repeat(64),
      jobName: "Field evidence",
      objective: "Reduce tracking error",
      targetScore: 0.5,
      deviceObservationId: "observation-1",
      observationSha256: "a".repeat(64),
      snapshotSha256: "b".repeat(64),
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      adapterId: "mavlink-common-v2",
      budget: {
        maxIterations: 4,
        usedTrainingTrials: 2,
        usedHoldoutTrials: 1,
        remainingIterations: 2,
      },
      trials: [trial("training-1", false), trial("training-2", false), trial("holdout", true)],
      selectedCandidateSha256: "e".repeat(64),
      proposedParameters: parameters,
      proposedCandidateSha256: "f".repeat(64),
      holdoutTrialId: "holdout",
      qualification: {
        status: "recorded-evidence-passed",
        recordedEvidencePassed: true,
        hardwareValid: false,
        reason: "Recorded evidence never grants hardware authority",
      },
      blockers: ["field.registry.zero-validated-packs"],
      providerRequests: 0,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      armAttempts: 0,
      flightAttempts: 0,
      hardwareAuthority: false,
      receiptSha256: "a".repeat(64),
    };
    const invoke = vi.fn(async () => receipt);
    window.__TAURI__ = { core: { invoke } };
    const request = {
      jobName: "Field evidence",
      objective: "Reduce tracking error",
      targetScore: 0.5,
      maxIterations: 4,
      deviceObservationId: "observation-1",
      observationSha256: "a".repeat(64),
      snapshotSha256: "b".repeat(64),
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      adapterId: "mavlink-common-v2",
      parameterBounds: { MC_ROLL_P: { min: 5, max: 8, maxStep: 0.2 } },
      trials: [
        { trialId: "training-1", telemetrySha256: "c".repeat(64), parameters, metrics: trial("training-1", false).metrics, independentHoldout: false },
        { trialId: "training-2", telemetrySha256: "c".repeat(64), parameters, metrics: trial("training-2", false).metrics, independentHoldout: false },
        { trialId: "holdout", telemetrySha256: "d".repeat(64), parameters, metrics: trial("holdout", true).metrics, independentHoldout: true },
      ],
    };

    await expect(runFieldHarnessJob(request)).resolves.toEqual(receipt);
    expect(invoke).toHaveBeenCalledWith("run_field_harness_job", { request });
    invoke.mockResolvedValueOnce({ ...receipt, hardwareWriteAttempts: 1 });
    await expect(runFieldHarnessJob(request)).rejects.toThrow();
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
    const summary = {
      schemaVersion: 1,
      kind: "dronedream-field-parameter-snapshot-summary",
      editionId: "field",
      sourceCommit: snapshot.sourceCommit,
      deviceObservationId: snapshot.deviceObservationId,
      vehiclePackId: snapshot.vehiclePackId,
      controllerId: snapshot.controllerId,
      firmwareVersion: snapshot.firmwareVersion,
      adapterId: snapshot.adapterId,
      observationSha256: snapshot.observationSha256,
      parameterCount: snapshot.parameterCount,
      parameterSetSha256: snapshot.parameterSetSha256,
      snapshotSha256: snapshot.snapshotSha256,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    };
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
      if (command === "list_field_parameter_snapshots") return [summary];
      if (command === "load_field_parameter_snapshot") return snapshot;
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
    await expect(listFieldParameterSnapshots()).resolves.toEqual([summary]);
    await expect(loadFieldParameterSnapshot(snapshot.snapshotSha256)).resolves.toEqual(snapshot);
    await expect(loadFieldParameterSnapshot("invalid")).rejects.toThrow(/hash/i);
    invoke.mockResolvedValueOnce([{ ...summary, parameterCount: 0 }]);
    await expect(listFieldParameterSnapshots()).rejects.toThrow(/positive/i);
    invoke.mockResolvedValueOnce([summary, summary]);
    await expect(listFieldParameterSnapshots()).rejects.toThrow(/ordered/i);
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

  it("accepts only a deny-by-default native Field preflight plan", async () => {
    const request = {
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      deviceObservationId: "operator-imported",
      observationSha256: "a".repeat(64),
      snapshotSha256: "b".repeat(64),
      zoneName: "Indoor cage A",
      zoneRadiusM: 12,
      maxAltitudeM: 5,
      operatorConfirmed: true,
    };
    const plan = {
      schemaVersion: 1,
      kind: "dronedream-field-preflight-plan",
      editionId: "field",
      executionDomain: "real-hardware",
      sourceCommit: "c".repeat(40),
      requestSha256: "d".repeat(64),
      planSha256: "e".repeat(64),
      validatedPackCount: 0,
      zone: {
        name: "Indoor cage A",
        radiusM: 12,
        maxAltitudeM: 5,
        evidenceState: "operator-declared-only",
      },
      quorum: {
        vehiclePack: "missing",
        nativeBackendRuntime: "missing",
        policy: "deny",
      },
      actionDecisions: {
        "parameter-write": "deny",
        "rollback-apply": "deny",
        takeover: "deny",
        "emergency-stop": "deny",
        arm: "deny",
        flight: "deny",
      },
      requiredEvidence: ["a", "b", "c", "d", "e", "f", "g"],
      blockers: [
        "field.registry.zero-validated-packs",
        "field.native-backend-runtime-quorum.missing",
      ],
      canExecute: false,
      hardwareAuthority: false,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
    };
    const invoke = vi.fn(async () => plan);
    window.__TAURI__ = { core: { invoke } };

    await expect(prepareFieldPreflight(request)).resolves.toEqual(plan);
    expect(invoke).toHaveBeenCalledWith("prepare_field_preflight", { request });
    invoke.mockResolvedValueOnce({
      ...plan,
      actionDecisions: { ...plan.actionDecisions, flight: "allow" },
    });
    await expect(prepareFieldPreflight(request)).rejects.toThrow(/deny|literal/i);
    invoke.mockResolvedValueOnce({ ...plan, zone: { ...plan.zone, radiusM: 0 } });
    await expect(prepareFieldPreflight(request)).rejects.toThrow(/safety boundary/i);
    await expect(prepareFieldPreflight({ ...request, maxAltitudeM: 0 })).rejects.toThrow(/bound/i);
    await expect(prepareFieldPreflight({ ...request, deviceObservationId: " observation" }))
      .rejects.toThrow(/bound/i);
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

  it("accepts a content-bound zero-write hardware plan and rejects budget drift", async () => {
    const response = {
      schemaVersion: 1,
      kind: "dronedream-field-hardware-tuning-plan",
      jobId: "field-hardware-plan-fixture",
      editionId: "field",
      executionDomain: "real-hardware",
      sourceCommit: "a".repeat(40),
      requestSha256: "b".repeat(64),
      snapshotSha256: "c".repeat(64),
      observationSha256: "d".repeat(64),
      budget: {
        maxIterations: 5,
        hardwareTrialBudget: 0,
        parameterWriteBudget: 0,
        providerRequests: 0,
      },
      phases: [
        "snapshot-binding",
        "candidate-validation",
        "operator-confirmation",
        "controlled-trial",
        "telemetry-capture",
        "scoring-and-failure-classification",
        "independent-holdout",
        "publish-or-rollback",
      ],
      canExecute: false,
      hardwareAuthority: false,
      hardwareWriteAttempts: 0,
      requiredEvidence: [
        "validated-vehicle-pack",
        "controller-and-firmware-match",
        "protocol-observation-receipt",
        "parameter-snapshot",
        "transaction-rollback",
        "operator-confirmation",
        "preflight",
        "safety-zone",
        "control-takeover",
        "emergency-stop",
        "native-backend-runtime-quorum",
      ],
      blockers: ["field.registry.zero-validated-packs", "field.quorum.missing"],
      planSha256: "e".repeat(64),
    };
    const invoke = vi.fn(async () => response);
    window.__TAURI__ = { core: { invoke } };
    const request = {
      deviceObservationId: "offline-frame:fixture",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerId: "Holybro::Pixhawk 6C",
      firmwareVersion: "PX4 1.16.0",
      adapterId: "mavlink-common-v2",
      observationSha256: "d".repeat(64),
      snapshotSha256: "c".repeat(64),
      objective: "Bounded bench tuning",
      maxIterations: 5,
    };

    await expect(prepareFieldHardwareTuning(request)).resolves.toEqual(response);
    expect(invoke).toHaveBeenCalledWith("prepare_field_hardware_tuning", { request });
    invoke.mockResolvedValueOnce({
      ...response,
      budget: { ...response.budget, parameterWriteBudget: 1 },
    });
    await expect(prepareFieldHardwareTuning(request)).rejects.toThrow();
  });

  it("rejects a native hardware plan that claims execution authority", async () => {
    const invoke = vi.fn(async () => ({
      schemaVersion: 1,
      kind: "dronedream-field-hardware-tuning-plan",
      jobId: "field-hardware-plan-fixture",
      editionId: "field",
      executionDomain: "real-hardware",
      sourceCommit: "a".repeat(40),
      requestSha256: "e".repeat(64),
      snapshotSha256: null,
      observationSha256: null,
      budget: {
        maxIterations: 5,
        hardwareTrialBudget: 0,
        parameterWriteBudget: 0,
        providerRequests: 0,
      },
      phases: [
        "snapshot-binding",
        "candidate-validation",
        "operator-confirmation",
        "controlled-trial",
        "telemetry-capture",
        "scoring-and-failure-classification",
        "independent-holdout",
        "publish-or-rollback",
      ],
      canExecute: true,
      hardwareAuthority: true,
      hardwareWriteAttempts: 0,
      requiredEvidence: [
        "validated-vehicle-pack",
        "controller-and-firmware-match",
        "protocol-observation-receipt",
        "parameter-snapshot",
        "transaction-rollback",
        "operator-confirmation",
        "preflight",
        "safety-zone",
        "control-takeover",
        "emergency-stop",
      ],
      blockers: [],
      planSha256: "f".repeat(64),
    }));
    window.__TAURI__ = { core: { invoke } };

    await expect(prepareFieldHardwareTuning({
      deviceObservationId: null,
      vehiclePackId: "pack-fixture",
      controllerId: "controller-fixture",
      firmwareVersion: "1.0.0",
      adapterId: null,
      observationSha256: null,
      snapshotSha256: null,
      objective: "Bounded bench tuning",
      maxIterations: 5,
    })).rejects.toThrow();
  });
});
