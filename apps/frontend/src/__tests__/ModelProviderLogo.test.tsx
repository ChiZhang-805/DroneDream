import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModelProviderLogo } from "../components/AssistantModelPicker";
import type { ModelProvider } from "../features/settings/ModelAccessContext";

describe("ModelProviderLogo", () => {
  it("uses vector marks instead of letter placeholders for the supported branded providers", () => {
    const providers: ModelProvider[] = [
      "openai",
      "anthropic",
      "google",
      "xai",
      "qwen",
      "deepseek",
      "kimi",
      "mistral",
      "perplexity",
      "openrouter",
      "together",
    ];

    for (const provider of providers) {
      const { container, unmount } = render(<ModelProviderLogo provider={provider} />);
      expect(container.querySelector("svg")).not.toBeNull();
      expect(container.querySelector(".model-provider-custom-logo")).toBeNull();
      unmount();
    }
  });

  it("renders the Together AI three-circle mark with its three brand colors", () => {
    const { container } = render(<ModelProviderLogo provider="together" />);
    const fills = Array.from(container.querySelectorAll("circle")).map((circle) => circle.getAttribute("fill"));
    expect(fills).toEqual(["#c3a3f7", "#e525c8", "#f45100"]);
  });

  it("keeps the Kimi K as a vector mark suitable for the white model menu", () => {
    const { container } = render(<ModelProviderLogo provider="kimi" />);
    expect(container.querySelector("svg.model-provider-logo-kimi path")).not.toBeNull();
    expect(container.querySelector(".model-provider-custom-logo")).toBeNull();
  });
});
