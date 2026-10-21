import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, localeSafeError, useI18n } from "../i18n/I18nProvider";

function LanguageProbe() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div>
      <span>{t("wizard.title")}</span>
      <span>{t("runtimeGate.previewTitle")}</span>
      <span>{t("wizard.realAdvancedText")}</span>
      <span>{t("settings.model.estimatedUsage", { count: 3 })}</span>
      <button type="button" onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}>
        Switch language
      </button>
    </div>
  );
}

function InterfaceLanguageProbe() {
  const { interfaceLocale, setLocale, t } = useI18n();
  return (
    <div>
      <span data-testid="interface-locale">{interfaceLocale}</span>
      <span data-testid="settings-label">{t("app.settings")}</span>
      {(["en", "zh-CN"] as const).map((next) => (
        <button key={next} type="button" onClick={() => setLocale(next)}>{next}</button>
      ))}
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
    delete window.__TAURI__;
  });

  it("keeps dynamic error prose inside the selected interface language", () => {
    const fallback = { zh: "运行环境暂时不可用。", en: "The runtime is unavailable." };
    expect(localeSafeError(new Error("Backend unavailable"), "zh-CN", fallback)).toBe(fallback.zh);
    expect(localeSafeError(new Error("后端暂时不可用"), "en", fallback)).toBe(fallback.en);
    expect(localeSafeError("RUNTIME_NOT_READY", "zh-CN", fallback))
      .toBe("运行环境暂时不可用。（RUNTIME_NOT_READY）");
    expect(localeSafeError("RUNTIME_NOT_READY", "en", fallback))
      .toBe("The runtime is unavailable. (RUNTIME_NOT_READY)");
  });

  it("switches the core product language and persists the choice", () => {
    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );
    expect(screen.getByText("New Tuning Experiment")).toBeInTheDocument();
    expect(screen.getByText("Runtime disconnected")).toBeInTheDocument();
    expect(screen.getByText(/physically creates verified obstacles through Gazebo Entity Factory/i)).toBeInTheDocument();
    expect(screen.getByText(/still fails closed for gusts, sensor degradation, battery effects/i)).toBeInTheDocument();
    expect(screen.getByText("3 request(s) used conservative estimated accounting"))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Switch language/i }));
    expect(screen.getByText("新建调优实验")).toBeInTheDocument();
    expect(screen.getByText("运行环境未连接")).toBeInTheDocument();
    expect(screen.getByText(/通过 Gazebo Entity Factory 真实生成并验证障碍物/)).toBeInTheDocument();
    expect(screen.getByText(/阵风、传感器退化、电池效应及非标称场景仍会默认拒绝运行/)).toBeInTheDocument();
    expect(screen.getByText("3 次请求采用保守估算记账")).toBeInTheDocument();
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

  it("defaults to English in the browser even when the operating system uses Chinese", () => {
    window.localStorage.clear();
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("zh-CN");

    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );

    expect(screen.getByText("New Tuning Experiment")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it("uses Chinese only when a fresh desktop install recorded Chinese", async () => {
    window.localStorage.clear();
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "get_installer_locale") return "zh-CN";
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );

    expect(await screen.findByText("新建调优实验")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
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

  it.each([
    ["en", "Settings"],
    ["zh-CN", "设置"],
  ] as const)("renders and persists the %s console interface", (next, expected) => {
    render(
      <I18nProvider>
        <InterfaceLanguageProbe />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: next }));
    expect(screen.getByTestId("interface-locale")).toHaveTextContent(next);
    expect(screen.getByTestId("settings-label")).toHaveTextContent(expected);
    expect(window.localStorage.getItem("drone-dream:locale")).toBe(next);
    expect(document.documentElement.lang).toBe(next);
  });

  it("migrates a legacy partial locale to the complete English interface", () => {
    window.localStorage.setItem("drone-dream:locale", "ja");
    render(
      <I18nProvider>
        <InterfaceLanguageProbe />
      </I18nProvider>,
    );

    expect(screen.getByTestId("interface-locale")).toHaveTextContent("en");
    expect(screen.getByTestId("settings-label")).toHaveTextContent("Settings");
    expect(window.localStorage.getItem("drone-dream:locale")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });
});
