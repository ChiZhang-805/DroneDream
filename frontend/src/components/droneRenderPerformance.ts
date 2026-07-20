export const DRONE_IDLE_FPS = 40;
export const DRONE_INTERACTIVE_FPS = 60;
export const DRONE_INTERACTION_TAIL_MS = 450;

export function shouldRunDroneRenderLoop({
  inViewport,
  documentVisible,
  contextHealthy,
  reducedMotion,
}: {
  inViewport: boolean;
  documentVisible: boolean;
  contextHealthy: boolean;
  reducedMotion: boolean;
}) {
  return inViewport && documentVisible && contextHealthy && !reducedMotion;
}

const DPR_CAPS = [0.85, 1, 1.25, 1.5, 1.8] as const;
const QUALITY_WARMUP_MS = 1_500;
const QUALITY_DOWN_HOLD_MS = 1_200;
const QUALITY_UP_HOLD_MS = 8_000;
const QUALITY_DOWN_COOLDOWN_MS = 3_000;
const QUALITY_UP_COOLDOWN_MS = 10_000;

function uniqueAscending(values: number[]) {
  return values
    .filter((value, index, source) => index === 0 || Math.abs(value - source[index - 1]) > 0.001);
}

export function buildAdaptiveDprSteps(devicePixelRatio: number) {
  const safeDevicePixelRatio = Number.isFinite(devicePixelRatio)
    ? Math.min(1.8, Math.max(0.75, devicePixelRatio))
    : 1;
  return uniqueAscending(
    DPR_CAPS
      .map((cap) => Math.min(cap, safeDevicePixelRatio))
      .sort((first, second) => first - second),
  );
}

export function estimateRefreshInterval(samples: number[]) {
  const validSamples = samples
    .filter((sample) => Number.isFinite(sample) && sample >= 4 && sample <= 50)
    .sort((first, second) => first - second);
  if (validSamples.length === 0) return 1000 / 60;
  return validSamples[Math.floor((validSamples.length - 1) * 0.2)];
}

export function renderGapBudget(refreshIntervalMs: number) {
  const safeInterval = Number.isFinite(refreshIntervalMs) && refreshIntervalMs > 0
    ? refreshIntervalMs
    : 1000 / 60;
  return Math.max(1000 / 60, safeInterval * 1.3);
}

export class AdaptiveDprController {
  readonly steps: number[];

  private index: number;
  private samples: number[] = [];
  private ema: number | null = null;
  private badSince: number | null = null;
  private goodSince: number | null = null;
  private warmupUntil: number;
  private cooldownUntil: number;
  private upgradeReady = false;

  constructor(devicePixelRatio: number, now = 0) {
    this.steps = buildAdaptiveDprSteps(devicePixelRatio);
    const safeStartingCap = Math.min(devicePixelRatio || 1, 1.25);
    this.index = 0;
    this.steps.forEach((step, index) => {
      if (step <= safeStartingCap + 0.001) this.index = index;
    });
    this.warmupUntil = now + QUALITY_WARMUP_MS;
    this.cooldownUntil = now;
  }

  get currentDpr() {
    return this.steps[this.index];
  }

  resetMeasurements(now: number) {
    this.samples = [];
    this.ema = null;
    this.badSince = null;
    this.goodSince = null;
    this.upgradeReady = false;
    this.warmupUntil = now + QUALITY_WARMUP_MS;
  }

  recordFrameGap({
    gapMs,
    budgetMs,
    now,
    interactive,
  }: {
    gapMs: number;
    budgetMs: number;
    now: number;
    interactive: boolean;
  }) {
    if (!Number.isFinite(gapMs) || gapMs <= 0 || now < this.warmupUntil) return null;

    this.ema = this.ema === null ? gapMs : this.ema * 0.92 + gapMs * 0.08;
    this.samples.push(gapMs);
    if (this.samples.length > 60) this.samples.shift();

    const recent = this.samples.slice(-60);
    const slowRatio = recent.filter((sample) => sample > budgetMs * 1.5).length /
      Math.max(recent.length, 1);
    const catastrophicThreshold = Math.max(50, budgetMs * 2.2);
    const catastrophic = recent.slice(-10)
      .filter((sample) => sample > catastrophicThreshold).length >= 3;
    const struggling = this.ema > budgetMs * 1.22 ||
      (recent.length >= 20 && slowRatio >= 0.2);

    if (struggling) {
      this.badSince ??= now;
    } else {
      this.badSince = null;
    }

    if (
      this.index > 0 &&
      now >= this.cooldownUntil &&
      (catastrophic || (this.badSince !== null && now - this.badSince >= QUALITY_DOWN_HOLD_MS))
    ) {
      this.index -= 1;
      this.cooldownUntil = now + QUALITY_DOWN_COOLDOWN_MS;
      this.resetMeasurements(now);
      return this.currentDpr;
    }

    const comfortablyFast = interactive &&
      this.ema < budgetMs * 1.05 &&
      recent.length >= 30 &&
      slowRatio < 0.03;
    if (comfortablyFast) {
      this.goodSince ??= now;
      if (now - this.goodSince >= QUALITY_UP_HOLD_MS) this.upgradeReady = true;
    } else if (interactive) {
      this.goodSince = null;
    }

    if (
      !interactive &&
      this.upgradeReady &&
      this.index < this.steps.length - 1 &&
      now >= this.cooldownUntil
    ) {
      this.index += 1;
      this.cooldownUntil = now + QUALITY_UP_COOLDOWN_MS;
      this.resetMeasurements(now);
      return this.currentDpr;
    }

    return null;
  }
}
