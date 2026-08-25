import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { CustomModelSettingsPanel } from "../components/CustomModelSettingsPanel";
import { ModelAccessProvider } from "../features/settings/ModelAccessProvider";

function renderPanel() {
  return render(
    <ModelAccessProvider
      accountScope="account-model-settings-test"
      initialSettings={{ accessMode: "byok", provider: "custom" }}
    >
      <CustomModelSettingsPanel locale="zh-CN" />
    </ModelAccessProvider>,
  );
}

describe("CustomModelSettingsPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
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
});
