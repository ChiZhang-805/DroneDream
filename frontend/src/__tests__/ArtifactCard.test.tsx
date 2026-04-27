import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import { ArtifactCard } from "../components/ArtifactCard";
import type { Artifact } from "../types/api";

function makeArtifact(): Artifact {
  return {
    id: "art-json-1",
    owner_type: "trial",
    owner_id: "trial-1",
    artifact_type: "telemetry_json",
    display_name: "Telemetry",
    storage_path: "/tmp/telemetry.json",
    mime_type: "application/json",
    file_size_bytes: 120,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("ArtifactCard", () => {
  it("shows schema_version when JSON artifact can be read", async () => {
    vi.spyOn(apiClient, "fetchArtifactJson").mockResolvedValue({
      schema_version: "dronedream.telemetry.v1",
    });

    render(<ArtifactCard artifact={makeArtifact()} />);

    await waitFor(() => {
      expect(screen.getByText("schema: dronedream.telemetry.v1")).toBeInTheDocument();
    });
  });
});
