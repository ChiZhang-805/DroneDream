import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useModelAccess } from "../features/settings/ModelAccessContext";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";

function Probe() {
  const modelAccess = useModelAccess();
  return (
    <>
      <output aria-label="provider">{modelAccess.settings.provider}</output>
      <output aria-label="api-key">{modelAccess.settings.apiKey}</output>
      <output aria-label="model">{modelAccess.settings.model}</output>
      <output aria-label="base-url">{modelAccess.settings.baseUrl}</output>
      <button
        type="button"
        onClick={() => modelAccess.updateSettings({
          provider: "qwen",
          apiKey: "user-a-secret",
          model: "user-a-model",
          baseUrl: "https://user-a.example/v1",
        })}
      >
        Configure key
      </button>
    </>
  );
}

describe("model access account isolation", () => {
  afterEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("isolates persisted model metadata and clears every key across account changes", async () => {
    const view = render(
      <ModelAccessProvider accountScope="user-a">
        <Probe />
      </ModelAccessProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure key" }));
    expect(screen.getByLabelText("provider")).toHaveTextContent("qwen");
    expect(screen.getByLabelText("api-key")).toHaveTextContent("user-a-secret");

    view.rerender(
      <ModelAccessProvider accountScope="user-b">
        <Probe />
      </ModelAccessProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("api-key")).toBeEmptyDOMElement();
    });
    expect(screen.getByLabelText("provider")).toHaveTextContent("openai");
    expect(screen.getByLabelText("model")).toBeEmptyDOMElement();
    expect(screen.getByLabelText("base-url")).toBeEmptyDOMElement();

    view.rerender(
      <ModelAccessProvider accountScope="user-a">
        <Probe />
      </ModelAccessProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("provider")).toHaveTextContent("qwen");
    });
    expect(screen.getByLabelText("model")).toHaveTextContent("user-a-model");
    expect(screen.getByLabelText("base-url")).toHaveTextContent(
      "https://user-a.example/v1",
    );
    expect(screen.getByLabelText("api-key")).toBeEmptyDOMElement();
  });
});
