import { describe, expect, it, vi, afterEach } from "vitest";

import { apiClient, ApiClientError, artifactDownloadUrl } from "../api/client";

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiClient envelope handling", () => {
  it("builds artifact download URLs from VITE_API_BASE_URL", () => {
    expect(artifactDownloadUrl("art_abc")).toBe(
      "http://127.0.0.1:8000/api/v1/artifacts/art_abc/download",
    );
  });

  it("unwraps the success envelope's data field", async () => {
    mockFetchOnce({
      success: true,
      data: { id: "job_abc123", job_id: "job_abc123", status: "QUEUED" },
      error: null,
    });

    const job = await apiClient.createJob({
      track_type: "circle",
      start_point: { x: 0, y: 0 },
      altitude_m: 3,
      wind: { north: 0, east: 0, south: 0, west: 0 },
      sensor_noise_level: "medium",
      objective_profile: "robust",
    });

    expect(job.id).toBe("job_abc123");
    expect(job.status).toBe("QUEUED");
  });

  it("throws ApiClientError with the server-provided code on a structured error envelope", async () => {
    mockFetchOnce(
      {
        success: false,
        data: null,
        error: {
          code: "INVALID_INPUT",
          message: "altitude_m must be between 1.0 and 20.0",
          details: null,
        },
      },
      422,
    );

    await expect(
      apiClient.createJob({
        track_type: "circle",
        start_point: { x: 0, y: 0 },
        altitude_m: 25,
        wind: { north: 0, east: 0, south: 0, west: 0 },
        sensor_noise_level: "medium",
        objective_profile: "robust",
      }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      code: "INVALID_INPUT",
      httpStatus: 422,
    });
  });

  it("produces an ApiClientError for non-JSON responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>oops</html>", {
          status: 500,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    await expect(apiClient.getJob("job_x")).rejects.toBeInstanceOf(
      ApiClientError,
    );
  });

  it("fetchArtifactJson uses artifact download URL and parses JSON", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ samples: [{ t: 0, x: 0, y: 0, z: 1 }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const data = await apiClient.fetchArtifactJson<{ samples: Array<{ t: number }> }>(
      "art_json_1",
    );
    expect(data.samples[0].t).toBe(0);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/artifacts/art_json_1/download",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("fetchArtifactJson throws useful error on parse failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    );
    await expect(apiClient.fetchArtifactJson("art_not_json")).rejects.toMatchObject({
      code: "ARTIFACT_NOT_JSON",
    });
  });
});
