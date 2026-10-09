import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  invokeDesktop = vi.fn(async (command: string) => {
    if (command === "stop_runtime_for_exit") return null;
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
    // Exit protection is a workspace-only concern. Visual-QA mode deliberately
    // bypasses the first-run launcher gate without probing or starting Runtime.
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
      conversation: {
        summary: "Keep only this compact summary.",
        field_provenance: {},
        messages: [
          {
            id: "turn-private",
            role: "user",
            content: "must-not-persist-raw-chat",
          },
        ],
      },
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
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toContain(
      "must-not-persist-raw-chat",
    );
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain(
      "Keep only this compact summary.",
    );
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
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

  it("keeps the native-close confirmation operable above the full settings workspace", async () => {
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) =>
      emptyJobs(params?.status === "RUNNING" ? 1 : 0)
    );
    renderShell("/dashboard");

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const quickSettings = screen.getByRole("dialog", { name: "Settings" });
    fireEvent.click(within(quickSettings).getByRole("button", { name: "All settings" }));
    const settingsWorkspace = await screen.findByRole("region", { name: "Settings" });
    const activeSettingsTab = within(settingsWorkspace).getByRole("tab", { name: "General" });
    await waitFor(() => expect(activeSettingsTab).toHaveFocus());

    await requestWindowClose();

    const exitDialog = screen.getByRole("dialog", { name: "Before you close DroneDream" });
    expect(exitDialog).toBeVisible();
    expect(exitDialog.closest("[inert]")).toBeNull();
    const settingsHost = settingsWorkspace.closest(".settings-workspace-host");
    expect(settingsHost).toHaveAttribute("inert");
    const returnButton = within(exitDialog).getByRole("button", { name: "Return to DroneDream" });
    const exitButton = within(exitDialog).getByRole("button", { name: "Exit anyway" });
    await waitFor(() => expect(returnButton).toHaveFocus());
    exitButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(returnButton).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(exitButton).toHaveFocus();
    fireEvent.click(returnButton);
    expect(screen.queryByRole("dialog", { name: "Before you close DroneDream" })).toBeNull();
    await waitFor(() => expect(settingsHost).not.toHaveAttribute("inert"));
    await waitFor(() => expect(activeSettingsTab).toHaveFocus());
  });

  it("cancels known jobs and stops the dedicated runtime before destroying the window", async () => {
    const activeJob = { id: "job-running", control_version: 7 } as Job;
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

    await waitFor(() => expect(cancelJob).toHaveBeenCalledWith("job-running", 7));
    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(cancelJob).toHaveBeenCalledTimes(1);
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
    expect(cancelJob.mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(invokeDesktop).mock.invocationCallOrder[0]);
    expect(vi.mocked(invokeDesktop).mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(destroyWindow).mock.invocationCallOrder[0]);
  });

  it("enumerates every active-job page before cancelling and exiting", async () => {
    const activeJobs = Array.from({ length: 101 }, (_, index) => ({
      id: `job-running-${index + 1}`,
      control_version: index + 1,
    } as Job));
    vi.mocked(apiClient.listJobs).mockImplementation(async (params) => {
      if (params?.status !== "RUNNING") return emptyJobs();
      const page = params.page ?? 1;
      const start = (page - 1) * 100;
      return {
        items: activeJobs.slice(start, start + 100),
        page,
        page_size: 100,
        total: activeJobs.length,
      };
    });
    const cancelJob = vi.spyOn(apiClient, "cancelJob").mockImplementation(
      async (jobId) => ({
        ...activeJobs.find((job) => job.id === jobId)!,
        status: "CANCELLED",
      } as Job),
    );
    renderShell("/dashboard");

    await requestWindowClose();
    expect(screen.getByText(/101 active experiment jobs/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Exit anyway" }));

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(apiClient.listJobs).toHaveBeenCalledWith({
      page: 2,
      page_size: 100,
      status: "RUNNING",
    });
    expect(cancelJob).toHaveBeenCalledTimes(101);
    expect(cancelJob).toHaveBeenCalledWith("job-running-101", 101);
  });

  it("stops the dedicated runtime and closes without prompting when no work is active", async () => {
    renderShell("/dashboard");

    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog", { name: "Before you close DroneDream" })).toBeNull();
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
  });

  it("still closes when the bounded runtime stop command reports an error", async () => {
    vi.mocked(invokeDesktop).mockRejectedValueOnce(
      new Error("Runtime termination timed out."),
    );
    renderShell("/dashboard");

    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
  });

  it("always lets the first-run launcher close without probing workspace jobs", async () => {
    vi.mocked(invokeDesktop).mockRejectedValueOnce(
      new Error("Runtime is not installed on this machine."),
    );
    renderShell("/desktop/setup");

    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(apiClient.listJobs).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Before you close DroneDream" })).toBeNull();
  });
});
