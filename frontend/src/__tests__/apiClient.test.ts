import { describe, expect, it, vi, afterEach } from "vitest";

import { apiClient, ApiClientError, artifactDownloadUrl } from "../api/client";
import {
  ensureOverallDesktopReadiness,
  resetDesktopReadinessSession,
} from "../desktop/readiness";
import {
  approveDesktopStartupGateWithoutCloudAuth,
  resetDesktopStartupGateSession,
} from "../desktop/startupGate";
import { setAuthAccessToken } from "../features/auth/authTokenStore";

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
  vi.useRealTimers();
  vi.unstubAllEnvs();
  setAuthAccessToken(null);
  resetDesktopReadinessSession();
  resetDesktopStartupGateSession();
  delete window.__TAURI__;
  localStorage.clear();
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

  it("binds a continuation child request to the viewed parent control version", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { id: "job_child", status: "QUEUED" },
          error: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    await apiClient.continueExploration("job/parent", 7, {
      budget: {
        additional_generation_cap: 3,
        additional_trial_cap: 24,
        additional_provider_turn_cap: 8,
        additional_time_budget_seconds: 1800,
      },
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs/job%2Fparent/continue-exploration?control_version=7",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          budget: {
            additional_generation_cap: 3,
            additional_trial_cap: 24,
            additional_provider_turn_cap: 8,
            additional_time_budget_seconds: 1800,
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

  it("maps an oversized API response to a bounded client error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("{}", {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": String(64 * 1024 * 1024 + 1),
          },
        }),
      ),
    );

    await expect(
      apiClient.createJob({
        track_type: "circle",
        start_point: { x: 0, y: 0 },
        altitude_m: 3,
        wind: { north: 0, east: 0, south: 0, west: 0 },
        sensor_noise_level: "medium",
        objective_profile: "robust",
      }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      code: "RESPONSE_TOO_LARGE",
      httpStatus: 200,
      message: "Response exceeded the 64 MiB safety limit.",
    });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("preserves the oversized-response classification after a safe mutation retry", async () => {
    const fetchSpy = vi.fn()
      .mockRejectedValueOnce(new Error("response channel closed"))
      .mockResolvedValueOnce(
        new Response("{}", {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": String(64 * 1024 * 1024 + 1),
          },
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);

    await expect(
      apiClient.createJob({
        track_type: "circle",
        start_point: { x: 0, y: 0 },
        altitude_m: 3,
        wind: { north: 0, east: 0, south: 0, west: 0 },
        sensor_noise_level: "medium",
        objective_profile: "robust",
      }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      code: "RESPONSE_TOO_LARGE",
      httpStatus: 200,
      message: "Response exceeded the 64 MiB safety limit.",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("fails a browser request when response headers arrive but the body stalls", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream<Uint8Array>({
            pull: () => new Promise<void>(() => undefined),
          }),
        ),
      ),
    );

    const assertion = expect(apiClient.getJob("job_x")).rejects.toMatchObject({
      name: "ApiClientError",
      code: "NETWORK_ERROR",
      httpStatus: 0,
      message: "Request timed out after 120 seconds.",
    });
    await vi.advanceTimersByTimeAsync(120_000);
    await assertion;
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

  it("prefers the current cloud account token for authenticated API calls", async () => {
    setAuthAccessToken("cloud-session-token");
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { items: [], page: 1, page_size: 20, total: 0 },
          error: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    await apiClient.listJobs();

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/jobs",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer cloud-session-token",
        }),
      }),
    );
  });


  it("downloadArtifact sends Authorization header when configured", async () => {
    vi.useFakeTimers();
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
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();
    expect(anchorClickSpy).toHaveBeenCalledOnce();
    await vi.runAllTimersAsync();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock");
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/artifacts/art_1/download",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer demo-token" }),
      }),
    );
  });

  it("streams desktop artifact downloads through the native bridge", async () => {
    setAuthAccessToken("cloud-session-token");
    const invoke = vi.fn().mockResolvedValue({
      savedPath: "C:\\Users\\pilot\\Downloads\\telemetry.ulg",
      bytes: 70 * 1024 * 1024,
    });
    window.__TAURI__ = { core: { invoke } };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await apiClient.downloadArtifact("art_large_1", "telemetry.ulg");

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith("desktop_download_artifact", {
      request: {
        artifactId: "art_large_1",
        filename: "telemetry.ulg",
        accessToken: "cloud-session-token",
      },
    });
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

  it("uses the approved startup gate and performs one lightweight runtime probe before a real run", async () => {
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
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return desktopPrerequisites;
      if (command === "probe_runtime_status") return readyRuntime;
      if (command === "start_runtime") return readyRuntime;
      if (command === "desktop_api_request") {
        return {
          status: 200,
          contentType: "application/json",
          bodyBase64: btoa(JSON.stringify({
            success: true,
            data: { id: "job_1" },
            error: null,
          })),
        };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    await ensureOverallDesktopReadiness({ autoStart: true });
    approveDesktopStartupGateWithoutCloudAuth();
    invoke.mockClear();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await expect(apiClient.createJob({} as never)).resolves.toMatchObject({ id: "job_1" });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).toHaveBeenNthCalledWith(1, "probe_runtime_status", undefined);
    expect(invoke).toHaveBeenNthCalledWith(
      2,
      "desktop_api_request",
      expect.objectContaining({
        request: expect.objectContaining({
          method: "POST",
          path: "/api/v1/jobs",
        }),
      }),
    );
  });

  it("blocks a real run without a cached manual check and never probes automatically", async () => {
    const invoke = vi.fn(async () => undefined);
    const fetchSpy = vi.fn();
    window.__TAURI__ = { core: { invoke } };
    vi.stubGlobal("fetch", fetchSpy);

    await expect(apiClient.createJob({} as never)).rejects.toMatchObject({
      code: "DESKTOP_RUNTIME_NOT_READY",
      httpStatus: 0,
    });
    expect(invoke).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
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
      if (command === "desktop_api_request") {
        return {
          status: 200,
          contentType: "application/json",
          bodyBase64: btoa(JSON.stringify({
            success: true,
            data: { id: "job_1", display_name: "safe write" },
            error: null,
          })),
        };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await apiClient.updateJob(
      "job_1",
      { display_name: "safe write" },
      7,
    );

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledWith(
      "desktop_api_request",
      expect.objectContaining({
        request: expect.objectContaining({
          method: "PATCH",
          path: "/api/v1/jobs/job_1?control_version=7",
        }),
      }),
    );
  });

  it("retries an ambiguous desktop mutation once with the same idempotency key", async () => {
    const invoke = vi.fn()
      .mockRejectedValueOnce(new Error("response channel closed"))
      .mockResolvedValueOnce({
        status: 200,
        contentType: "application/json",
        bodyBase64: btoa(JSON.stringify({
          success: true,
          data: { id: "job_1", display_name: "safe retry" },
          error: null,
        })),
      });
    window.__TAURI__ = { core: { invoke } };

    await expect(
      apiClient.updateJob("job_1", { display_name: "safe retry" }, 7),
    ).resolves.toMatchObject({ id: "job_1", display_name: "safe retry" });

    expect(invoke).toHaveBeenCalledTimes(2);
    const firstRequest = invoke.mock.calls[0]?.[1]?.request;
    const secondRequest = invoke.mock.calls[1]?.[1]?.request;
    expect(firstRequest.idempotencyKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(secondRequest).toEqual(firstRequest);
  });

  it("forwards preference updates through the desktop bridge with PUT", async () => {
    const preferences = {
      schema_version: "1.0",
      saved: true,
      memory_enabled: true,
      locale: "en",
      default_template_key: "hover-basics@1",
      default_track_type: "hover",
      default_altitude_m: 4,
      retention_days: 90,
      stored_content: "allowlisted_preferences_and_verified_structured_job_outcomes_only",
      updated_at: "2026-08-12T00:00:00Z",
      deleted_memory_count: 0,
    };
    const invoke = vi.fn().mockResolvedValue({
      status: 200,
      contentType: "application/json",
      bodyBase64: btoa(JSON.stringify({ success: true, data: preferences, error: null })),
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(apiClient.updateUserExperiencePreferences({
      memory_enabled: true,
      locale: "en",
      default_template_key: "hover-basics@1",
      default_track_type: "hover",
      default_altitude_m: 4,
    })).resolves.toEqual(preferences);

    expect(invoke).toHaveBeenCalledWith(
      "desktop_api_request",
      expect.objectContaining({
        request: expect.objectContaining({
          method: "PUT",
          path: "/api/v1/preferences/experience",
        }),
      }),
    );
  });

  it("reuses an unresolved mutation key after an application restart boundary", async () => {
    const failedInvoke = vi.fn().mockRejectedValue(
      new Error("response channel closed"),
    );
    window.__TAURI__ = { core: { invoke: failedInvoke } };

    await expect(
      apiClient.updateJob("job_1", { display_name: "recover me" }, 7),
    ).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(failedInvoke).toHaveBeenCalledTimes(2);
    const unresolvedRequest = failedInvoke.mock.calls[0]?.[1]?.request;

    const recoveredInvoke = vi.fn().mockResolvedValue({
      status: 200,
      contentType: "application/json",
      bodyBase64: btoa(JSON.stringify({
        success: true,
        data: { id: "job_1", display_name: "recover me" },
        error: null,
      })),
    });
    // Replacing the native bridge models a fresh WebView process. Persistent
    // storage is the only state shared with the new request invocation.
    window.__TAURI__ = { core: { invoke: recoveredInvoke } };

    await expect(
      apiClient.updateJob("job_1", { display_name: "recover me" }, 7),
    ).resolves.toMatchObject({ id: "job_1", display_name: "recover me" });

    const recoveredRequest = recoveredInvoke.mock.calls[0]?.[1]?.request;
    expect(recoveredRequest.idempotencyKey).toBe(
      unresolvedRequest.idempotencyKey,
    );
    expect(
      localStorage.getItem("dronedream.api.pending-mutations.v1"),
    ).toBeNull();
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
