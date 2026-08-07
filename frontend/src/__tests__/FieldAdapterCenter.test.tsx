import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getFieldAdapterCatalog,
  inspectFieldProtocolFrame,
  installFieldAdapter,
  probeFieldMavlinkTelemetry,
} from "../desktop/bridge";
import { FieldAdapterCenter } from "../field/FieldAdapterCenter";

vi.mock("../desktop/bridge", async (importOriginal) => {
  const original = await importOriginal<typeof import("../desktop/bridge")>();
  return {
    ...original,
    isDesktopRuntime: () => true,
    getFieldAdapterCatalog: vi.fn(),
    installFieldAdapter: vi.fn(),
    inspectFieldProtocolFrame: vi.fn(),
    probeFieldMavlinkTelemetry: vi.fn(),
  };
});

const report = {
  schemaVersion: 1 as const,
  kind: "dronedream-field-adapter-catalog-report" as const,
  catalogVersion: "1.0.0",
  editionId: "field" as const,
  source: "source-bound-embedded-catalog" as const,
  catalogSha256: "a".repeat(64),
  hardwareAuthority: false as const,
  executableExtensionLoading: false as const,
  entries: [
    {
      adapterId: "mavlink-common-v2",
      version: "1.0.0",
      displayName: { en: "MAVLink Common", "zh-CN": "MAVLink 通用协议" },
      vendor: "MAVLink",
      protocolFamily: "MAVLink 1/2 Common",
      implementationStatus: "available" as const,
      deliveryMode: "embedded-managed" as const,
      installable: true,
      installed: false,
      installedPackageSha256: null,
      supportedTransports: ["serial", "udp"],
      supportedPlatforms: ["windows"],
      packageSha256: "b".repeat(64),
      capabilities: {
        deviceDiscovery: "read-only" as const,
        telemetryRead: "read-only" as const,
        parameterRead: "quorum-required" as const,
        parameterWrite: "quorum-required" as const,
        arm: "quorum-required" as const,
        flight: "quorum-required" as const,
        autonomousTuning: "quorum-required" as const,
      },
      safety: {
        installationGrantsAuthority: false as const,
        discoveryGrantsAuthority: false as const,
        requiresValidatedVehiclePackForWrites: true as const,
        requiresNativeBackendRuntimeOperatorQuorum: true as const,
      },
    },
    {
      adapterId: "dji-enterprise-sdk",
      version: "1.0.0",
      displayName: { en: "DJI Enterprise SDK", "zh-CN": "大疆行业SDK" },
      vendor: "DJI",
      protocolFamily: "DJI SDK",
      implementationStatus: "vendor-access-required" as const,
      deliveryMode: "vendor-managed" as const,
      installable: false,
      installed: false,
      installedPackageSha256: null,
      supportedTransports: ["remote-controller"],
      supportedPlatforms: ["android-bridge"],
      packageSha256: null,
      capabilities: {
        deviceDiscovery: "vendor-controlled" as const,
        telemetryRead: "vendor-controlled" as const,
        parameterRead: "vendor-controlled" as const,
        parameterWrite: "unavailable" as const,
        arm: "vendor-controlled" as const,
        flight: "vendor-controlled" as const,
        autonomousTuning: "unavailable" as const,
      },
      safety: {
        installationGrantsAuthority: false as const,
        discoveryGrantsAuthority: false as const,
        requiresValidatedVehiclePackForWrites: true as const,
        requiresNativeBackendRuntimeOperatorQuorum: true as const,
      },
    },
  ],
};

describe("FieldAdapterCenter", () => {
  beforeEach(() => {
    vi.mocked(getFieldAdapterCatalog).mockReset().mockResolvedValue(report);
    vi.mocked(installFieldAdapter).mockReset().mockResolvedValue({
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
    });
    vi.mocked(probeFieldMavlinkTelemetry).mockReset().mockResolvedValue({
      schemaVersion: 1,
      kind: "dronedream-field-mavlink-telemetry-probe-receipt",
      editionId: "field",
      adapterId: "mavlink-common-v2",
      observationId: "c".repeat(64),
      portName: "COM7",
      baudRate: 115_200,
      protocolVersion: 2,
      systemId: 42,
      componentId: 1,
      sequence: 7,
      messageId: 0,
      messageName: "HEARTBEAT",
      frameSha256: "d".repeat(64),
      frameBytes: 21,
      deviceOpenAttempts: 1,
      telemetryReadAttempts: 1,
      parameterReadAttempts: 0,
      hardwareWriteAttempts: 0,
      armAttempts: 0,
      flightAttempts: 0,
      hardwareAuthority: false,
    });
    vi.mocked(inspectFieldProtocolFrame).mockReset().mockResolvedValue({
      schemaVersion: 1,
      kind: "dronedream-field-protocol-frame-inspection",
      editionId: "field",
      adapterId: "mavlink-common-v2",
      protocolFamily: "MAVLink",
      classification: "HEARTBEAT",
      fields: { messageId: 0, messageName: "HEARTBEAT" },
      frameSha256: "e".repeat(64),
      frameBytes: 21,
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    });
  });

  it("installs only a catalog-bound managed adapter", async () => {
    render(<FieldAdapterCenter locale="en" />);
    await screen.findByText("Vendor access required");
    const table = within(screen.getByRole("table", { name: "Protocol adapters" }));
    const buttons = table.getAllByRole("button", { name: "Install" });

    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeDisabled();
    fireEvent.click(buttons[0]!);

    await waitFor(() => expect(installFieldAdapter).toHaveBeenCalledWith({
      adapterId: "mavlink-common-v2",
      expectedPackageSha256: "b".repeat(64),
    }));
    expect(screen.getByText(/Vehicle Pack validation/)).toBeInTheDocument();
    expect(screen.getByText("Vendor access required")).toBeInTheDocument();
  });

  it("installs every available managed adapter serially without enabling vendor SDKs", async () => {
    const secondManaged = {
      ...report.entries[0]!,
      adapterId: "betaflight-msp-v1",
      displayName: { en: "Betaflight / INAV MSP", "zh-CN": "Betaflight / INAV MSP" },
      vendor: "Betaflight / INAV",
      protocolFamily: "MultiWii Serial Protocol v1",
      packageSha256: "c".repeat(64),
    };
    vi.mocked(getFieldAdapterCatalog).mockResolvedValue({
      ...report,
      entries: [report.entries[0]!, secondManaged, report.entries[1]!],
    });
    let activeInstalls = 0;
    let maximumConcurrentInstalls = 0;
    const installOrder: string[] = [];
    vi.mocked(installFieldAdapter).mockImplementation(async (request) => {
      activeInstalls += 1;
      maximumConcurrentInstalls = Math.max(maximumConcurrentInstalls, activeInstalls);
      installOrder.push(request.adapterId);
      await new Promise((resolve) => window.setTimeout(resolve, 5));
      activeInstalls -= 1;
      return {
        schemaVersion: 1,
        kind: "dronedream-field-adapter-install-receipt",
        editionId: "field",
        adapterId: request.adapterId,
        packageSha256: request.expectedPackageSha256,
        state: "installed",
        executableCodeInstalled: false,
        deviceOpenAttempts: 0,
        hardwareWriteAttempts: 0,
        hardwareAuthority: false,
      };
    });
    render(<FieldAdapterCenter locale="en" />);
    const installAll = await screen.findByRole("button", {
      name: "Install all open adapters",
    });

    fireEvent.click(installAll);

    await waitFor(() => expect(installFieldAdapter).toHaveBeenCalledTimes(2));
    expect(installOrder).toEqual(["mavlink-common-v2", "betaflight-msp-v1"]);
    expect(maximumConcurrentInstalls).toBe(1);
    expect(installFieldAdapter).not.toHaveBeenCalledWith(
      expect.objectContaining({ adapterId: "dji-enterprise-sdk" }),
    );
  });

  it("requires an installed adapter, observed port, and explicit read-only confirmation", async () => {
    vi.mocked(getFieldAdapterCatalog).mockResolvedValue({
      ...report,
      entries: [{
        ...report.entries[0]!,
        installed: true,
        installedPackageSha256: "b".repeat(64),
      }, report.entries[1]!],
    });
    const onReadOnlyEvidence = vi.fn();
    render(<FieldAdapterCenter locale="en" onReadOnlyEvidence={onReadOnlyEvidence} devices={[{
      observationId: "c".repeat(64),
      portName: "COM7",
      registryValueNameSha256: "d".repeat(64),
      transport: "windows-serial-registry-readonly",
      portOpened: false,
      validationStatus: "unknown-unvalidated",
      hardwareAuthority: false,
    }]} />);
    const probe = await screen.findByRole("button", { name: "Read one frame" });
    expect(probe).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", {
      name: /one read-only frame/i,
    }));
    expect(probe).toBeEnabled();
    fireEvent.click(probe);

    await waitFor(() => expect(probeFieldMavlinkTelemetry).toHaveBeenCalledWith({
      adapterId: "mavlink-common-v2",
      expectedPackageSha256: "b".repeat(64),
      observationId: "c".repeat(64),
      portName: "COM7",
      baudRate: 115_200,
      readDeadlineMs: 3_000,
      operatorConfirmedReadOnly: true,
    }));
    expect(await screen.findByText(/Received HEARTBEAT/)).toBeInTheDocument();
    expect(onReadOnlyEvidence).toHaveBeenCalledWith({
      adapterId: "mavlink-common-v2",
      observationSha256: "d".repeat(64),
      deviceObservationId: "c".repeat(64),
    });
  });

  it("inspects one offline frame without invoking a device transport", async () => {
    vi.mocked(getFieldAdapterCatalog).mockResolvedValue({
      ...report,
      entries: [{
        ...report.entries[0]!,
        installed: true,
        installedPackageSha256: "b".repeat(64),
      }, report.entries[1]!],
    });
    const onReadOnlyEvidence = vi.fn();
    render(<FieldAdapterCenter locale="en" onReadOnlyEvidence={onReadOnlyEvidence} />);

    const frame = await screen.findByRole("textbox", {
      name: "Captured frame (canonical base64)",
    });
    fireEvent.change(frame, { target: { value: "AQ==" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect frame" }));

    await waitFor(() => expect(inspectFieldProtocolFrame).toHaveBeenCalledWith({
      adapterId: "mavlink-common-v2",
      frameBase64: "AQ==",
    }));
    expect(probeFieldMavlinkTelemetry).not.toHaveBeenCalled();
    expect(await screen.findByText(/Classified MAVLink/)).toBeInTheDocument();
    expect(onReadOnlyEvidence).toHaveBeenCalledWith({
      adapterId: "mavlink-common-v2",
      observationSha256: "e".repeat(64),
      deviceObservationId: `offline-frame:${"e".repeat(32)}`,
    });
  });
});
