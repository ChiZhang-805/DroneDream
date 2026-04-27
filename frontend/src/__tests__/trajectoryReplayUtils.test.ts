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
