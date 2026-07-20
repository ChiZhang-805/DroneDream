import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, useI18n } from "../i18n/I18nProvider";

function LanguageProbe() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div>
      <span>{t("wizard.title")}</span>
      <span>{t("runtimeGate.previewTitle")}</span>
      <span>{t("runtimeGate.ece498PreviewBody")}</span>
      <span>{t("wizard.realAdvancedText")}</span>
      <button type="button" onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}>
        Switch language
      </button>
    </div>
  );
}

describe("I18nProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("switches the core product language and persists the choice", () => {
    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );
    expect(screen.getByText("New Tuning Experiment")).toBeInTheDocument();
    expect(screen.getByText("Runtime data is not available yet")).toBeInTheDocument();
    expect(screen.getByText(/review and edit the ECE498 configuration/i)).toBeInTheDocument();
    expect(screen.getByText(/physically creates verified obstacles through Gazebo Entity Factory/i)).toBeInTheDocument();
    expect(screen.getByText(/still fails closed for gusts, sensor degradation, battery effects/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Switch language/i }));
    expect(screen.getByText("新建调优实验")).toBeInTheDocument();
    expect(screen.getByText("运行数据暂不可用")).toBeInTheDocument();
    expect(screen.getByText(/查看并编辑 ECE498 配置/)).toBeInTheDocument();
    expect(screen.getByText(/通过 Gazebo Entity Factory 真实生成并验证障碍物/)).toBeInTheDocument();
    expect(screen.getByText(/阵风、传感器退化、电池效应及非标称场景仍会默认拒绝运行/)).toBeInTheDocument();
    expect(window.localStorage.getItem("drone-dream:locale")).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("still starts when reading the stored locale is denied", () => {
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("en-US");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Storage disabled", "SecurityError");
    });

    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );

    expect(screen.getByText("New Tuning Experiment")).toBeInTheDocument();
  });

  it("keeps the selected in-memory locale when persistence fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage disabled", "QuotaExceededError");
    });

    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Switch language/i }));

    expect(screen.getByText("新建调优实验")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
  });
});
