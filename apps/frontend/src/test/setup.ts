import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom has no layout engine; browser layout is covered by the Chromium checks.
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete window.__TAURI__;
  document.documentElement.removeAttribute("lang");
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
