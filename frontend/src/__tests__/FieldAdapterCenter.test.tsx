import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getFieldAdapterCatalog,
  installFieldAdapter,
} from "../desktop/bridge";
import { FieldAdapterCenter } from "../field/FieldAdapterCenter";

vi.mock("../desktop/bridge", async (importOriginal) => {
  const original = await importOriginal<typeof import("../desktop/bridge")>();
  return {
    ...original,
    isDesktopRuntime: () => true,
    getFieldAdapterCatalog: vi.fn(),
    installFieldAdapter: vi.fn(),
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
});
