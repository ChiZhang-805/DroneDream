import { describe, expect, it } from "vitest";

import {
  AdaptiveDprController,
  buildAdaptiveDprSteps,
  estimateRefreshInterval,
  renderGapBudget,
  shouldRunDroneRenderLoop,
} from "../components/droneRenderPerformance";

describe("drone render performance controller", () => {
  it("fully stops the render loop for reduced motion, hidden documents, and offscreen scenes", () => {
    const visibleScene = {
      inViewport: true,
      documentVisible: true,
      contextHealthy: true,
      reducedMotion: false,
    };
    expect(shouldRunDroneRenderLoop(visibleScene)).toBe(true);
    expect(shouldRunDroneRenderLoop({ ...visibleScene, reducedMotion: true })).toBe(false);
    expect(shouldRunDroneRenderLoop({ ...visibleScene, documentVisible: false })).toBe(false);
    expect(shouldRunDroneRenderLoop({ ...visibleScene, inViewport: false })).toBe(false);
    expect(shouldRunDroneRenderLoop({ ...visibleScene, contextHealthy: false })).toBe(false);
  });
  it("starts conservatively while retaining quality steps up to the display DPR", () => {
    expect(buildAdaptiveDprSteps(2)).toEqual([0.85, 1, 1.25, 1.5, 1.8]);
    expect(buildAdaptiveDprSteps(1.25)).toEqual([0.85, 1, 1.25]);

    const controller = new AdaptiveDprController(2, 0);
    expect(controller.currentDpr).toBe(1.25);
  });

  it("estimates the display cadence without treating occasional long frames as refresh rate", () => {
    const samples = [16.5, 16.7, 33.2, 16.6, 16.8, 48, 16.7];
    expect(estimateRefreshInterval(samples)).toBeCloseTo(16.6, 1);
    expect(renderGapBudget(16.7)).toBeGreaterThan(21);
    expect(renderGapBudget(33.3)).toBeGreaterThan(43);
  });

  it("drops one DPR step after sustained missed frames", () => {
    const controller = new AdaptiveDprController(2, 0);
    let changed: number | null = null;

    for (let now = 1_600; now <= 3_200 && changed === null; now += 50) {
      changed = controller.recordFrameGap({
        gapMs: 40,
        budgetMs: 21.7,
        now,
        interactive: true,
      });
    }

    expect(changed).toBe(1);
    expect(controller.currentDpr).toBe(1);
  });

  it("only raises quality after a long stable interactive period and returns to idle", () => {
    const controller = new AdaptiveDprController(2, 0);
    let changed: number | null = null;

    for (let now = 1_600; now <= 14_000; now += 100) {
      changed = controller.recordFrameGap({
        gapMs: 16.7,
        budgetMs: 21.7,
        now,
        interactive: true,
      });
      expect(changed).toBeNull();
    }

    changed = controller.recordFrameGap({
      gapMs: 16.7,
      budgetMs: 21.7,
      now: 14_100,
      interactive: false,
    });
    expect(changed).toBe(1.5);
    expect(controller.currentDpr).toBe(1.5);
  });
});
