import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DroneLaunchScene } from "../components/DroneLaunchScene";
import { I18nProvider } from "../i18n/I18nProvider";

function renderScene(locale: "en" | "zh-CN") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <DroneLaunchScene active />
    </I18nProvider>,
  );
}

afterEach(() => window.localStorage.clear());

describe("DroneLaunchScene localization", () => {
  it("renders an English-only telemetry overlay in English", () => {
    renderScene("en");

    expect(screen.getByText("PX4 / SITL")).toBeInTheDocument();
    expect(screen.getByText("LINK ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("ATTITUDE")).toBeInTheDocument();
    expect(screen.getByText(/HOLD/)).toBeInTheDocument();
    expect(screen.queryByText("链路已连接")).not.toBeInTheDocument();
    expect(screen.queryByText("飞行姿态")).not.toBeInTheDocument();
  });

  it("renders a Chinese-only telemetry overlay in Chinese", () => {
    renderScene("zh-CN");

    expect(screen.getByText("PX4 / 软件在环")).toBeInTheDocument();
    expect(screen.getByText("链路已连接")).toBeInTheDocument();
    expect(screen.getByText("飞行姿态")).toBeInTheDocument();
    expect(screen.getByText(/悬停/)).toBeInTheDocument();
    expect(screen.queryByText("LINK ACTIVE")).not.toBeInTheDocument();
    expect(screen.queryByText("ATTITUDE")).not.toBeInTheDocument();
    expect(screen.queryByText(/HOLD/)).not.toBeInTheDocument();
  });
});
