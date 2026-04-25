import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ArtifactCard } from "../components/ArtifactCard";
import type { Artifact } from "../types/api";

const artifact: Artifact = {
  id: "art_1",
  owner_type: "trial",
  owner_id: "tri_1",
  artifact_type: "telemetry_json",
  display_name: "Telemetry",
  storage_path:
    "/workspace/dd_artifacts/jobs/job_xxx/trials/tri_xxx/some/deep/nested/location/telemetry.json",
  mime_type: "application/json",
  file_size_bytes: 123,
  created_at: "2026-04-22T09:00:40Z",
};

describe("ArtifactCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a basename-focused card and supports clipboard copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<ArtifactCard artifact={artifact} />);

    expect(screen.getByText("Telemetry")).toBeInTheDocument();
    expect(screen.getByText("telemetry.json")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /copy path/i }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(artifact.storage_path),
    );
  });

  it("falls back gracefully when navigator.clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    const execCopy = vi.fn().mockReturnValue(false);
    Object.defineProperty(document, "execCommand", {
      value: execCopy,
      configurable: true,
    });

    render(<ArtifactCard artifact={artifact} />);
    fireEvent.click(screen.getByRole("button", { name: /copy path/i }));

    await waitFor(() => expect(execCopy).toHaveBeenCalledWith("copy"));
    expect(await screen.findByText(/copy unavailable/i)).toBeInTheDocument();
  });
});
