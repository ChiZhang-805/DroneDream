import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import { I18nProvider } from "../i18n/I18nProvider";
import { ExperimentAssistant } from "../pages/ExperimentAssistant";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

vi.mock("../features/demo/publicDemo", () => ({
  publicDemoConsole: true,
}));

describe("public web assistant model boundary", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    window.history.replaceState({}, "", "/console/assistant?docsPreview=1");
  });

  it("fixes the public console to the managed OpenAI model", () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <EditionThemeProvider edition="sim">
            <ModelAccessProvider>
              <ExperimentAssistant />
            </ModelAccessProvider>
          </EditionThemeProvider>
        </MemoryRouter>
      </I18nProvider>,
    );

    const modelSelector = screen.getByRole("combobox", { name: "Model" });
    expect(modelSelector).toBeEnabled();
    expect(modelSelector).toHaveValue("managed:openai:gpt-4.1");
    expect(modelSelector.querySelectorAll("option")).toHaveLength(7);
    expect(modelSelector).toHaveTextContent("GPT");
    expect(modelSelector).toHaveTextContent("DeepSeek");
    expect(modelSelector).toHaveTextContent("Kimi K3");
    expect(modelSelector).not.toHaveTextContent("Qwen");
  });
});
