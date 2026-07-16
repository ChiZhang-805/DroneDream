import { describe, expect, it, vi, afterEach } from "vitest";

import { apiClient, ApiClientError, artifactDownloadUrl } from "../api/client";
import {
  ensureOverallDesktopReadiness,
  resetDesktopReadinessSession,
} from "../desktop/readiness";

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

const desktopPrerequisites = {
  platform: "windows",
  supported: true,
  windows: {
    caption: "Windows 11 Pro",
    version: "10.0.26100",
    buildNumber: "26100",
    architecture: "64-bit",
  },
  wsl: { executableAvailable: true, distributions: [] },
  memory: { totalBytes: 16 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
  disks: [],
  gpus: [],
  probeErrors: [],
};

const runtimeComponents = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
].map((id) => ({
  id,
  label: id,
  status: "ready",
  required: true,
  version: null,
  detail: null,
}));

afterEach(() => {
  resetDesktopReadinessSession();
  delete window.__TAURI__;
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

  it("preserves provider-neutral LLM credentials when rerunning a job", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { id: "job_rerun_1", status: "QUEUED" },
          error: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    await apiClient.rerunJob("job/source", {
      llm: {
        provider: "deepseek",
        api_key: "secret-token",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com/v1",
      },
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs/job%2Fsource/rerun",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          llm: {
            provider: "deepseek",
            api_key: "secret-token",
            model: "deepseek-chat",
            base_url: "https://api.deepseek.com/v1",
          },
        }),
      }),
    );
  });

  it("loads runtime capability preflight metadata", async () => {
    mockFetchOnce({
      success: true,
      data: {
        service_version: "0.1.0",
        simulators: {
          configuration_scope: "api_process",
          authoritative: false,
          worker_override: null,
          worker_override_supported: true,
          items: { mock: { ready: true, status: "available" } },
        },
        optimizers: {
          authoritative: true,
          items: { heuristic: { ready: true, status: "available" } },
        },
        parameter_catalog: {
          catalog_version: "px4-mc-v3",
          supported_px4_versions: ["v1.16"],
        },
      },
      error: null,
    });

    const capabilities = await apiClient.getCapabilities();

    expect(capabilities.simulators.items.mock.ready).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/capabilities",
      expect.any(Object),
    );
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

  it("does not accept a success envelope carried by an HTTP error response", async () => {
    mockFetchOnce(
      {
        success: true,
        data: { id: "job_should_not_exist", status: "QUEUED" },
        error: null,
      },
      503,
    );

    await expect(apiClient.getJob("job_x")).rejects.toMatchObject({
      name: "ApiClientError",
      code: "HTTP_ERROR",
      httpStatus: 503,
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

  it("adds Authorization header when VITE_DEMO_AUTH_TOKEN is configured", async () => {
    vi.stubEnv("VITE_DEMO_AUTH_TOKEN", "demo-token");
    vi.resetModules();
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { items: [], page: 1, page_size: 20, total: 0 },
          error: null,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const mod = await import("../api/client");
    await mod.apiClient.listJobs();
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer demo-token",
        }),
      }),
    );
  });


  it("downloadArtifact sends Authorization header when configured", async () => {
    vi.stubEnv("VITE_DEMO_AUTH_TOKEN", "demo-token");
    vi.resetModules();
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response("file-bytes", {
        status: 200,
        headers: { "Content-Type": "application/octet-stream" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock");
    const revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const mod = await import("../api/client");
    await mod.apiClient.downloadArtifact("art_1", "file.txt");
    expect(createObjectURLSpy).toHaveBeenCalled();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock");
    expect(anchorClickSpy).toHaveBeenCalledOnce();
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/artifacts/art_1/download",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer demo-token" }),
      }),
    );
  });

  it("compareJobs posts job_ids payload", async () => {
    mockFetchOnce({
      success: true,
      data: { items: [] },
      error: null,
    });
    await apiClient.compareJobs(["job_1", "job_2"]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs/compare",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ job_ids: ["job_1", "job_2"] }),
      }),
    );
  });

  it("loads every bounded trial page without returning duplicates", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) => ({
      id: `trial_${index}`,
    }));
    const secondPage = [{ id: "trial_500" }];
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ success: true, data: firstPage, error: null }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ success: true, data: secondPage, error: null }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchSpy);

    const trials = await apiClient.listJobTrials("job with spaces");

    expect(trials).toHaveLength(501);
    expect(new Set(trials.map((trial) => trial.id)).size).toBe(501);
    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/jobs/job%20with%20spaces/trials?page=1&page_size=500",
      expect.any(Object),
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/jobs/job%20with%20spaces/trials?page=2&page_size=500",
      expect.any(Object),
    );
  });

  it("uses only a lightweight Runtime probe before a real run and blocks stale health", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const readyRuntime = {
      runtimeName: "DroneDreamRuntime",
      installed: true,
      running: true,
      ready: true,
      version: "2026.07",
      dataRoot: "E:\\DroneDream",
      components: runtimeComponents,
      diagnostics: [] as string[],
    };
    const unhealthyRuntime = {
      ...readyRuntime,
      ready: false,
      components: runtimeComponents.map((component) =>
        component.id === "local-backend"
          ? { ...component, status: "unhealthy" }
          : component,
      ),
      diagnostics: ["Backend stopped after the page was opened."],
    };
    let runtime = readyRuntime;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return desktopPrerequisites;
      if (command === "probe_runtime_status") return runtime;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    await ensureOverallDesktopReadiness({ autoStart: true });
    invoke.mockClear();
    runtime = unhealthyRuntime;

    await expect(apiClient.createJob({} as never))
      .rejects.toMatchObject({
        code: "DESKTOP_RUNTIME_NOT_READY",
        httpStatus: 0,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(invoke.mock.calls.map(([command]) => command)).toEqual(["probe_runtime_status"]);
  });

  it("does not recheck the environment for metadata-only mutations", async () => {
    const readyRuntime = {
      runtimeName: "DroneDreamRuntime",
      installed: true,
      running: true,
      ready: true,
      version: "2026.07",
      dataRoot: "E:\\DroneDream",
      components: runtimeComponents,
      diagnostics: [],
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return desktopPrerequisites;
      if (command === "probe_runtime_status") return readyRuntime;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    mockFetchOnce({
      success: true,
      data: { id: "job_1", display_name: "safe write" },
      error: null,
    });

    await apiClient.updateJob("job_1", { display_name: "safe write" });

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("loads the versioned parameter catalog from the advanced endpoint", async () => {
    mockFetchOnce({
      success: true,
      data: {
        catalog_version: "catalog-v1",
        source: "PX4 snapshot",
        px4_version: "v1.16",
        supported_px4_versions: ["v1.16"],
        vehicle_type: "multicopter",
        parameter_count: 0,
        parameters: [],
      },
      error: null,
    });
    await apiClient.getParameterCatalog("v1.16");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/parameter-catalog?px4_version=v1.16",
      expect.any(Object),
    );
  });

  it("normalizes comparison CSV network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await expect(
      apiClient.downloadCompareJobsCsv(["job_a", "job_b"]),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      code: "NETWORK_ERROR",
      httpStatus: 0,
    });
  });

  it("loads constraint-aware candidate and Pareto history for a job", async () => {
    mockFetchOnce({
      success: true,
      data: {
        items: [],
        pareto_candidate_ids: [],
        recommendations: {},
        objective_directions: {},
      },
      error: null,
    });
    await apiClient.listJobCandidates("job advanced/1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs/job%20advanced%2F1/candidates",
      expect.any(Object),
    );
  });
});
