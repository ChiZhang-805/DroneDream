import { describe, expect, it, vi, afterEach } from "vitest";

import { apiClient, ApiClientError } from "../api/client";

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
});
