import type { Artifact } from "../types/api";

export interface ReplayArtifacts {
  trajectory: Artifact | null;
  telemetry: Artifact | null;
  reference: Artifact | null;
}

function looksLikeTrajectoryArtifact(artifact: Artifact): boolean {
  const token = `${artifact.artifact_type} ${artifact.display_name ?? ""} ${artifact.storage_path}`.toLowerCase();
  return (
    token.includes("trajectory") ||
    token.includes("telemetry") ||
    token.includes("reference_track") ||
    token.includes("reference-track")
  );
}

function isJsonArtifact(artifact: Artifact): boolean {
  return (
    artifact.mime_type === "application/json" ||
    artifact.storage_path.toLowerCase().endsWith(".json")
  );
}

function selectBestArtifact(candidates: Artifact[], terms: string[]): Artifact | null {
  for (const term of terms) {
    const hit = candidates.find((artifact) => {
      const text = `${artifact.artifact_type} ${artifact.display_name ?? ""} ${artifact.storage_path}`.toLowerCase();
      return text.includes(term);
    });
    if (hit) return hit;
  }
  return null;
}

export function selectReplayArtifactsForTrial(
  artifacts: Artifact[],
  trialId: string,
): ReplayArtifacts {
  const trialArtifacts = artifacts.filter(
    (artifact) => artifact.owner_type === "trial" && artifact.owner_id === trialId,
  );
  const replayCandidates = trialArtifacts.filter(
    (artifact) => looksLikeTrajectoryArtifact(artifact) && isJsonArtifact(artifact),
  );

  const trajectory = selectBestArtifact(replayCandidates, [
    "trajectory.json",
    "trajectory",
    "trajectory_samples",
    "trajectory_json",
  ]);
  const telemetry = selectBestArtifact(replayCandidates, [
    "telemetry.json",
    "telemetry",
    "telemetry_json",
  ]);
  const reference = selectBestArtifact(replayCandidates, [
    "reference_track.used.json",
    "reference_track",
    "reference",
  ]);

  return {
    trajectory,
    telemetry,
    reference,
  };
}
