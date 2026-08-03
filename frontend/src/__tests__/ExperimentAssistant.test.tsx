import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, ApiClientError } from "../api/client";
import { EXPERIMENT_DRAFT_KEY } from "../features/experiment/draftStorage";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";
import { I18nProvider } from "../i18n/I18nProvider";
import { ExperimentAssistant } from "../pages/ExperimentAssistant";
import type { ExperimentAssistantTurnResponse } from "../types/api";

function renderAssistant() {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <ModelAccessProvider
          initialSettings={{
            provider: "qwen",
            apiKey: "memory-only-key",
            model: "qwen-plus",
            baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          }}
        >
          <ExperimentAssistant />
        </ModelAccessProvider>
      </MemoryRouter>
    </I18nProvider>,
  );
}

function assistantResponse(): ExperimentAssistantTurnResponse {
  return {
    schema_version: "1.0",
    experiment_summary:
      "Tune an x500 on a five metre circular track at three metres altitude.",
    accepted_patches: [
      {
        field_id: "display_name",
        value: "x500-circle-study",
        provenance: "derived",
        source_message_id: "message-under-test",
      },
      {
        field_id: "track_type",
        value: "circle",
        provenance: "explicit",
        source_message_id: "message-under-test",
      },
      {
        field_id: "altitude_m",
        value: 3,
        provenance: "explicit",
        source_message_id: "message-under-test",
      },
    ],
    rejected_patches: [],
    accepted_parameter_patches: [
      {
        name: "MPC_XY_P",
        source_message_id: "message-under-test",
        selected: true,
        baseline: 0.95,
        search_min: 0.6,
        search_max: 1.3,
        scale: "linear",
        provenance: "explicit",
      },
    ],
    rejected_parameter_patches: [],
    missing_field_ids: ["simulator_backend"],
    review_field_ids: ["optimizer_strategy"],
    questions: [
      {
        field_ids: ["simulator_backend", "optimizer_strategy"],
        question: "Which simulator backend and optimizer should be used?",
      },
    ],
    usage: {
      input_tokens: 120,
      output_tokens: 80,
      total_tokens: 200,
      estimated: false,
    },
    provider: "qwen",
    model: "qwen-plus",
  };
}

describe("conversational experiment drafting", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
    Reflect.deleteProperty(window, "SpeechRecognition");
  });

  it("compiles a turn into the shared V3 draft without persisting the API key", async () => {
    vi.spyOn(apiClient, "compileExperimentAssistantTurn").mockImplementation(
      async (request) => {
        expect(request.current_parameters).toEqual(
          expect.arrayContaining([
            expect.objectContaining({ name: "MPC_XY_P", selected: true }),
          ]),
        );
        const response = assistantResponse();
        response.accepted_patches = response.accepted_patches.map((patch) => ({
          ...patch,
          source_message_id: request.message_id,
        }));
        return response;
      },
    );
    renderAssistant();

    fireEvent.change(screen.getByLabelText("Describe your experiment…"), {
      target: {
        value:
          "Tune an x500 on a circular track at 3 metres and include MPC_XY_P.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByText(/Tune an x500 on a five metre circular track/),
    ).toBeVisible();
    expect(screen.getByText("Still to decide")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open experiment" })).toBeEnabled();

    const raw = window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY);
    expect(raw).not.toBeNull();
    expect(raw).not.toContain("memory-only-key");
    const stored = JSON.parse(raw ?? "null") as {
      schema_version: number;
      form: Record<string, unknown>;
      selections: Record<string, { selected: boolean }>;
      conversation: {
        summary: string;
        messages: Array<{ role: string; content: string }>;
      };
    };
    expect(stored.schema_version).toBe(3);
    expect(stored.form).toMatchObject({
      display_name: "x500-circle-study",
      track_type: "circle",
      altitude_m: "3",
      llm_api_key: "",
    });
    expect(stored.selections.MPC_XY_P.selected).toBe(true);
    expect(stored.conversation.summary).toContain("five metre circular track");
    expect(stored.conversation.messages.map((message) => message.role)).toEqual([
      "user",
      "assistant",
    ]);
    const persistentRaw = window.localStorage.getItem(EXPERIMENT_DRAFT_KEY);
    expect(persistentRaw).toContain("five metre circular track");
    expect(persistentRaw).not.toContain(
      "Tune an x500 on a circular track at 3 metres and include MPC_XY_P.",
    );
    expect(JSON.parse(persistentRaw ?? "null").conversation.messages).toEqual([]);
  });

  it("coalesces duplicate submissions before React can disable the composer", async () => {
    let resolveCompile:
      | ((response: ExperimentAssistantTurnResponse) => void)
      | null = null;
    const compile = vi
      .spyOn(apiClient, "compileExperimentAssistantTurn")
      .mockImplementation(
        () =>
          new Promise<ExperimentAssistantTurnResponse>((resolve) => {
            resolveCompile = resolve;
          }),
      );
    const { container } = renderAssistant();
    fireEvent.change(screen.getByLabelText("Describe your experiment…"), {
      target: { value: "Tune one safe circular-track experiment." },
    });
    const form = container.querySelector<HTMLFormElement>(".assistant-composer");
    expect(form).not.toBeNull();

    act(() => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(compile).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCompile?.(assistantResponse());
    });
    expect(
      await screen.findByText(/Tune an x500 on a five metre circular track/),
    ).toBeVisible();
    expect(compile).toHaveBeenCalledTimes(1);
  });

  it("preserves a follow-up typed while the previous turn is pending", async () => {
    let resolveCompile:
      | ((response: ExperimentAssistantTurnResponse) => void)
      | null = null;
    vi.spyOn(apiClient, "compileExperimentAssistantTurn").mockImplementation(
      () => new Promise<ExperimentAssistantTurnResponse>((resolve) => {
        resolveCompile = resolve;
      }),
    );
    renderAssistant();
    const composer = screen.getByLabelText("Describe your experiment…");
    fireEvent.change(composer, {
      target: { value: "Tune one safe circular-track experiment." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    fireEvent.change(composer, {
      target: { value: "Also verify the result in a wind holdout." },
    });
    await act(async () => {
      resolveCompile?.(assistantResponse());
    });

    expect(await screen.findByText(/Tune an x500 on a five metre circular track/))
      .toBeVisible();
    expect(composer).toHaveValue(
      "Also verify the result in a wind holdout.",
    );
  });

  it("does not request microphone permission until the user clicks the voice button", async () => {
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop: stopTrack }],
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });

    const recognitionStart = vi.fn();
    class FakeSpeechRecognition {
      lang = "";
      continuous = false;
      interimResults = false;
      maxAlternatives = 0;
      onresult = null;
      onerror = null;
      onend = null;
      start = recognitionStart;
      stop = vi.fn();
      abort = vi.fn();
    }
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: FakeSpeechRecognition,
    });

    renderAssistant();
    expect(getUserMedia).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Use voice input" }));
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(
      screen.getByText(/browser may send microphone audio to its speech service/i),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Allow and start" }));

    await waitFor(() => {
      expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
      expect(stopTrack).toHaveBeenCalledTimes(1);
      expect(recognitionStart).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText("Listening…")).toBeVisible();
  });

  it("keeps the manual five-step path available beside the conversation path", () => {
    const { container } = renderAssistant();

    expect(container.querySelector(".assistant-hero-icon"))
      .toHaveTextContent(">_");
    expect(container.querySelector(".assistant-hero-icon svg")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "More ways to start" }));
    expect(screen.getByRole("menuitem", { name: "Create manually" }))
      .toHaveAttribute("href", "/jobs/new");
    expect(
      screen.getByRole("menuitem", { name: "Import files" }),
    ).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Model" }))
      .toHaveValue("default");
  });

  it("shows only centrally available managed models without exposing a key", () => {
    window.history.replaceState({}, "", "/?docsPreview=1");
    render(
      <I18nProvider>
        <MemoryRouter>
          <ModelAccessProvider>
            <ExperimentAssistant />
          </ModelAccessProvider>
        </MemoryRouter>
      </I18nProvider>,
    );

    const selector = screen.getByRole("combobox", { name: "Model" });
    expect(selector).toHaveValue("managed:openai");
    expect(selector).toHaveTextContent("GPT · gpt-4.1");
    expect(selector).toHaveTextContent("DeepSeek · deepseek-chat");
    expect(selector).toHaveTextContent("Qwen · qwen-plus");
    expect(selector).not.toHaveTextContent("key required");

    fireEvent.change(selector, { target: { value: "managed:deepseek" } });
    expect(selector).toHaveValue("managed:deepseek");
  });

  it("fails closed when a signed-out build has no managed model policy", () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <ModelAccessProvider>
            <ExperimentAssistant />
          </ModelAccessProvider>
        </MemoryRouter>
      </I18nProvider>,
    );

    const selector = screen.getByRole("combobox", { name: "Model" });
    expect(selector).toBeDisabled();
    expect(selector).toHaveValue("none");
    expect(selector).toHaveTextContent(
      "No managed conversation model is currently available.",
    );
  });

  it("inserts only a template body and keeps its heading out of the prompt", () => {
    renderAssistant();

    fireEvent.click(screen.getByRole("button", { name: /Circular Track/ }));

    const composer = screen.getByLabelText("Describe your experiment…");
    expect(composer).toHaveValue(
      "Tune an x500 on a 5 m circular track at 3 m altitude, balancing tracking accuracy, wind robustness, and repeatable trials.",
    );
    expect((composer as HTMLTextAreaElement).value).not.toContain(
      "Circular Track",
    );
  });

  it("imports a supported reference file from the add menu", async () => {
    const compile = vi.spyOn(apiClient, "compileExperimentAssistantTurn")
      .mockResolvedValue(assistantResponse());
    const { container } = renderAssistant();
    const fileInput = container.querySelector<HTMLInputElement>(
      ".assistant-reference-input",
    );
    expect(fileInput).not.toBeNull();

    const file = new File(
      ['{"track_type":"circle","altitude_m":3}'],
      "experiment.json",
      { type: "application/json" },
    );
    fireEvent.change(fileInput as HTMLInputElement, {
      target: { files: [file] },
    });

    expect(await screen.findByText("experiment.json")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Remove file: experiment.json" }),
    ).toBeEnabled();
    expect(screen.getByText(
      "DroneDream uses reference content only in this request and does not save it in drafts or memory. Your selected model provider still receives the request.",
    )).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));
    const request = compile.mock.calls[0][0];
    expect(request.message).toBe(
      "Use the imported reference files to prepare this experiment.",
    );
    expect(request.message).not.toContain("track_type");
    expect(request.document_context).toMatchObject({
      schema_version: "1.0",
      purpose: "experiment_draft_reference",
      chunks: [
        {
          chunk_id: "chunk-1",
          display_name: "experiment.json",
          content: '{"track_type":"circle","altitude_m":3}',
          retention: "request_only",
        },
      ],
    });
    expect(request.document_context?.chunks[0].content_sha256)
      .toMatch(/^[0-9a-f]{64}$/u);
    expect(window.localStorage.getItem(EXPERIMENT_DRAFT_KEY))
      .not.toContain('{"track_type":"circle","altitude_m":3}');
  });

  it("clears the conversation and shared experiment draft only after confirmation", async () => {
    vi.spyOn(apiClient, "compileExperimentAssistantTurn").mockImplementation(
      async (request) => {
        const response = assistantResponse();
        response.accepted_patches = response.accepted_patches.map((patch) => ({
          ...patch,
          source_message_id: request.message_id,
        }));
        return response;
      },
    );
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAssistant();

    fireEvent.change(screen.getByLabelText("Describe your experiment…"), {
      target: { value: "Tune an x500 on a circular track." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Clear conversation")).toBeVisible();
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clear conversation" }));

    expect(confirm).toHaveBeenCalledWith(
      "Clear this conversation and discard its current experiment draft?",
    );
    expect(window.sessionStorage.getItem(EXPERIMENT_DRAFT_KEY)).toBeNull();
    expect(
      screen.getByRole("heading", {
        name: "What flight experiment should we build?",
      }),
    ).toBeVisible();
  });

  it("explains that a 404 assistant route means the installed Runtime is outdated", async () => {
    vi.spyOn(apiClient, "compileExperimentAssistantTurn").mockRejectedValue(
      new ApiClientError("NOT_FOUND", "Not Found", null, 404),
    );
    renderAssistant();

    fireEvent.change(screen.getByLabelText("Describe your experiment…"), {
      target: { value: "Tune an x500 on a circular track." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(
      "This installed DroneDreamRuntime does not support AI experiment drafting yet.",
    );
    expect(screen.queryByText("Not Found")).not.toBeInTheDocument();
  });

  it("asks for a manual environment check only after a send hits an unavailable Runtime", async () => {
    vi.spyOn(apiClient, "compileExperimentAssistantTurn").mockRejectedValue(
      new ApiClientError("NETWORK_ERROR", "Failed to fetch", null, 0),
    );
    renderAssistant();

    fireEvent.change(screen.getByLabelText("Describe your experiment…"), {
      target: { value: "Build a robust wind experiment." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Open Settings and run Check environment",
    );
  });
});
