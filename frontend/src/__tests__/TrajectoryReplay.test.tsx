import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TrajectoryReplay } from "../components/TrajectoryReplay";
import { apiClient } from "../api/client";
import type { ReplayArtifacts } from "../components/trajectoryReplayUtils";

function buildArtifacts(overrides: Partial<ReplayArtifacts> = {}): ReplayArtifacts {
  return {
    trajectory: {
      id: "art-trajectory",
      owner_type: "trial",
      owner_id: "trial-1",
      artifact_type: "telemetry_json",
      display_name: "telemetry.json",
      storage_path: "/tmp/telemetry.json",
      mime_type: "application/json",
      file_size_bytes: 123,
      created_at: "2026-04-27T10:00:00Z",
    },
    telemetry: null,
    reference: null,
    ...overrides,
  };
}

describe("TrajectoryReplay", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to 2D view", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: [
        { t: 0, x: 0, y: 0, z: 0 },
        { t: 1, x: 1, y: 1, z: 0.5 },
      ],
    });

    render(<TrajectoryReplay artifacts={buildArtifacts()} meta={{ scenario: "nominal" }} />);

    await waitFor(() =>
      expect(screen.getByTestId("trajectory-replay-svg-2d")).toBeInTheDocument(),
    );
  });

  it("switches to 3D view after selecting it", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: [
        { t: 0, x: 0, y: 0, z: 0 },
        { t: 1, x: 2, y: 1, z: 3 },
      ],
    });

    render(<TrajectoryReplay artifacts={buildArtifacts()} meta={{}} />);

    await waitFor(() =>
      expect(screen.getByTestId("trajectory-replay-svg-2d")).toBeInTheDocument(),
    );

    const select = screen.getByLabelText("Replay view mode");
    fireEvent.change(select, { target: { value: "3d" } });

    await waitFor(() =>
      expect(screen.getByTestId("trajectory-replay-svg-3d")).toBeInTheDocument(),
    );
  });

  it("shows empty state when artifacts are missing", async () => {
    render(
      <TrajectoryReplay
        artifacts={{ trajectory: null, telemetry: null, reference: null }}
        meta={{}}
      />,
    );
    expect(screen.getByText("Replay unavailable")).toBeInTheDocument();
  });
});
