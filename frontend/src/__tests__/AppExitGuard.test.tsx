import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { apiClient } from "../api/client";
import { AppShell } from "../AppShell";
import type {
  DesktopCloseRequestedEvent,
  DesktopWindowHandle,
} from "../desktop/bridge";
import { resetDesktopReadinessSession } from "../desktop/readiness";
import { EXPERIMENT_DRAFT_KEY } from "../features/experiment/draftStorage";
import { I18nProvider } from "../i18n/I18nProvider";
import type { Job, PaginatedJobs } from "../types/api";

let closeRequestedHandler:
  | ((event: DesktopCloseRequestedEvent) => void | Promise<void>)
  | undefined;
let destroyWindow: () => Promise<void>;
let invokeDesktop: (
  command: string,
  args?: Record<string, unknown>,
) => Promise<unknown>;

function installDesktopWindow(): void {
  destroyWindow = vi.fn(async () => undefined);
  invokeDesktop = vi.fn(async () => {
    throw new Error("No automatic probe expected.");
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
  return { items: [], page: 1, page_size: 1, total };
}

function renderShell(path: string): void {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppShell />,
      children: [
        { path: "dashboard", element: <div>Dashboard content</div> },
        { path: "jobs/new", element: <div>Blank experiment wizard</div> },
        { path: "desktop/setup", element: <div>Environment setup</div> },
      ],
    },
  ], { initialEntries: [path] });
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
  expect(preventDefault).toHaveBeenCalledTimes(1);
  return preventDefault;
}

describe("desktop close protection", () => {
  beforeEach(() => {
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
    delete window.__TAURI__;
  });

  it("treats a blank new-experiment page as a disposable draft and lets the user return", async () => {
    renderShell("/jobs/new");

    await requestWindowClose();
    expect(screen.getByRole("dialog", { name: "Before you close DroneDream" })).toBeVisible();
    expect(screen.getByText(/five-step draft/i)).toBeVisible();
    expect(destroyWindow).not.toHaveBeenCalled();
    expect(invokeDesktop).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Return to DroneDream" }));
    expect(screen.queryByRole("dialog", { name: "Before you close DroneDream" })).toBeNull();
    expect(destroyWindow).not.toHaveBeenCalled();
  });

  it("persists the redacted current-session draft before explicit exit confirmation", async () => {
    window.sessionStorage.setItem(EXPERIMENT_DRAFT_KEY, JSON.stringify({
      schema_version: 3,
      saved_at: "2026-07-26T00:00:00.000Z",
      active_step: 2,
      completed_steps: [0, 1],
      form: { display_name: "Keep me", llm_api_key: "must-not-persist" },
      selections: {},
      conversation: null,
    }));
    renderShell("/dashboard");

    await requestWindowClose();
    expect(screen.getByText(/redacted draft is saved/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Exit and keep draft" }));

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toBeNull();
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain("Keep me");
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toContain(
      "must-not-persist",
    );
    expect(invokeDesktop).not.toHaveBeenCalled();
  });

  it("warns about active experiment jobs without running an environment probe", async () => {
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) =>
      emptyJobs(params?.status === "RUNNING" ? 2 : 0)
    );
    renderShell("/dashboard");

    await requestWindowClose();

    expect(screen.getByText(/2 active experiment jobs/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Exit anyway" })).toBeVisible();
    expect(destroyWindow).not.toHaveBeenCalled();
    expect(invokeDesktop).not.toHaveBeenCalled();
  });

  it("best-effort cancels known active jobs before destroying the window", async () => {
    const activeJob = { id: "job-running" } as Job;
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) => (
      params?.status === "RUNNING"
        ? {
            items: [activeJob],
            page: 1,
            page_size: 100,
            total: 1,
          }
        : emptyJobs()
    ));
    const cancelJob = vi.spyOn(apiClient, "cancelJob").mockResolvedValue({
      ...activeJob,
      status: "CANCELLED",
    });
    renderShell("/dashboard");

    await requestWindowClose();
    const exitButton = screen.getByRole("button", { name: "Exit anyway" });
    fireEvent.click(exitButton);
    fireEvent.click(exitButton);

    await waitFor(() => expect(cancelJob).toHaveBeenCalledWith("job-running"));
    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(cancelJob).toHaveBeenCalledTimes(1);
    expect(invokeDesktop).not.toHaveBeenCalled();
  });

  it("closes immediately when there is no draft and no active work", async () => {
    renderShell("/dashboard");

    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog", { name: "Before you close DroneDream" })).toBeNull();
    expect(invokeDesktop).not.toHaveBeenCalled();
  });
});
