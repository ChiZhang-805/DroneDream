import { afterEach, describe, expect, it, vi } from "vitest";

import type { SystemPrerequisiteReport } from "../desktop/bridge";
import {
  isTransientSystemProbeTimeout,
  probeSystemPrerequisitesWithStartupGrace,
  runSystemProbeWithStartupGrace,
} from "../desktop/prerequisiteProbe";

const report: SystemPrerequisiteReport = {
  platform: "windows",
  supported: true,
  windows: {
    caption: "Windows 11 Pro",
    version: "10.0.26100",
    buildNumber: "26100",
    architecture: "64-bit",
  },
  wsl: { executableAvailable: true, distributions: [] },
  memory: { totalBytes: 32 * 1024 ** 3, availableBytes: 16 * 1024 ** 3 },
  disks: [],
  gpus: [],
  probeErrors: [],
};

afterEach(() => {
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("system prerequisite startup grace", () => {
  it("recognizes native timeout diagnostics without treating other failures as transient", () => {
    expect(isTransientSystemProbeTimeout(
      new Error("read-only system probe timed out after 40 seconds."),
    )).toBe(true);
    expect(isTransientSystemProbeTimeout("probe timeout while Windows was starting"))
      .toBe(true);
    expect(isTransientSystemProbeTimeout(new Error("invalid prerequisite JSON")))
      .toBe(false);
  });

  it("keeps retrying a transient timeout inside the startup grace window", async () => {
    const firstTimeout = new Error(
      "read-only system probe timed out after 40 seconds.",
    );
    const probe = vi.fn()
      .mockRejectedValueOnce(firstTimeout)
      .mockResolvedValue(report);
    const wait = vi.fn(async () => undefined);

    await expect(runSystemProbeWithStartupGrace(probe, {
      maxAttempts: 3,
      retryDelaysMs: [1_000, 2_000],
      wait,
    })).resolves.toBe(report);

    expect(probe).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledOnce();
    expect(wait).toHaveBeenCalledWith(1_000);
  });

  it("reports only after the consecutive timeout threshold is exhausted", async () => {
    const errors = [1, 2, 3].map((attempt) =>
      new Error(`read-only system probe timed out on attempt ${attempt}`)
    );
    const probe = vi.fn()
      .mockRejectedValueOnce(errors[0])
      .mockRejectedValueOnce(errors[1])
      .mockRejectedValueOnce(errors[2]);
    const wait = vi.fn(async () => undefined);

    await expect(runSystemProbeWithStartupGrace(probe, {
      maxAttempts: 3,
      retryDelaysMs: [1_000, 2_000],
      wait,
    })).rejects.toBe(errors[2]);

    expect(probe).toHaveBeenCalledTimes(3);
    expect(wait.mock.calls).toEqual([[1_000], [2_000]]);
  });

  it("fails fast for a deterministic probe error", async () => {
    const error = new Error("The system probe returned invalid UTF-8.");
    const probe = vi.fn().mockRejectedValue(error);
    const wait = vi.fn(async () => undefined);

    await expect(runSystemProbeWithStartupGrace(probe, {
      maxAttempts: 3,
      retryDelaysMs: [1_000, 2_000],
      wait,
    })).rejects.toBe(error);

    expect(probe).toHaveBeenCalledOnce();
    expect(wait).not.toHaveBeenCalled();
  });

  it("shares one native probe sequence across concurrent startup callers", async () => {
    let resolveProbe!: (value: SystemPrerequisiteReport) => void;
    const pending = new Promise<SystemPrerequisiteReport>((resolve) => {
      resolveProbe = resolve;
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return pending;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const first = probeSystemPrerequisitesWithStartupGrace();
    const second = probeSystemPrerequisitesWithStartupGrace();

    expect(second).toBe(first);
    expect(invoke).toHaveBeenCalledTimes(1);
    resolveProbe(report);
    await expect(Promise.all([first, second])).resolves.toEqual([report, report]);

    await expect(probeSystemPrerequisitesWithStartupGrace()).resolves.toEqual(report);
    expect(invoke).toHaveBeenCalledTimes(2);
  });
});
