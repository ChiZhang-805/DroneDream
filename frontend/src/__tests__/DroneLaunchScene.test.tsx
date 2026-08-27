import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DroneLaunchScene } from "../components/DroneLaunchScene";
import { getDroneStarflightPose } from "../components/droneStarflight";
import { I18nProvider } from "../i18n/I18nProvider";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";

function renderScene(locale: "en" | "zh-CN", edition: "universal" | "sim" | "lab" | "field" | "autonomy" = "universal") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <EditionThemeProvider edition={edition}>
        <DroneLaunchScene active />
      </EditionThemeProvider>
    </I18nProvider>,
  );
}

function poseDistance(first: ReturnType<typeof getDroneStarflightPose>, second: ReturnType<typeof getDroneStarflightPose>) {
  return Math.hypot(second.x - first.x, second.y - first.y, second.z - first.z);
}

afterEach(() => window.localStorage.clear());

describe("DroneLaunchScene localization", () => {
  it("exposes the canonical 3D palette and preserves the no-authority boundary", () => {
    const { container } = renderScene("en", "field");
    const scene = container.querySelector(".drone-launch-scene");
    expect(scene).toHaveAttribute("data-theme-edition", "field");
    expect(scene).toHaveAttribute("data-theme-primary", "#ffc247");
    expect(scene).toHaveAttribute("data-theme-secondary", "#ff754b");
    expect(scene).toHaveAttribute("data-theme-tertiary", "#d746a5");
    expect(scene).toHaveAttribute("data-theme-grants-hardware-authority", "false");
  });

  it("keeps the night-city scene enabled in light appearance", () => {
    window.localStorage.setItem("dronedream:appearance", "light");
    const { container } = renderScene("en");
    const scene = container.querySelector(".drone-launch-scene");

    expect(scene).toHaveAttribute("data-theme-appearance", "light");
    expect(scene).toHaveAttribute("data-scene-stars", "true");
    expect(scene).toHaveAttribute("data-scene-particles", "true");
  });

  it("renders the English launch message without telemetry clutter", () => {
    renderScene("en");

    const heading = screen.getByRole("heading", {
      name: "Let Every Flight Flow Like a Dream",
    });
    expect(heading).toHaveAttribute("data-line-count", "2");
    expect(heading.querySelectorAll(".drone-launch-tagline-line")).toHaveLength(2);
    expect(heading).toHaveTextContent("Let Every Flight Flow Like a Dream");
    expect(screen.queryByText("PX4 / SITL")).not.toBeInTheDocument();
    expect(screen.queryByText("LINK ACTIVE")).not.toBeInTheDocument();
    expect(screen.queryByText("ATTITUDE")).not.toBeInTheDocument();
    expect(screen.queryByText(/HOLD/)).not.toBeInTheDocument();
    expect(screen.queryByText("链路已连接")).not.toBeInTheDocument();
    expect(screen.queryByText("飞行姿态")).not.toBeInTheDocument();
  });

  it("renders the Chinese launch message without telemetry clutter", () => {
    renderScene("zh-CN");

    const heading = screen.getByRole("heading", { name: "蝶 梦 水 云 乡" });
    expect(heading).toHaveAttribute("data-line-count", "1");
    expect(heading.querySelectorAll(".drone-launch-tagline-line")).toHaveLength(1);
    expect(screen.queryByText("PX4 / 软件在环")).not.toBeInTheDocument();
    expect(screen.queryByText("链路已连接")).not.toBeInTheDocument();
    expect(screen.queryByText("飞行姿态")).not.toBeInTheDocument();
    expect(screen.queryByText(/悬停/)).not.toBeInTheDocument();
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

  it("flies out over the city, completes one orbit, and returns smoothly", () => {
    const orbitEntry = getDroneStarflightPose(0.2);
    const farSide = getDroneStarflightPose(0.51);
    const orbitExit = getDroneStarflightPose(0.82);
    const returning = getDroneStarflightPose(0.91);

    expect(orbitEntry.x).toBeCloseTo(3.9, 5);
    expect(orbitEntry.y).toBeCloseTo(0.95, 5);
    expect(orbitEntry.z).toBeCloseTo(-3.5, 5);
    expect(farSide.x).toBeCloseTo(-3.9, 5);
    expect(farSide.y).toBeCloseTo(0.95, 5);
    expect(farSide.z).toBeCloseTo(-3.5, 5);
    expect(orbitExit.x).toBeCloseTo(orbitEntry.x, 5);
    expect(orbitExit.y).toBeCloseTo(orbitEntry.y, 5);
    expect(orbitExit.z).toBeCloseTo(orbitEntry.z, 5);
    expect(returning.x).toBeGreaterThan(0);
    expect(returning.x).toBeLessThan(orbitExit.x);
    expect(returning.z).toBeGreaterThan(orbitExit.z);
  });

  it("eases into and out of the city orbit", () => {
    const entryFirst = poseDistance(
      getDroneStarflightPose(0.2),
      getDroneStarflightPose(0.205),
    );
    const entrySecond = poseDistance(
      getDroneStarflightPose(0.205),
      getDroneStarflightPose(0.21),
    );
    const middleBefore = poseDistance(
      getDroneStarflightPose(0.46),
      getDroneStarflightPose(0.51),
    );
    const middleAfter = poseDistance(
      getDroneStarflightPose(0.51),
      getDroneStarflightPose(0.56),
    );
    const exitBefore = poseDistance(
      getDroneStarflightPose(0.81),
      getDroneStarflightPose(0.815),
    );
    const exitLast = poseDistance(
      getDroneStarflightPose(0.815),
      getDroneStarflightPose(0.82),
    );

    expect(entryFirst).toBeLessThan(entrySecond);
    expect(exitLast).toBeLessThan(exitBefore);
    expect(middleBefore / middleAfter).toBeGreaterThan(0.9);
    expect(middleBefore / middleAfter).toBeLessThan(1.1);
  });

  it("keeps every sampled pose finite and physically scaled", () => {
    for (let index = 0; index <= 1_000; index += 1) {
      const pose = getDroneStarflightPose(index / 1_000);
      expect(Object.values(pose).every(Number.isFinite)).toBe(true);
      expect(pose.scale).toBeGreaterThan(0);
      expect(pose.scale).toBeLessThanOrEqual(1);
    }
  });

  it("clamps trajectory progress outside the animation range", () => {
    expect(getDroneStarflightPose(-1)).toEqual(getDroneStarflightPose(0));
    expect(getDroneStarflightPose(2)).toEqual(getDroneStarflightPose(1));
    expect(getDroneStarflightPose(Number.NaN)).toEqual(getDroneStarflightPose(0));
    expect(getDroneStarflightPose(Number.NEGATIVE_INFINITY))
      .toEqual(getDroneStarflightPose(0));
    expect(getDroneStarflightPose(Number.POSITIVE_INFINITY))
      .toEqual(getDroneStarflightPose(1));
  });
});
