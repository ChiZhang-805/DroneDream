import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TrajectoryReplay } from "../components/TrajectoryReplay";
import { apiClient } from "../api/client";
import type { Artifact } from "../types/api";

function makeArtifact(id: string, artifact_type: string, storage_path: string): Artifact {
  return {
    id,
    owner_type: "trial",
    owner_id: "trial_1",
    artifact_type,
    display_name: null,
    storage_path,
    mime_type: "application/json",
    file_size_bytes: 100,
    created_at: "2026-04-25T00:00:00Z",
  };
}

describe("TrajectoryReplay", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders replay svg and playback controls from sample artifacts", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: [
        { t: 0, x: 0, y: 0, z: 1 },
        { t: 1, x: 1, y: 1, z: 1 },
        { t: 2, x: 2, y: 1.5, z: 1 },
      ],
    });

    render(
      <TrajectoryReplay
        artifacts={{
          trajectory: makeArtifact("a1", "trajectory_json", "/tmp/trajectory.json"),
          telemetry: null,
          reference: null,
        }}
        meta={{ scenario: "nominal", candidate_id: "cand_1" }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("trajectory-replay")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(screen.getByLabelText("Trajectory replay")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("shows empty/error states gracefully for invalid samples", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: [
        { t: 0, x: "bad", y: 0, z: 1 },
        { t: 1, x: Number.NaN, y: Number.NaN, z: 1 },
      ],
    });

    render(
      <TrajectoryReplay
        artifacts={{
          trajectory: makeArtifact("a2", "trajectory", "/tmp/trajectory.json"),
          telemetry: null,
          reference: null,
        }}
        meta={{}}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText(/Replay data missing/i)).toBeInTheDocument(),
    );
  });

  it("shows empty state when artifact is not provided", async () => {
    render(
      <TrajectoryReplay
        artifacts={{ trajectory: null, telemetry: null, reference: null }}
        meta={{}}
      />,
    );

    expect(screen.getByText(/Replay unavailable/i)).toBeInTheDocument();
  });

  it("renders embedded reference_track from primary artifact payload", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: [
        { t: 0, x: 0, y: 0, z: 1 },
        { t: 1, x: 1, y: 1, z: 1 },
      ],
      reference_track: [
        { x: 0, y: 0, z: 1 },
        { x: 1.2, y: 1.1, z: 1 },
      ],
    });

    render(
      <TrajectoryReplay
        artifacts={{
          trajectory: makeArtifact("a3", "telemetry_json", "/tmp/telemetry.json"),
          telemetry: null,
          reference: null,
        }}
        meta={{}}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("trajectory-replay")).toBeInTheDocument(),
    );
    const canvas = screen.getByLabelText("Trajectory replay");
    expect(canvas.querySelectorAll("polyline")).toHaveLength(2);
  });
});
