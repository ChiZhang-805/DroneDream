import { describe, expect, it } from "vitest";

import { selectReplayArtifactsForTrial } from "../components/trajectoryReplayUtils";
import type { Artifact } from "../types/api";

function makeArtifact(
  id: string,
  trialId: string,
  artifact_type: string,
  storage_path: string,
  mime_type: string | null = "application/json",
): Artifact {
  return {
    id,
    owner_type: "trial",
    owner_id: trialId,
    artifact_type,
    display_name: artifact_type,
    storage_path,
    mime_type,
    file_size_bytes: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("selectReplayArtifactsForTrial", () => {
  it("never treats a reference file as measured flight just because its directory contains trajectory", () => {
    const reference = makeArtifact("reference", "trial-1", "reference_track_json", "/trajectory/telemetry.json/reference_track.json");
    expect(selectReplayArtifactsForTrial([reference], "trial-1")).toEqual({
      reference, trajectory: null, telemetry: null,
    });
  });

  it("does not let a telemetry-like parent directory outrank an explicit telemetry type", () => {
    const wrong = makeArtifact("wrong", "trial-1", "trajectory_plot", "/telemetry_json/other.json");
    const correct = makeArtifact("correct", "trial-1", "telemetry_json", "/data/record.json");
    expect(selectReplayArtifactsForTrial([wrong, correct], "trial-1").telemetry).toBe(correct);
  });

  it("does not mix different trial owners even when their filenames look correct", () => {
    const unrelated = makeArtifact("other", "trial-2", "telemetry_json", "/data/telemetry.json");
    expect(selectReplayArtifactsForTrial([unrelated], "trial-1").trajectory).toBeNull();
  });

  it("retains explicit measured telemetry with a reference-tracking display name", () => {
    const measured = makeArtifact("measured", "trial-1", "telemetry_json", "/data/telemetry.json");
    measured.display_name = "Reference tracking telemetry";
    expect(selectReplayArtifactsForTrial([measured], "trial-1").trajectory).toBe(measured);
  });
  it("prefers telemetry_json/reference_track_json artifacts", () => {
    const trialId = "trial-1";
    const artifacts: Artifact[] = [
      makeArtifact("a-legacy-trajectory", trialId, "trajectory_json", "/tmp/trajectory.json"),
      makeArtifact("a-telemetry", trialId, "telemetry_json", "/tmp/telemetry.json"),
      makeArtifact("a-ref", trialId, "reference_track_json", "/tmp/reference_track.json"),
    ];

    const selected = selectReplayArtifactsForTrial(artifacts, trialId);
    expect(selected.trajectory?.id).toBe("a-telemetry");
    expect(selected.telemetry?.id).toBe("a-telemetry");
    expect(selected.reference?.id).toBe("a-ref");
  });

  it("keeps compatibility with legacy trajectory_plot/reference_track names", () => {
    const trialId = "trial-legacy";
    const artifacts: Artifact[] = [
      makeArtifact("a-plot", trialId, "trajectory_plot", "/tmp/trajectory_plot.json"),
      makeArtifact("a-ref-legacy", trialId, "misc", "/tmp/reference_track.used.json"),
    ];

    const selected = selectReplayArtifactsForTrial(artifacts, trialId);
    expect(selected.trajectory?.id).toBe("a-plot");
    expect(selected.reference?.id).toBe("a-ref-legacy");
  });
});
