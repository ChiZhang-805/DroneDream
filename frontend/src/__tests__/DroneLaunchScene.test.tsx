import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DroneLaunchScene } from "../components/DroneLaunchScene";
import { getDroneStarflightPose } from "../components/droneStarflight";
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

describe("drone starflight trajectory", () => {
  it("starts and finishes at the hovering platform", () => {
    const start = getDroneStarflightPose(0);
    const finish = getDroneStarflightPose(1);

    for (const pose of [start, finish]) {
      expect(pose.x).toBeCloseTo(0, 7);
      expect(pose.y).toBeCloseTo(0, 7);
      expect(pose.z).toBeCloseTo(0, 7);
      expect(pose.scale).toBeCloseTo(1, 7);
    }
  });

  it("flies into the starfield, completes an orbit, and returns smoothly", () => {
    const rightRear = getDroneStarflightPose(0.22);
    const deepCentre = getDroneStarflightPose(0.5);
    const leftRear = getDroneStarflightPose(0.78);
    const returningFromLeft = getDroneStarflightPose(0.9);

    expect(rightRear.x).toBeCloseTo(0.5, 5);
    expect(rightRear.y).toBeCloseTo(0.2, 5);
    expect(rightRear.z).toBeCloseTo(-5.5, 5);
    expect(deepCentre.x).toBeCloseTo(-5, 5);
    expect(deepCentre.y).toBeCloseTo(0, 5);
    expect(deepCentre.z).toBeCloseTo(-7, 5);
    expect(leftRear.x).toBeCloseTo(-8, 5);
    expect(leftRear.y).toBeCloseTo(-0.6, 5);
    expect(leftRear.z).toBeCloseTo(-4.5, 5);
    expect(returningFromLeft.x).toBeGreaterThan(-8);
    expect(returningFromLeft.x).toBeLessThan(0);
    expect(returningFromLeft.z).toBeGreaterThan(-4.5);
  });

  it("clamps trajectory progress outside the animation range", () => {
    expect(getDroneStarflightPose(-1)).toEqual(getDroneStarflightPose(0));
    expect(getDroneStarflightPose(2)).toEqual(getDroneStarflightPose(1));
  });
});
