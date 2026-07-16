import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

  it("keeps the actual trajectory usable when an optional reference fails", async () => {
    const reference = {
      ...buildArtifacts().trajectory!,
      id: "art-reference",
      artifact_type: "reference_track_json",
      display_name: "reference.json",
    };
    vi.spyOn(apiClient, "fetchArtifactJson")
      .mockResolvedValueOnce({
        samples: [
          { t: 0, x: 0, y: 0, z: 0 },
          { t: 1, x: 1, y: 1, z: 1 },
        ],
      })
      .mockRejectedValueOnce(new Error("reference unavailable"));

    render(
      <TrajectoryReplay
        artifacts={buildArtifacts({ reference })}
        meta={{}}
      />,
    );

    expect(await screen.findByTestId("trajectory-replay")).toBeInTheDocument();
    expect(screen.getByText("Reference track unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Replay failed")).not.toBeInTheDocument();
  });

  it("applies playback speed once rather than multiplying both step and timer", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      samples: Array.from({ length: 8 }, (_, index) => ({
        t: index,
        x: index,
        y: index,
        z: index,
      })),
    });

    render(<TrajectoryReplay artifacts={buildArtifacts()} meta={{}} />);
    await screen.findByTestId("trajectory-replay");

    fireEvent.change(screen.getByLabelText("Replay speed"), {
      target: { value: "4" },
    });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    act(() => vi.advanceTimersByTime(56));

    expect(screen.getByLabelText("Replay position")).toHaveValue("1");
    vi.useRealTimers();
  });
});
