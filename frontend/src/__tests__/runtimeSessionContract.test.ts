import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuntimeStatusReport } from "../desktop/bridge";
import {
  runtimeSessionContractFailure,
  verifyRuntimeSessionContract,
} from "../desktop/runtimeSessionContract";

const readyRuntime: RuntimeStatusReport = {
  runtimeName: "DroneDreamRuntime",
  installed: true,
  running: true,
  ready: true,
  version: "0.1.0-beta.2",
  dataRoot: "E:\\DroneDream",
  components: [
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
  })),
  diagnostics: [],
};

function base64Json(value: unknown): string {
  return btoa(JSON.stringify(value));
}

function installResponse(status: number, body: unknown) {
  const invoke = vi.fn(async (command: string) => {
    if (command !== "desktop_api_request") {
      throw new Error(`Unexpected command: ${command}`);
    }
    return {
      status,
      contentType: "application/json",
      bodyBase64: base64Json(body),
    };
  });
  window.__TAURI__ = { core: { invoke } };
  return invoke;
}

afterEach(() => {
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("desktop Runtime account-session contract", () => {
  it("accepts a structured anonymous 401 as proof that the protected route exists", async () => {
    const invoke = installResponse(401, {
      success: false,
      data: null,
      error: { code: "UNAUTHORIZED", message: "Missing bearer token", details: null },
    });

    const report = await verifyRuntimeSessionContract(readyRuntime);

    expect(report.ready).toBe(true);
    expect(runtimeSessionContractFailure(report)).toBeNull();
    expect(report.components).toContainEqual(expect.objectContaining({
      id: "account-session-api",
      status: "ready",
      required: true,
    }));
    expect(invoke).toHaveBeenCalledWith("desktop_api_request", {
      request: {
        method: "GET",
        path: "/api/v1/session",
        body: null,
        accessToken: null,
        accept: "application/json",
        idempotencyKey: null,
      },
    });
  });

  it("classifies a structured 404 as an outdated Runtime and fails readiness closed", async () => {
    installResponse(404, {
      success: false,
      data: null,
      error: { code: "NOT_FOUND", message: "Not Found", details: null },
    });

    const report = await verifyRuntimeSessionContract(readyRuntime);

    expect(report.ready).toBe(false);
    expect(runtimeSessionContractFailure(report)).toBe("runtime_session_api_missing");
    expect(report.diagnostics).toContain("runtime_session_api_missing");
  });

  it("classifies the legacy bare FastAPI Not Found response as an outdated Runtime", async () => {
    installResponse(404, { detail: "Not Found" });

    const report = await verifyRuntimeSessionContract(readyRuntime);

    expect(report.ready).toBe(false);
    expect(runtimeSessionContractFailure(report)).toBe("runtime_session_api_missing");
  });

  it("does not mistake an unexpected response or bridge failure for compatibility", async () => {
    installResponse(500, {
      success: false,
      data: null,
      error: { code: "INTERNAL_ERROR", message: "failure", details: null },
    });
    const report = await verifyRuntimeSessionContract(readyRuntime);
    expect(report.ready).toBe(false);
    expect(runtimeSessionContractFailure(report))
      .toBe("runtime_session_api_unavailable");
  });

  it("does not probe an environment that is not otherwise ready", async () => {
    const invoke = installResponse(401, {});
    const report = await verifyRuntimeSessionContract({
      ...readyRuntime,
      running: false,
      ready: false,
    });
    expect(report.components).toHaveLength(6);
    expect(invoke).not.toHaveBeenCalled();
  });
});
