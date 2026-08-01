import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useModelAccess } from "../features/settings/ModelAccessContext";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";

function ModelAccessProbe() {
  const {
    settings,
    selectAccessMode,
    selectManagedProvider,
    selectProvider,
  } = useModelAccess();
  return (
    <>
      <output aria-label="provider">{settings.provider}</output>
      <output aria-label="api-key">{settings.apiKey}</output>
      <output aria-label="access-mode">{settings.accessMode}</output>
      <output aria-label="managed-provider">{settings.managedProvider}</output>
      <button type="button" onClick={() => selectAccessMode("byok")}>
        Use my key
      </button>
      <button type="button" onClick={() => selectProvider("qwen")}>
        Select Qwen
      </button>
      <button type="button" onClick={() => selectManagedProvider("deepseek")}>
        Select managed DeepSeek
      </button>
    </>
  );
}

describe("ModelAccessProvider", () => {
  afterEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("clears the in-memory credential when its provider changes", async () => {
    render(
      <ModelAccessProvider initialSettings={{ apiKey: "openai-secret" }}>
        <ModelAccessProbe />
      </ModelAccessProvider>,
    );

    expect(screen.getByLabelText("api-key")).toHaveTextContent("openai-secret");
    fireEvent.click(screen.getByRole("button", { name: "Select Qwen" }));

    expect(screen.getByLabelText("provider")).toHaveTextContent("qwen");
    expect(screen.getByLabelText("api-key")).toBeEmptyDOMElement();
    await waitFor(() => {
      expect(window.localStorage.getItem("dronedream:model-access:v1"))
        .not.toContain("openai-secret");
    });
  });

  it("defaults to the included platform allowance and persists only the mode", async () => {
    render(
      <ModelAccessProvider
        initialSettings={{ accessMode: "platform", apiKey: "never-persist" }}
      >
        <ModelAccessProbe />
      </ModelAccessProvider>,
    );

    expect(screen.getByLabelText("access-mode")).toHaveTextContent("platform");
    expect(screen.getByLabelText("managed-provider")).toHaveTextContent("openai");
    fireEvent.click(screen.getByRole("button", { name: "Select managed DeepSeek" }));
    expect(screen.getByLabelText("managed-provider")).toHaveTextContent("deepseek");
    fireEvent.click(screen.getByRole("button", { name: "Use my key" }));
    expect(screen.getByLabelText("access-mode")).toHaveTextContent("byok");
    await waitFor(() => {
      const stored = window.localStorage.getItem("dronedream:model-access:v1") ?? "";
      expect(stored).toContain("\"accessMode\":\"byok\"");
      expect(stored).toContain("\"managedProvider\":\"deepseek\"");
      expect(stored).not.toContain("never-persist");
    });
  });
});
