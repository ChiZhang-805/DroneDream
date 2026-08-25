import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FieldPreflightWorkspace } from "../field/FieldPreflightWorkspace";

const bridge = vi.hoisted(() => ({ prepare: vi.fn() }));

vi.mock("../desktop/bridge", async (importOriginal) => {
  const original = await importOriginal<typeof import("../desktop/bridge")>();
  return {
    ...original,
    isDesktopRuntime: () => true,
    prepareFieldPreflight: bridge.prepare,
  };
});

const plan = {
  schemaVersion: 1,
  kind: "dronedream-field-preflight-plan",
  editionId: "field",
  executionDomain: "real-hardware",
  sourceCommit: "a".repeat(40),
  requestSha256: "b".repeat(64),
  planSha256: "c".repeat(64),
  validatedPackCount: 0,
  zone: {
    name: "Indoor cage A",
    radiusM: 12,
    maxAltitudeM: 5,
    evidenceState: "operator-declared-only",
  },
  quorum: {
    vehiclePack: "missing",
    controller: "matched",
    firmware: "matched",
    observation: "present",
    snapshot: "matched",
    zone: "operator-declared",
    operatorConfirmation: "local-only",
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
} as const;

const snapshot = {
  schemaVersion: 1,
  kind: "dronedream-field-parameter-snapshot",
  editionId: "field",
  executionDomain: "real-hardware",
  evidenceSource: "operator-imported-read-only",
  sourceCommit: "a".repeat(40),
  deviceObservationId: "operator-imported",
  vehiclePackId: "holybro-x500-v2-pixhawk6",
  controllerId: "Holybro::Pixhawk 6C",
  firmwareVersion: "PX4 1.16.0",
  adapterId: "mavlink-common-v2",
  observationSha256: "d".repeat(64),
  parameterCount: 1,
  parameters: { MC_ROLL_P: 6.5 },
  parameterSetSha256: "e".repeat(64),
  snapshotSha256: "f".repeat(64),
  deviceOpenAttempts: 0,
  hardwareWriteAttempts: 0,
  hardwareAuthority: false,
} as const;

describe("FieldPreflightWorkspace", () => {
  beforeEach(() => {
    bridge.prepare.mockReset().mockResolvedValue(plan);
  });

  it("evaluates bound evidence while every hardware action stays denied", async () => {
    const { container } = render(
      <FieldPreflightWorkspace
        locale="en"
        selectedPackId={snapshot.vehiclePackId}
        selectedControllerId={snapshot.controllerId}
        snapshot={snapshot}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /I confirm the declared zone/ }));
    fireEvent.click(screen.getByRole("button", { name: "Evaluate preflight" }));

    await waitFor(() => expect(bridge.prepare).toHaveBeenCalledWith(expect.objectContaining({
      snapshotSha256: snapshot.snapshotSha256,
      observationSha256: snapshot.observationSha256,
      operatorConfirmed: true,
      zoneRadiusM: 12,
      maxAltitudeM: 5,
    })));
    expect(await screen.findByText("field.registry.zero-validated-packs")).toBeInTheDocument();
    const actionMatrix = container.querySelector(".field-action-matrix");
    expect(actionMatrix).not.toBeNull();
    expect(within(actionMatrix as HTMLElement).getAllByText("deny")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Request takeover" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
  });

  it("surfaces a fail-closed invalid-zone rejection", async () => {
    bridge.prepare.mockRejectedValueOnce(new Error("Field preflight request is outside its bound."));
    render(
      <FieldPreflightWorkspace
        locale="zh-CN"
        selectedPackId={snapshot.vehiclePackId}
        selectedControllerId={snapshot.controllerId}
      />,
    );
    fireEvent.change(screen.getByRole("spinbutton", { name: "最大高度（米）" }), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "评估飞前条件" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("飞前条件评估失败。");
    expect(bridge.prepare).toHaveBeenCalledOnce();
  });
});
