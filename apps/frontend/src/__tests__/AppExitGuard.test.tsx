import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { apiClient } from "../api/client";
import { AppShell } from "../AppShell";
import type { DesktopCloseRequestedEvent, DesktopWindowHandle } from "../desktop/bridge";
import { resetDesktopReadinessSession } from "../desktop/readiness";
import { EXPERIMENT_DRAFT_KEY } from "../features/experiment/draftStorage";
import { I18nProvider } from "../i18n/I18nProvider";
import type { Job, PaginatedJobs } from "../types/api";

let closeRequestedHandler: ((event: DesktopCloseRequestedEvent) => void | Promise<void>) | undefined;
let destroyWindow: ReturnType<typeof vi.fn<() => Promise<void>>>;
let invokeDesktop: ReturnType<typeof vi.fn<(command: string) => Promise<unknown>>>;

function installDesktopWindow(): void {
  destroyWindow = vi.fn(async () => undefined);
  invokeDesktop = vi.fn(async (command: string) => {
    if (command === "stop_runtime_for_exit") return null;
    throw new Error(`Unexpected desktop command: ${command}`);
  });
  const desktopWindow: DesktopWindowHandle = {
    onCloseRequested: vi.fn(async (handler) => {
      closeRequestedHandler = handler;
      return vi.fn();
    }),
    destroy: destroyWindow,
  };
  window.__TAURI__ = {
    core: { invoke: invokeDesktop },
    window: { getCurrentWindow: () => desktopWindow },
  };
}

function emptyJobs(total = 0): PaginatedJobs {
  return { items: [], page: 1, page_size: 100, total };
}

function renderShell(path: string): void {
  const router = createMemoryRouter([{
    path: "/",
    element: <AppShell />,
    children: [
      { path: "dashboard", element: <div>Dashboard content</div> },
      { path: "jobs/new", element: <div>Experiment wizard</div> },
      { path: "desktop/setup", element: <div>Environment setup</div> },
    ],
  }], { initialEntries: [path] });
  render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
}

async function requestWindowClose(): Promise<ReturnType<typeof vi.fn>> {
  await waitFor(() => expect(closeRequestedHandler).toBeTypeOf("function"));
  const preventDefault = vi.fn();
  await act(async () => {
    await closeRequestedHandler?.({ preventDefault });
  });
  return preventDefault;
}

describe("desktop close lifecycle", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_DESKTOP_VISUAL_QA", "true");
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    resetDesktopReadinessSession();
    closeRequestedHandler = undefined;
    installDesktopWindow();
    vi.spyOn(apiClient, "listJobs").mockResolvedValue(emptyJobs());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    delete window.__TAURI__;
  });

  it("closes without a confirmation dialog and preserves a redacted draft", async () => {
    window.sessionStorage.setItem(EXPERIMENT_DRAFT_KEY, JSON.stringify({
      schema_version: 3,
      saved_at: "2026-10-23T00:00:00.000Z",
      active_step: 2,
      completed_steps: [0, 1],
      form: { display_name: "Keep me", llm_api_key: "must-not-persist" },
      selections: {},
      conversation: {
        summary: "Keep only this compact summary.",
        field_provenance: {},
        messages: [{ id: "turn-private", role: "user", content: "must-not-persist-raw-chat" }],
      },
    }));
    renderShell("/jobs/new");

    const preventDefault = await requestWindowClose();

    expect(preventDefault).toHaveBeenCalledOnce();
    expect(document.querySelector(".app-exit-dialog")).toBeNull();
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain("Keep me");
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toContain("must-not-persist");
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
    expect(destroyWindow).toHaveBeenCalledOnce();
  });

  it("cancels active jobs, releases Runtime, then destroys the window", async () => {
    const activeJob = { id: "job-running", control_version: 7 } as Job;
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) => (
      params?.status === "RUNNING"
        ? { items: [activeJob], page: 1, page_size: 100, total: 1 }
        : emptyJobs()
    ));
    const cancelJob = vi.spyOn(apiClient, "cancelJob").mockResolvedValue({
      ...activeJob,
      status: "CANCELLED",
    });
    renderShell("/dashboard");

    await requestWindowClose();

    expect(cancelJob).toHaveBeenCalledWith("job-running", 7);
    expect(cancelJob.mock.invocationCallOrder[0]).toBeLessThan(invokeDesktop.mock.invocationCallOrder[0]);
    expect(invokeDesktop.mock.invocationCallOrder[0]).toBeLessThan(destroyWindow.mock.invocationCallOrder[0]);
  });

  it("enumerates every active-job page before closing", async () => {
    const activeJobs = Array.from({ length: 101 }, (_, index) => ({
      id: `job-running-${index + 1}`,
      control_version: index + 1,
    } as Job));
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) => {
      if (params?.status !== "RUNNING") return emptyJobs();
      const page = params.page ?? 1;
      const start = (page - 1) * 100;
      return { items: activeJobs.slice(start, start + 100), page, page_size: 100, total: activeJobs.length };
    });
    const cancelJob = vi.spyOn(apiClient, "cancelJob").mockImplementation(async (jobId) => ({
      ...activeJobs.find((job) => job.id === jobId)!,
      status: "CANCELLED",
    } as Job));
    renderShell("/dashboard");

    await requestWindowClose();

    expect(apiClient.listJobs).toHaveBeenCalledWith({ page: 2, page_size: 100, status: "RUNNING" });
    expect(cancelJob).toHaveBeenCalledTimes(101);
    expect(destroyWindow).toHaveBeenCalledOnce();
  });

  it("still closes when active-job discovery is unavailable", async () => {
    vi.mocked(apiClient.listJobs).mockRejectedValue(new Error("Runtime unavailable"));
    renderShell("/dashboard");

    await requestWindowClose();

    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
    expect(destroyWindow).toHaveBeenCalledOnce();
  });

  it("does not query jobs while closing from the launcher", async () => {
    renderShell("/desktop/setup");

    await requestWindowClose();

    expect(apiClient.listJobs).not.toHaveBeenCalled();
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
    expect(destroyWindow).toHaveBeenCalledOnce();
  });
});
