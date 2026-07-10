import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("environment-aware routing", () => {
  it("exports a hash router when Tauri is present during module loading", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    expect(router.state.location.pathname).toBe("/desktop/setup");
    await router.navigate("/dashboard");
    expect(window.location.hash).toBe("#/dashboard");

    router.dispose();
  });

  it("exports a browser router for the hosted web application", async () => {
    delete window.__TAURI__;
    window.history.replaceState(null, "", "/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    expect(router.state.location.pathname).toBe("/desktop/setup");
    await router.navigate("/history");
    expect(window.location.pathname).toBe("/history");
    expect(window.location.hash).toBe("");

    router.dispose();
  });
});
