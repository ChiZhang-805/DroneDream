import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const agentCoreMock = vi.hoisted(() => ({
  create: vi.fn(async () => ({
    profile_id: "cmp-1234567890abcdef12345678",
    selection_id: "custom:cmp-1234567890abcdef12345678",
  })),
  remove: vi.fn(async () => undefined),
  test: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../features/autonomy/agentCore", async (importOriginal) => {
  const original = await importOriginal<typeof import("../features/autonomy/agentCore")>();
  return {
    ...original,
    createAgentCoreCustomModel: agentCoreMock.create,
    deleteAgentCoreCustomModel: agentCoreMock.remove,
    testAgentCoreCustomModel: agentCoreMock.test,
  };
});

import { CustomModelSettingsPanel } from "../components/CustomModelSettingsPanel";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";

function renderPanel(edition?: "autonomy") {
  return render(
    <ModelAccessProvider
      accountScope="account-model-settings-test"
      initialSettings={{ accessMode: "byok", provider: "custom" }}
    >
      <CustomModelSettingsPanel locale="zh-CN" edition={edition} />
    </ModelAccessProvider>,
  );
}

describe("CustomModelSettingsPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    agentCoreMock.create.mockClear();
    agentCoreMock.remove.mockClear();
    agentCoreMock.test.mockClear();
  });

  it("reveals and hides a BYOK credential only on explicit user action", () => {
    renderPanel();
    const key = screen.getByLabelText("API Key") as HTMLInputElement;
    expect(key.type).toBe("password");

    fireEvent.change(key, { target: { value: "secret-for-ui-test" } });
    fireEvent.click(screen.getByRole("button", { name: "显示 API Key" }));
    expect(key.type).toBe("text");
    expect(key.value).toBe("secret-for-ui-test");

    fireEvent.click(screen.getByRole("button", { name: "隐藏 API Key" }));
    expect(key.type).toBe("password");
  });

  it("detects a provider locally and never persists the API key", async () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("API 地址"), {
      target: { value: "https://open.bigmodel.cn/api/paas/v4" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "private-zhipu-key" },
    });
    fireEvent.change(screen.getByLabelText("模型 ID"), {
      target: { value: "glm-4.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "识别供应商与模型" }));

    expect(screen.getByLabelText("供应商")).toHaveValue("zhipu");
    expect(screen.getByText(/已在本机识别为 Zhipu GLM/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(screen.getByText(/模型配置已保存/)).toBeVisible();
    });

    const persisted = Array.from({ length: window.localStorage.length }, (_, index) => {
      const key = window.localStorage.key(index);
      return key ? window.localStorage.getItem(key) : "";
    }).join("\n");
    expect(persisted).toContain("zhipu");
    expect(persisted).toContain("glm-4.5");
    expect(persisted).not.toContain("private-zhipu-key");
  });

  it("separates the editor from the saved-model library and can delete the last saved model", async () => {
    renderPanel();

    expect(screen.getByRole("heading", { name: "模型配置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "自定义模型" })).toBeVisible();
    expect(screen.getByText("尚未保存可使用的自定义模型。")).toBeVisible();

    fireEvent.change(screen.getByLabelText("API 地址"), {
      target: { value: "http://127.0.0.1:11434/v1" },
    });
    fireEvent.change(screen.getByLabelText("供应商"), {
      target: { value: "ollama" },
    });
    fireEvent.change(screen.getByLabelText("模型 ID"), {
      target: { value: "qwen3:8b" },
    });
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Local Qwen" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "删除 Local Qwen" })).toBeVisible();
    });
    expect(screen.getByLabelText("已保存的自定义模型")).toHaveTextContent("Local Qwen");

    fireEvent.click(screen.getByRole("button", { name: "删除 Local Qwen" }));
    await waitFor(() => {
      expect(screen.getByText("尚未保存可使用的自定义模型。")).toBeVisible();
    });
    expect(screen.getByLabelText("模型配置")).toBeVisible();
  });

  it("binds an autonomy custom model through AGENT Core without persisting its key", async () => {
    renderPanel("autonomy");
    fireEvent.change(screen.getByLabelText("API 地址"), {
      target: { value: "https://api.deepseek.com/v1" },
    });
    fireEvent.change(screen.getByLabelText("供应商"), {
      target: { value: "deepseek" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "temporary-agent-core-key" },
    });
    fireEvent.change(screen.getByLabelText("模型 ID"), {
      target: { value: "deepseek-chat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(agentCoreMock.create).toHaveBeenCalledWith({
      display_name: "deepseek-chat",
      base_url: "https://api.deepseek.com",
      model_id: "deepseek-chat",
      api_key: "temporary-agent-core-key",
      api_style: "chat-completions",
      provider: "deepseek",
    }));
    expect(agentCoreMock.test).toHaveBeenCalledWith("cmp-1234567890abcdef12345678");
    expect(screen.getByText(/Windows 当前用户凭证库/)).toBeVisible();
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    const persisted = Array.from({ length: window.localStorage.length }, (_, index) => {
      const key = window.localStorage.key(index);
      return key ? window.localStorage.getItem(key) : "";
    }).join("\n");
    expect(persisted).toContain("custom:cmp-1234567890abcdef12345678");
    expect(persisted).not.toContain("temporary-agent-core-key");
  });
});
