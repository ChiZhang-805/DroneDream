import { describe, expect, it } from "vitest";

import { calculateTrialPlan, optimizerBatchTarget } from "../features/experiment/trialPlan";

const validInput = {
  searchSeedCount: 3,
  holdoutSeedCount: 2,
  searchCaseCount: 2,
  holdoutCaseCount: 1,
  maxIterations: 4,
  maxTotalTrials: 100,
  optimizerStrategy: "heuristic" as const,
  selectedDimensions: 4,
};

describe("experiment trial planning", () => {
  it("schedules only complete scenario matrices within the hard budget", () => {
    const plan = calculateTrialPlan({ ...validInput, maxTotalTrials: 35 });

    expect(plan.scenarioTrialsPerCandidate).toBe(8);
    expect(plan.plannedTrials).toBe(40);
    expect(plan.scheduledTrials).toBe(32);
    expect(plan.candidateCount).toBe(4);
    expect(plan.capped).toBe(true);
  });

  it("requires a baseline and a candidate for optimizer runs", () => {
    expect(calculateTrialPlan(validInput).minimumRequiredTrials).toBe(16);
    expect(calculateTrialPlan({
      ...validInput,
      optimizerStrategy: "none",
    }).minimumRequiredTrials).toBe(8);
  });

  it("fails closed when seeds or search cases are invalid", () => {
    expect(calculateTrialPlan({
      ...validInput,
      searchSeedCount: null,
    }).scenarioTrialsPerCandidate).toBe(0);
    expect(calculateTrialPlan({
      ...validInput,
      searchCaseCount: 0,
    }).scheduledTrials).toBe(0);
  });

  it("scales experimental optimizer batches while retaining legacy compatibility", () => {
    expect(optimizerBatchTarget("heuristic", 20)).toBe(1);
    expect(optimizerBatchTarget("turbo", 1)).toBe(2);
    expect(optimizerBatchTarget("turbo", 20)).toBe(4);
    expect(optimizerBatchTarget("optimizer_portfolio", 1)).toBe(4);
    expect(optimizerBatchTarget("optimizer_portfolio", 20)).toBe(12);
  });
});
