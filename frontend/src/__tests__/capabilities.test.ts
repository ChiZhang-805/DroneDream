import { describe, expect, it } from "vitest";

import { runtimeCapabilityErrors } from "../features/experiment/capabilities";
import type { BackendCapabilitiesResponse } from "../types/api";

function capabilities(
  realCliReady: boolean,
  gptReady: boolean,
): BackendCapabilitiesResponse {
  return {
    service_version: "0.1.0",
    simulators: {
      configuration_scope: "api_process",
      authoritative: false,
      worker_override: null,
      worker_override_supported: true,
      items: {
        mock: { ready: true, status: "available" },
        real_cli: {
          ready: realCliReady,
          status: realCliReady ? "configured" : "not_configured",
          reason: realCliReady ? null : "Configure REAL_SIMULATOR_COMMAND",
        },
      },
    },
    optimizers: {
      configuration_scope: "api_process",
      authoritative: false,
      items: {
        heuristic: { ready: true, status: "available" },
        gpt: {
          ready: gptReady,
          status: gptReady ? "available" : "server_secret_not_configured",
        },
        llm_harness: {
          ready: gptReady,
          status: gptReady ? "experimental" : "server_secret_not_configured",
          reason: gptReady ? null : "Harness model access is not configured",
        },
      },
    },
    parameter_catalog: {
      catalog_version: "px4-mc-v3",
      supported_px4_versions: ["v1.16"],
    },
  };
}

describe("runtimeCapabilityErrors", () => {
  it("blocks unavailable real simulation and GPT before queueing", () => {
    const discovered = capabilities(false, false);
    discovered.simulators.authoritative = true;
    expect(runtimeCapabilityErrors("real_cli", "gpt", discovered)).toEqual({
      simulator_backend: "Configure REAL_SIMULATOR_COMMAND",
      optimizer_strategy:
        "The backend secret store is not configured for GPT optimization",
    });
  });

  it("does not block ready or local-only workflows", () => {
    expect(runtimeCapabilityErrors("real_cli", "gpt", capabilities(true, true))).toEqual({});
    expect(runtimeCapabilityErrors("mock", "llm_harness", capabilities(true, true))).toEqual({});
    expect(runtimeCapabilityErrors("mock", "heuristic", capabilities(false, false))).toEqual({});
    expect(runtimeCapabilityErrors("real_cli", "gpt", null)).toEqual({});
    expect(runtimeCapabilityErrors("real_cli", "heuristic", capabilities(false, true))).toEqual({});
  });

  it("uses the selected model optimizer capability instead of GPT metadata", () => {
    expect(runtimeCapabilityErrors("mock", "llm_harness", capabilities(true, false))).toEqual({
      optimizer_strategy: "Harness model access is not configured",
    });
  });

  it("fails closed when a discovered capability contract omits selected items", () => {
    const malformed = capabilities(true, true);
    malformed.simulators.authoritative = true;
    delete malformed.simulators.items.real_cli;
    delete malformed.optimizers.items.gpt;

    expect(runtimeCapabilityErrors("real_cli", "gpt", malformed)).toEqual({
      simulator_backend: "The real simulator runtime is not ready",
      optimizer_strategy:
        "The backend secret store is not configured for GPT optimization",
    });
  });
});
