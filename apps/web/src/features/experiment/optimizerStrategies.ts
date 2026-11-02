import type { TranslationKey } from "../../i18n/I18nProvider";
import type { OptimizerStrategy } from "../../types/api";

interface OptimizerStrategyPresentation {
  label: TranslationKey;
  description: TranslationKey;
  cardDetail: TranslationKey;
  flow: readonly [TranslationKey, TranslationKey, TranslationKey, TranslationKey];
}

type Translate = (key: TranslationKey) => string;

const PRESENTATION: Record<OptimizerStrategy, OptimizerStrategyPresentation> = {
  none: {
    label: "optimizer.none.label",
    description: "optimizer.none.description",
    cardDetail: "optimizer.none.cardDetail",
    flow: [
      "wizard.strategyFlow.lockBaseline",
      "wizard.strategyFlow.simulateMatrix",
      "wizard.strategyFlow.aggregateEvidence",
      "wizard.strategyFlow.reportBaseline",
    ],
  },
  heuristic: {
    label: "optimizer.heuristic.label",
    description: "optimizer.heuristic.description",
    cardDetail: "optimizer.heuristic.cardDetail",
    flow: [
      "wizard.strategyFlow.perturbParameters",
      "wizard.strategyFlow.applyConstraints",
      "wizard.strategyFlow.simulateMatrix",
      "wizard.strategyFlow.rankCandidates",
    ],
  },
  gpt: {
    label: "optimizer.gpt.label",
    description: "optimizer.gpt.description",
    cardDetail: "optimizer.gpt.cardDetail",
    flow: [
      "wizard.strategyFlow.summarizeEvidence",
      "wizard.strategyFlow.requestModelProposal",
      "wizard.strategyFlow.validateProposal",
      "wizard.strategyFlow.simulateAndLearn",
    ],
  },
  llm_harness: {
    label: "optimizer.llmHarness.label",
    description: "optimizer.llmHarness.description",
    cardDetail: "optimizer.llmHarness.cardDetail",
    flow: [
      "wizard.strategyFlow.summarizeEvidence",
      "wizard.strategyFlow.selectOptimizerTool",
      "wizard.strategyFlow.executeBoundedTool",
      "wizard.strategyFlow.simulateAndLearn",
    ],
  },
  cma_es: {
    label: "optimizer.cmaEs.label",
    description: "optimizer.cmaEs.description",
    cardDetail: "optimizer.cmaEs.cardDetail",
    flow: [
      "wizard.strategyFlow.samplePopulation",
      "wizard.strategyFlow.simulatePopulation",
      "wizard.strategyFlow.selectElites",
      "wizard.strategyFlow.adaptCovariance",
    ],
  },
  constrained_mobo: {
    label: "optimizer.constrainedMobo.label",
    description: "optimizer.constrainedMobo.description",
    cardDetail: "optimizer.constrainedMobo.cardDetail",
    flow: [
      "wizard.strategyFlow.fitObjectives",
      "wizard.strategyFlow.fitFeasibility",
      "wizard.strategyFlow.acquirePareto",
      "wizard.strategyFlow.verifyCandidate",
    ],
  },
  multi_fidelity_mobo: {
    label: "optimizer.multiFidelityMobo.label",
    description: "optimizer.multiFidelityMobo.description",
    cardDetail: "optimizer.multiFidelityMobo.cardDetail",
    flow: [
      "wizard.strategyFlow.screenCheaply",
      "wizard.strategyFlow.promoteCandidate",
      "wizard.strategyFlow.fullVerification",
      "wizard.strategyFlow.updateFidelities",
    ],
  },
  turbo: {
    label: "optimizer.turbo.label",
    description: "optimizer.turbo.description",
    cardDetail: "optimizer.turbo.cardDetail",
    flow: [
      "wizard.strategyFlow.centerTrustRegion",
      "wizard.strategyFlow.proposeLocally",
      "wizard.strategyFlow.simulateMatrix",
      "wizard.strategyFlow.resizeTrustRegion",
    ],
  },
  saasbo: {
    label: "optimizer.saasbo.label",
    description: "optimizer.saasbo.description",
    cardDetail: "optimizer.saasbo.cardDetail",
    flow: [
      "wizard.strategyFlow.learnSparseAxes",
      "wizard.strategyFlow.acquireCandidate",
      "wizard.strategyFlow.simulateMatrix",
      "wizard.strategyFlow.updateSparseModel",
    ],
  },
  surrogate_cma_es: {
    label: "optimizer.surrogateCmaEs.label",
    description: "optimizer.surrogateCmaEs.description",
    cardDetail: "optimizer.surrogateCmaEs.cardDetail",
    flow: [
      "wizard.strategyFlow.samplePopulation",
      "wizard.strategyFlow.predictWithSurrogate",
      "wizard.strategyFlow.evaluateElite",
      "wizard.strategyFlow.adaptCovariance",
    ],
  },
  bipop_cma_es: {
    label: "optimizer.bipopCmaEs.label",
    description: "optimizer.bipopCmaEs.description",
    cardDetail: "optimizer.bipopCmaEs.cardDetail",
    flow: [
      "wizard.strategyFlow.chooseRestartScale",
      "wizard.strategyFlow.samplePopulation",
      "wizard.strategyFlow.simulatePopulation",
      "wizard.strategyFlow.scheduleRestart",
    ],
  },
  optimizer_portfolio: {
    label: "optimizer.portfolio.label",
    description: "optimizer.portfolio.description",
    cardDetail: "optimizer.portfolio.cardDetail",
    flow: [
      "wizard.strategyFlow.allocateEngines",
      "wizard.strategyFlow.collectProposals",
      "wizard.strategyFlow.verifyCandidate",
      "wizard.strategyFlow.reweightEngines",
    ],
  },
};

export function optimizerStrategyLabel(
  strategy: OptimizerStrategy,
  t: Translate,
): string {
  return t(PRESENTATION[strategy].label);
}

export function optimizerStrategyDescription(
  strategy: OptimizerStrategy,
  t: Translate,
): string {
  return t(PRESENTATION[strategy].description);
}

export function optimizerStrategyCard(
  strategy: OptimizerStrategy,
  t: Translate,
): {
  label: string;
  description: string;
  detail: string;
  flow: readonly [string, string, string, string];
} {
  const presentation = PRESENTATION[strategy];
  return {
    label: t(presentation.label),
    description: t(presentation.description),
    detail: t(presentation.cardDetail),
    flow: presentation.flow.map((key) => t(key)) as unknown as readonly [
      string,
      string,
      string,
      string,
    ],
  };
}
