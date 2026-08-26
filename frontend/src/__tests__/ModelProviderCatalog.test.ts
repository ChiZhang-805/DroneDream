import { describe, expect, it } from "vitest";

import {
  detectModelProvider,
  MODEL_PROVIDER_CATALOG,
  modelProviderDefaults,
} from "../features/settings/modelProviderCatalog";

describe("model provider catalog", () => {
  it("keeps the provider registry unique and expandable", () => {
    const ids = MODEL_PROVIDER_CATALOG.map((provider) => provider.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(expect.arrayContaining([
      "openai",
      "anthropic",
      "google",
      "xai",
      "qwen",
      "deepseek",
      "kimi",
      "zhipu",
      "together",
      "openrouter",
      "ollama",
      "custom",
    ]));
  });

  it("prefers a provider endpoint over a model-name coincidence", () => {
    expect(detectModelProvider({
      baseUrl: "https://api.together.xyz/v1",
      model: "Qwen/Qwen3-235B-A22B",
    })).toMatchObject({
      provider: "together",
      confidence: "high",
      matchedBy: expect.arrayContaining(["endpoint", "model"]),
    });
  });

  it("distinguishes OpenRouter keys from OpenAI keys without transmitting them", () => {
    expect(detectModelProvider({ apiKey: "sk-or-placeholder" })).toMatchObject({
      provider: "openrouter",
      confidence: "medium",
      matchedBy: ["key"],
    });
    expect(detectModelProvider({ apiKey: "sk-proj-placeholder" })).toMatchObject({
      provider: "openai",
      confidence: "medium",
      matchedBy: ["key"],
    });
  });

  it("falls back to a custom profile instead of guessing", () => {
    expect(detectModelProvider({
      baseUrl: "https://models.example.test/v1",
      model: "organization-private-model",
    })).toEqual({
      provider: "custom",
      confidence: "low",
      matchedBy: [],
    });
  });

  it("supplies protocol and endpoint defaults from one registry", () => {
    expect(modelProviderDefaults("anthropic")).toEqual({
      model: "claude-sonnet-4-6",
      baseUrl: "https://api.anthropic.com",
      protocol: "anthropic-messages",
      displayName: "",
    });
    expect(modelProviderDefaults("ollama").protocol).toBe("ollama-chat");
  });
});
