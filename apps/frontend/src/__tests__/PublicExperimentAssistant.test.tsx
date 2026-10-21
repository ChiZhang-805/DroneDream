import { fireEvent, render, screen } from "@testing-library/react";
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
    expect(modelSelector).toHaveTextContent("GPT 4.1");
    fireEvent.click(modelSelector);
    const defaultModels = screen.getAllByRole("option");
    expect(defaultModels).toHaveLength(7);
    expect(defaultModels.map((item) => item.textContent)).toEqual(expect.arrayContaining([
      expect.stringContaining("GPT 5.4"),
      expect.stringContaining("DeepSeek V4 Pro"),
      expect.stringContaining("Kimi K2.6"),
      expect.stringContaining("Kimi K3"),
    ]));
    expect(screen.getByText("Default")).toBeVisible();
    expect(screen.getByText("Custom")).toBeVisible();
    expect(screen.getByRole("button", { name: /Add custom model/ })).toBeVisible();
  });
});
