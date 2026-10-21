import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as bridge from "../desktop/bridge";
import { FieldTuningWorkspace } from "../field/FieldTuningWorkspace";
import { fieldBrowserHardwareDenial, fieldBrowserStatus, runFieldBrowserFixture } from "../field/tuning";

const props = { locale: "en" as const, selectedPackId: "pack", selectedControllerId: "controller" };
const demo = () => runFieldBrowserFixture({ objective: "old objective", maxIterations: 5, targetScore: 0.55 });

function deferred<T>() {
  // Complete an old native request at a deliberately chosen UI ownership boundary.
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("Field tuning result ownership", () => {
  beforeEach(() => {
    vi.spyOn(bridge, "isDesktopRuntime").mockReturnValue(true);
    vi.spyOn(bridge, "getFieldTuningStatus").mockResolvedValue(fieldBrowserStatus());
    vi.spyOn(bridge, "listFieldHarnessJobs").mockResolvedValue([]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("does not show a late demo receipt under an edited objective", async () => {
    const pending = deferred<bridge.FieldTuningDemoReceipt>();
    vi.spyOn(bridge, "runFieldTuningDemo").mockReturnValue(pending.promise);
    render(<FieldTuningWorkspace {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Run safe tuning demo" }));
    fireEvent.change(screen.getByLabelText("Tuning objective"), { target: { value: "new objective" } });
    await act(async () => pending.resolve(demo()));
    expect(screen.queryByRole("heading", { name: "Candidate history" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run safe tuning demo" })).toBeEnabled();
  });

  it("does not transfer a late hardware gate to a newly selected vehicle", async () => {
    const pending = deferred<bridge.FieldHardwareTuningPlan>();
    vi.spyOn(bridge, "prepareFieldHardwareTuning").mockReturnValue(pending.promise);
    const view = render(<FieldTuningWorkspace {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Evaluate current hardware gate" }));
    view.rerender(<FieldTuningWorkspace {...props} selectedPackId="another-pack" />);
    await act(async () => pending.resolve(fieldBrowserHardwareDenial()));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("clears an existing receipt when its numeric budget changes", async () => {
    vi.spyOn(bridge, "runFieldTuningDemo").mockResolvedValue(demo());
    render(<FieldTuningWorkspace {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Run safe tuning demo" }));
    expect(await screen.findByRole("heading", { name: "Candidate history" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Iteration budget"), { target: { value: "3" } });
    expect(screen.queryByRole("heading", { name: "Candidate history" })).not.toBeInTheDocument();
  });

  it("does not bind another vehicle's snapshot into the selected hardware workspace", async () => {
    const snapshot = {
      schemaVersion: 1, kind: "dronedream-field-parameter-snapshot", editionId: "field",
      executionDomain: "real-hardware", evidenceSource: "operator-imported-read-only",
      sourceCommit: "a".repeat(40), deviceObservationId: "observed",
      vehiclePackId: "wrong-pack", controllerId: "controller", firmwareVersion: "version",
      adapterId: "adapter", observationSha256: "b".repeat(64), parameterCount: 1,
      parameters: { MC_ROLL_P: 6.5 }, parameterSetSha256: "c".repeat(64),
      snapshotSha256: "d".repeat(64), deviceOpenAttempts: 0, hardwareWriteAttempts: 0,
      hardwareAuthority: false,
    } as const satisfies bridge.FieldParameterSnapshot;
    render(<FieldTuningWorkspace {...props} snapshot={snapshot} />);
    await act(async () => {});
    expect(screen.getByText("No parameter snapshot bound")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze evidence and propose next trial" })).toBeDisabled();
  });

  it("does not let initial history overwrite a newer persisted job refresh", async () => {
    const initial = deferred<bridge.FieldHarnessJobSummary[]>();
    const jobs = [{
      jobId: "job-new", createdAt: "2026-09-11T12:00:00Z", jobName: "New recorded job",
      objective: "Review", qualificationStatus: "recorded-evidence-passed" as const,
      recordedEvidencePassed: true, hardwareValid: false as const, receiptSha256: "a".repeat(64),
    }];
    vi.mocked(bridge.listFieldHarnessJobs).mockReturnValueOnce(initial.promise).mockResolvedValueOnce(jobs);
    // All IPC is mocked: these shape fixtures exercise React ownership only.
    const snapshot = {
      schemaVersion: 1, kind: "dronedream-field-parameter-snapshot", editionId: "field",
      executionDomain: "real-hardware", evidenceSource: "operator-imported-read-only",
      sourceCommit: "a".repeat(40), parameterCount: 1, parameterSetSha256: "f".repeat(64),
      deviceOpenAttempts: 0, hardwareWriteAttempts: 0, hardwareAuthority: false,
      vehiclePackId: props.selectedPackId, controllerId: props.selectedControllerId,
      snapshotSha256: "b".repeat(64), observationSha256: "c".repeat(64), firmwareVersion: "test",
      deviceObservationId: "test", adapterId: "adapter", parameters: { P: 1 },
    } as const satisfies bridge.FieldParameterSnapshot;
    vi.spyOn(bridge, "runFieldHarnessJob").mockResolvedValue({
      schemaVersion: 1, kind: "dronedream-field-harness-job-receipt", editionId: "field",
      jobId: "test-job", createdAt: "2026-09-11T12:00:00Z",
      executionDomain: "real-device-recorded-evidence", executionMode: "offline-evidence-replay-no-device-io",
      sourceCommit: "a".repeat(40), enginePackId: `sha256:${"b".repeat(64)}`,
      requestSha256: "c".repeat(64), jobName: "test-job", objective: "test", targetScore: 0.5,
      deviceObservationId: snapshot.deviceObservationId, observationSha256: snapshot.observationSha256,
      snapshotSha256: snapshot.snapshotSha256, vehiclePackId: snapshot.vehiclePackId,
      controllerId: snapshot.controllerId, firmwareVersion: snapshot.firmwareVersion, adapterId: snapshot.adapterId,
      budget: { maxIterations: 5, usedTrainingTrials: 2, usedHoldoutTrials: 1, remainingIterations: 3 },
      trials: [], selectedCandidateSha256: "d".repeat(64), holdoutTrialId: "holdout",
      qualification: { status: "recorded-evidence-passed", recordedEvidencePassed: true,
        hardwareValid: false, reason: "UI fixture only" }, receiptSha256: "d".repeat(64),
      proposedCandidateSha256: "e".repeat(64), proposedParameters: { P: 1 },
      blockers: ["fixture"], providerRequests: 0, deviceOpenAttempts: 0,
      hardwareWriteAttempts: 0, armAttempts: 0, flightAttempts: 0, hardwareAuthority: false,
    });
    render(<FieldTuningWorkspace {...props} snapshot={snapshot} />);
    fireEvent.change(screen.getByLabelText("Parameter bounds and recorded trials (JSON)"), {
      target: { value: JSON.stringify({ parameterBounds: { P: {} }, trials: [{}, {}, {}] }) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze evidence and propose next trial" }));
    expect(await screen.findByText("New recorded job")).toBeInTheDocument();
    await act(async () => initial.resolve([]));
    expect(screen.getByText("New recorded job")).toBeInTheDocument();
  });
});
