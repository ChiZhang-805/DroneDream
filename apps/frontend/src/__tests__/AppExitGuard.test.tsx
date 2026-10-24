import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "../AppShell";
import type {
  DesktopCloseRequestedEvent,
  DesktopWindowHandle,
} from "../desktop/bridge";
import { resetDesktopReadinessSession } from "../desktop/readiness";
import { EXPERIMENT_DRAFT_KEY } from "../features/experiment/draftStorage";
import { I18nProvider } from "../i18n/I18nProvider";

let closeRequestedHandler:
  | ((event: DesktopCloseRequestedEvent) => void | Promise<void>)
  | undefined;
let destroyWindow: ReturnType<typeof vi.fn<() => void>>;
let invokeDesktop: ReturnType<typeof vi.fn<(command: string, args?: Record<string, unknown>) => unknown>>;

function installDesktopWindow(): void {
  destroyWindow = vi.fn<() => void>();
  invokeDesktop = vi.fn<(command: string, args?: Record<string, unknown>) => unknown>((command) => {
    if (command === "stop_runtime_for_exit") return null;
    throw new Error("No automatic probe expected.");
  });
  const desktopWindow: DesktopWindowHandle = {
    onCloseRequested: vi.fn(async (handler) => {
      closeRequestedHandler = handler;
      return vi.fn();
    }),
    destroy: async () => { destroyWindow(); },
  };
  window.__TAURI__ = {
    core: { invoke: async (command, args) => invokeDesktop(command, args) },
    window: { getCurrentWindow: () => desktopWindow },
  };
}

function renderShell(path: string): void {
  const router = createMemoryRouter([{
    path: "/",
    element: <AppShell />,
    children: [
      { path: "dashboard", element: <div>Dashboard content</div> },
      { path: "desktop/setup", element: <div>Environment setup</div> },
    ],
  }], { initialEntries: [path] });
  render(<I18nProvider><RouterProvider router={router} /></I18nProvider>);
}

async function requestWindowClose(): Promise<void> {
  await waitFor(() => expect(closeRequestedHandler).toBeTypeOf("function"));
  const preventDefault = vi.fn();
  await act(async () => {
    await closeRequestedHandler?.({ preventDefault });
  });
  expect(preventDefault).toHaveBeenCalledTimes(1);
}

describe("desktop direct close", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_DESKTOP_VISUAL_QA", "true");
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    resetDesktopReadinessSession();
    closeRequestedHandler = undefined;
    installDesktopWindow();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    delete window.__TAURI__;
  });

  it("stops Runtime and destroys the window without a confirmation dialog", async () => {
    renderShell("/dashboard");
    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(invokeDesktop).toHaveBeenCalledWith("stop_runtime_for_exit", undefined);
  });

  it("persists a redacted draft before closing directly", async () => {
    window.sessionStorage.setItem(EXPERIMENT_DRAFT_KEY, JSON.stringify({
      schema_version: 3,
      saved_at: "2026-10-25T00:00:00.000Z",
      active_step: 2,
      completed_steps: [0, 1],
      form: { display_name: "Keep me", llm_api_key: "must-not-persist" },
      selections: {},
      conversation: { summary: "Keep summary", field_provenance: {}, messages: [] },
    }));
    renderShell("/dashboard");
    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).toContain("Keep me");
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toContain("must-not-persist");
  });

  it("still destroys the window when Runtime shutdown reports an error", async () => {
    invokeDesktop.mockRejectedValueOnce(new Error("Runtime termination failed."));
    renderShell("/desktop/setup");
    await requestWindowClose();

    await waitFor(() => expect(destroyWindow).toHaveBeenCalledTimes(1));
  });
});
