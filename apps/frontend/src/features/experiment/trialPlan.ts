import { EXPERIMENTAL_OPTIMIZER_STRATEGIES } from "../../types/api";
import type { OptimizerStrategy } from "../../types/api";

export interface TrialPlanInput {
  searchSeedCount: number | null;
  holdoutSeedCount: number | null;
  searchCaseCount: number;
  holdoutCaseCount: number;
  maxIterations: number | null;
  maxTotalTrials: number | null;
  optimizerStrategy: OptimizerStrategy;
  selectedDimensions: number;
}

export interface TrialPlan {
  scenarioTrialsPerCandidate: number;
  candidateCount: number;
  plannedTrials: number;
  scheduledTrials: number;
  minimumRequiredTrials: number;
  capped: boolean;
}

export function optimizerBatchTarget(
  strategy: OptimizerStrategy,
  selectedDimensions: number,
): number {
  if (!EXPERIMENTAL_OPTIMIZER_STRATEGIES.some((item) => item === strategy)) {
    return 1;
  }
  const dimensions = Math.max(1, selectedDimensions);
  if (["surrogate_cma_es", "bipop_cma_es", "optimizer_portfolio"].includes(strategy)) {
    return Math.max(4, Math.min(12, 4 + Math.floor(3 * Math.log(dimensions))));
  }
  return Math.max(2, Math.min(4, dimensions));
}

export function calculateTrialPlan(input: TrialPlanInput): TrialPlan {
  const invalidSearch = input.searchSeedCount === null || input.searchCaseCount === 0;
  const invalidHoldout = input.holdoutCaseCount > 0 && input.holdoutSeedCount === null;
  const scenarioTrialsPerCandidate = invalidSearch || invalidHoldout
    ? 0
    : (input.searchSeedCount ?? 0) * input.searchCaseCount
      + (input.holdoutSeedCount ?? 0) * input.holdoutCaseCount;
  const optimizerCandidatesPerGeneration = optimizerBatchTarget(
    input.optimizerStrategy,
    input.selectedDimensions,
  );
  const plannedCandidateCount = input.optimizerStrategy === "none"
    ? 1
    : 1 + (
      input.maxIterations && Number.isInteger(input.maxIterations) && input.maxIterations > 0
        ? input.maxIterations * optimizerCandidatesPerGeneration
        : 0
    );
  const plannedTrials = scenarioTrialsPerCandidate * plannedCandidateCount;
  const budgetedCompleteTrials = input.maxTotalTrials
    && input.maxTotalTrials > 0
    && scenarioTrialsPerCandidate > 0
    ? scenarioTrialsPerCandidate * Math.floor(input.maxTotalTrials / scenarioTrialsPerCandidate)
    : 0;
  const scheduledTrials = Math.min(plannedTrials, budgetedCompleteTrials);
  const candidateCount = scenarioTrialsPerCandidate > 0
    ? Math.floor(scheduledTrials / scenarioTrialsPerCandidate)
    : plannedCandidateCount;
  const minimumRequiredTrials = scenarioTrialsPerCandidate * (
    input.optimizerStrategy === "none" ? 1 : 2
  );
  return {
    scenarioTrialsPerCandidate,
    candidateCount,
    plannedTrials,
    scheduledTrials,
    minimumRequiredTrials,
    capped: plannedTrials > scheduledTrials,
  };
}
