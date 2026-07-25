import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useModelAccess } from "../features/settings/ModelAccessContext";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";

function ModelAccessProbe() {
  const { settings, selectProvider } = useModelAccess();
  return (
    <>
      <output aria-label="provider">{settings.provider}</output>
      <output aria-label="api-key">{settings.apiKey}</output>
      <button type="button" onClick={() => selectProvider("qwen")}>
        Select Qwen
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
});
