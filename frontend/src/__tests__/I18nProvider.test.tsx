import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider, useI18n } from "../i18n/I18nProvider";

function LanguageProbe() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div>
      <span>{t("wizard.title")}</span>
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

  it("switches the core product language and persists the choice", () => {
    render(
      <I18nProvider>
        <LanguageProbe />
      </I18nProvider>,
    );
    expect(screen.getByText("New Tuning Experiment")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Switch language/i }));
    expect(screen.getByText("新建调优实验")).toBeInTheDocument();
    expect(window.localStorage.getItem("drone-dream:locale")).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
  });
});

