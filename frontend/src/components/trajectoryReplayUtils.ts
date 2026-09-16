import type { Artifact } from "../types/api";

export interface ReplayArtifacts {
  trajectory: Artifact | null;
  telemetry: Artifact | null;
  reference: Artifact | null;
}

/** Parents describe storage location, never whether this file is measured or reference data. */
function artifactLabels(artifact: Artifact): string[] {
  const filename = artifact.storage_path.split(/[\\/]/u).at(-1) ?? "";
  return [artifact.artifact_type, filename, artifact.display_name ?? ""].map((value) => value.toLowerCase());
}

/** Candidate discovery is a display heuristic; payload schema validation still happens on load. */
function looksLikeTrajectoryArtifact(artifact: Artifact): boolean {
  const token = artifactLabels(artifact).join(" ");
  return (
    token.includes("trajectory") ||
    token.includes("telemetry") ||
    token.includes("reference_track") ||
    token.includes("reference-track")
  );
}

/** Accept MIME metadata or the legacy filename suffix, without treating either as validated JSON. */
function isJsonArtifact(artifact: Artifact): boolean {
  return (
    artifact.mime_type === "application/json" ||
    artifact.storage_path.toLowerCase().endsWith(".json")
  );
}

/** Prefer explicit artifact type, then basename, then user-facing names, preserving term priority. */
function selectBestArtifact(candidates: Artifact[], terms: string[]): Artifact | null {
  for (let field = 0; field < 3; field += 1) {
    for (const term of terms) {
      const hit = candidates.find((artifact) => artifactLabels(artifact)[field].includes(term));
      if (hit) return hit;
    }
  }
  return null;
}

/** Explicit measured types outrank a descriptive name such as "reference tracking telemetry". */
function isReferenceArtifact(artifact: Artifact): boolean {
  const labels = artifactLabels(artifact);
  if (labels[0].includes("reference")) return true;
  if (labels[0].includes("telemetry") || labels[0].includes("trajectory")) return false;
  return labels.slice(1).some((label) => label.includes("reference"));
}

/** Keep a trial's intended reference separate from its observed motion; never select another owner. */
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

  // A reference trace can describe an ideal trajectory but is not proof that the
  // aircraft flew it. Its label must never be a fallback for measured replay.
  const measuredCandidates = replayCandidates.filter((artifact) => !isReferenceArtifact(artifact));
  const trajectory = selectBestArtifact(measuredCandidates, [
    "telemetry_json",
    "telemetry.json",
    "trajectory_plot",
    "trajectory.json",
    "trajectory",
    "trajectory_samples",
    "trajectory_json",
  ]);
  const telemetry = selectBestArtifact(measuredCandidates, [
    "telemetry_json",
    "telemetry.json",
    "telemetry",
    "trajectory_plot",
  ]);
  const reference = selectBestArtifact(replayCandidates, [
    "reference_track_json",
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
