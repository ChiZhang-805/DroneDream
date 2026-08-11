import { describe, expect, it } from "vitest";

import {
  LAUNCHER_MINIMUM_DURATION_MS,
  LAUNCHER_PROGRESS_MILESTONES,
} from "../desktop/launcherProgress";

describe("launcher progress contract", () => {
  it("uses a five-second production sequence without an intermediate action point", () => {
    expect(LAUNCHER_MINIMUM_DURATION_MS).toBe(5_000);

    const times = LAUNCHER_PROGRESS_MILESTONES.map(({ at }) => at);
    const values = LAUNCHER_PROGRESS_MILESTONES.map(({ value }) => value);

    expect(times.every((time, index) => index === 0 || time > times[index - 1])).toBe(true);
    expect(values.every((value, index) => index === 0 || value > values[index - 1])).toBe(true);
    expect(values[0]).toBeGreaterThan(0);
    expect(values.at(-1)).toBe(96);
    expect(values).not.toContain(99);
    expect(values).not.toContain(100);
  });
});
