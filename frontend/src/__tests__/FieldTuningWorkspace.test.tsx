import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { FieldTuningWorkspace } from "../field/FieldTuningWorkspace";

describe("FieldTuningWorkspace", () => {
  beforeEach(() => {
    delete window.__TAURI__;
  });

  it("runs the complete fixture Model and Harness loop without hardware authority", () => {
    const { container } = render(
      <FieldTuningWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run safe tuning demo" }));

    expect(screen.getByRole("heading", { name: "Candidate history" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(6);
    expect(screen.getByText("Independent holdout")).toBeInTheDocument();
    expect(screen.getByText("Demo-qualified only")).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-simulation='false']")).toBeTruthy();
  });

  it("returns a typed real-hardware denial with all mandatory evidence", () => {
    render(
      <FieldTuningWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
        snapshot={{
          schemaVersion: 1,
          kind: "dronedream-field-parameter-snapshot",
          editionId: "field",
          executionDomain: "real-hardware",
          evidenceSource: "operator-imported-read-only",
          sourceCommit: "a".repeat(40),
          deviceObservationId: "offline-frame:fixture",
          vehiclePackId: "holybro-x500-v2-pixhawk6",
          controllerId: "Holybro::Pixhawk 6C",
          firmwareVersion: "PX4 1.16.0",
          adapterId: "mavlink-common-v2",
          observationSha256: "b".repeat(64),
          parameterCount: 1,
          parameters: { MC_ROLL_P: 6.5 },
          parameterSetSha256: "c".repeat(64),
          snapshotSha256: "d".repeat(64),
          deviceOpenAttempts: 0,
          hardwareWriteAttempts: 0,
          hardwareAuthority: false,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Evaluate current hardware gate" }));

    const status = screen.getByRole("status");
    expect(within(status).getByText("field.registry.zero-validated-packs"))
      .toBeInTheDocument();
    expect(within(status).getByText("parameter-snapshot")).toBeInTheDocument();
    expect(within(status).getByText("transaction-rollback")).toBeInTheDocument();
    expect(within(status).getByText("0")).toBeInTheDocument();
    expect(within(status).getByText(/canExecute=false/)).toBeInTheDocument();
    expect(screen.getByText("Snapshot bound")).toBeInTheDocument();
  });

  it("authors the Chinese tuning workflow independently", () => {
    render(
      <FieldTuningWorkspace
        locale="zh-CN"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );

    expect(screen.getByRole("heading", { name: "真机自主调参" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行安全调参演示" })).toBeInTheDocument();
    expect(screen.getByText("Model 提出受边界约束的候选参数，Harness 负责受控实验、遥测评分、失败分类和回滚证据。"))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "真机记录证据 Harness 作业" })).toBeInTheDocument();
  });

  it("creates an empty evidence template from the bound snapshot without fake trials", () => {
    render(
      <FieldTuningWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
        snapshot={{
          schemaVersion: 1,
          kind: "dronedream-field-parameter-snapshot",
          editionId: "field",
          executionDomain: "real-hardware",
          evidenceSource: "operator-imported-read-only",
          sourceCommit: "a".repeat(40),
          deviceObservationId: "recorded-observation-1",
          vehiclePackId: "holybro-x500-v2-pixhawk6",
          controllerId: "Holybro::Pixhawk 6C",
          firmwareVersion: "PX4 1.16.0",
          adapterId: "mavlink-common-v2",
          observationSha256: "b".repeat(64),
          parameterCount: 1,
          parameters: { MC_ROLL_P: 6.5 },
          parameterSetSha256: "c".repeat(64),
          snapshotSha256: "d".repeat(64),
          deviceOpenAttempts: 0,
          hardwareWriteAttempts: 0,
          hardwareAuthority: false,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create template from snapshot" }));
    const textarea = screen.getByRole("textbox", { name: "Parameter bounds and recorded trials (JSON)" });
    const value = JSON.parse((textarea as HTMLTextAreaElement).value) as {
      parameterBounds: Record<string, unknown>;
      trials: unknown[];
    };
    expect(value.parameterBounds).toHaveProperty("MC_ROLL_P");
    expect(value.trials).toEqual([]);
  });
});
