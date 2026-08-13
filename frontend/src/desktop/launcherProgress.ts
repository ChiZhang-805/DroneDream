import { useEffect, useRef, useState } from "react";

export const LAUNCHER_MINIMUM_DURATION_MS = 5_000;

export const LAUNCHER_PROGRESS_MILESTONES = [
  { at: 0.02, value: 2 },
  { at: 0.06, value: 7 },
  { at: 0.12, value: 14 },
  { at: 0.2, value: 24 },
  { at: 0.31, value: 37 },
  { at: 0.44, value: 52 },
  { at: 0.58, value: 66 },
  { at: 0.72, value: 78 },
  { at: 0.84, value: 87 },
  { at: 0.92, value: 92 },
  { at: 0.98, value: 96 },
] as const;

function effectiveLauncherDuration(): number {
  // Component tests validate the milestone contract separately and should not
  // spend five real seconds on every ready-launcher fixture. Production and
  // headed preview builds always use the full visual duration.
  const vitestFlag = (import.meta.env as Record<string, string | boolean | undefined>).VITEST;
  const jsdomHarness = typeof navigator !== "undefined" &&
    /\bjsdom\b/iu.test(navigator.userAgent);
  return import.meta.env.MODE === "test" || vitestFlag === true || vitestFlag === "true" || jsdomHarness
    ? 0
    : LAUNCHER_MINIMUM_DURATION_MS;
}

/**
 * Presents real readiness work as a calm, staged launch sequence.
 *
 * The sequence never grants authority: it may wait at 96%, but it reaches
 * 100% only after `complete` reports that every real environment check passed.
 * Disabling or blocking the sequence returns it to the only setup action
 * point, 0%.
 */
export function useLauncherProgress({
  enabled,
  complete,
  blocked = false,
}: {
  enabled: boolean;
  complete: boolean;
  blocked?: boolean;
}): number {
  const [progress, setProgress] = useState(0);
  const startedAt = useRef<number | null>(null);
  const duration = effectiveLauncherDuration();

  useEffect(() => {
    if (!enabled || blocked) {
      startedAt.current = null;
      setProgress(0);
      return;
    }

    const start = performance.now();
    startedAt.current = start;
    setProgress(0);

    if (duration === 0) {
      return;
    }

    const timers = LAUNCHER_PROGRESS_MILESTONES.map(({ at, value }) =>
      window.setTimeout(() => setProgress((current) => Math.max(current, value)), at * duration)
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [blocked, duration, enabled]);

  useEffect(() => {
    if (!enabled || blocked || !complete || startedAt.current === null) return;
    if (duration === 0) {
      setProgress(100);
      return;
    }
    const remaining = Math.max(
      0,
      duration - (performance.now() - startedAt.current),
    );
    const timer = window.setTimeout(() => setProgress(100), remaining);
    return () => window.clearTimeout(timer);
  }, [blocked, complete, duration, enabled]);

  return progress;
}
