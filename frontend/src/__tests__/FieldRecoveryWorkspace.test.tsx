import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FieldRecoveryWorkspace } from "../field/FieldRecoveryWorkspace";

const bridge = vi.hoisted(() => ({
  compare: vi.fn(),
  create: vi.fn(),
  rollback: vi.fn(),
}));

vi.mock("../desktop/bridge", async (importOriginal) => {
  const original = await importOriginal<typeof import("../desktop/bridge")>();
  return {
    ...original,
    isDesktopRuntime: () => true,
    createFieldParameterSnapshot: bridge.create,
    compareFieldParameterSnapshot: bridge.compare,
    prepareFieldParameterRollback: bridge.rollback,
  };
});

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
  observationSha256: "b".repeat(64),
  parameterCount: 3,
  parameters: { MC_ROLL_P: 6.5, MC_PITCH_P: 6.5, MPC_XY_VEL_P_ACC: 1.8 },
  parameterSetSha256: "c".repeat(64),
  snapshotSha256: "d".repeat(64),
  deviceOpenAttempts: 0,
  hardwareWriteAttempts: 0,
  hardwareAuthority: false,
} as const;

describe("FieldRecoveryWorkspace", () => {
  beforeEach(() => {
    bridge.create.mockReset().mockResolvedValue(snapshot);
    bridge.compare.mockReset().mockResolvedValue({
      schemaVersion: 1,
      kind: "dronedream-field-parameter-diff",
      editionId: "field",
      snapshotSha256: snapshot.snapshotSha256,
      currentParameterSetSha256: "e".repeat(64),
      changedCount: 1,
      changes: [{ name: "MC_ROLL_P", before: 6.5, after: 6.8, delta: 0.3 }],
      deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0,
      hardwareAuthority: false,
      receiptSha256: "f".repeat(64),
    });
    bridge.rollback.mockReset().mockResolvedValue({
      schemaVersion: 1,
      kind: "dronedream-field-rollback-plan",
      editionId: "field",
      snapshotSha256: snapshot.snapshotSha256,
      planSha256: "1".repeat(64),
      changes: [{ name: "MC_ROLL_P", before: 6.5, after: 6.8, delta: 0.3 }],
      canExecute: false,
      hardwareAuthority: false,
      hardwareWriteAttempts: 0,
      requiredEvidence: ["a", "b", "c", "d", "e", "f"],
      blockers: [
        "field.registry.zero-validated-packs",
        "field.snapshot.rollback-write-disabled",
      ],
    });
  });

  it("captures, compares, and prepares only a denied rollback plan", async () => {
    const { container } = render(
      <FieldRecoveryWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
        evidence={{
          adapterId: "mavlink-common-v2",
          observationSha256: "b".repeat(64),
          deviceObservationId: "offline-frame:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        }}
      />,
    );
    expect(screen.getByRole("textbox", { name: "Observation receipt SHA-256" }))
      .toHaveValue("b".repeat(64));
    fireEvent.change(screen.getByRole("textbox", { name: "Observed firmware" }), {
      target: { value: "PX4 1.16.0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(await screen.findByText("dddddddddd...dddddddd")).toBeInTheDocument();

    const current = screen.getByRole("textbox", { name: "Current parameters (JSON)" });
    fireEvent.change(current, { target: { value: JSON.stringify({ ...snapshot.parameters, MC_ROLL_P: 6.8 }) } });
    fireEvent.click(screen.getByRole("button", { name: "Compare drift" }));
    expect(await screen.findByText("MC_ROLL_P")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare rollback" }));
    expect(await screen.findByText("Rollback execution denied")).toBeInTheDocument();
    expect(screen.getByText("field.registry.zero-validated-packs")).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false'][data-hardware-write-attempts='0']"))
      .toBeTruthy();
    expect(screen.queryByRole("button", { name: /apply|execute/i })).not.toBeInTheDocument();
  });

  it("rejects malformed parameter JSON before invoking native commands", async () => {
    render(
      <FieldRecoveryWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Observation receipt SHA-256" }), {
      target: { value: "b".repeat(64) },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Baseline parameters (JSON)" }), {
      target: { value: '{"1INVALID": 4}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/1 to 256 finite numeric/i);
    expect(bridge.create).not.toHaveBeenCalled();
  });
});
