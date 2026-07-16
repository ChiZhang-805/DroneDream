import type { TranslationKey } from "../../i18n/I18nProvider";
import type { OptimizerStrategy } from "../../types/api";

interface OptimizerStrategyPresentation {
  label: TranslationKey;
  description: TranslationKey;
}

type Translate = (key: TranslationKey) => string;

const PRESENTATION: Record<OptimizerStrategy, OptimizerStrategyPresentation> = {
  none: {
    label: "optimizer.none.label",
    description: "optimizer.none.description",
  },
  heuristic: {
    label: "optimizer.heuristic.label",
    description: "optimizer.heuristic.description",
  },
  gpt: {
    label: "optimizer.gpt.label",
    description: "optimizer.gpt.description",
  },
  cma_es: {
    label: "optimizer.cmaEs.label",
    description: "optimizer.cmaEs.description",
  },
  constrained_mobo: {
    label: "optimizer.constrainedMobo.label",
    description: "optimizer.constrainedMobo.description",
  },
  multi_fidelity_mobo: {
    label: "optimizer.multiFidelityMobo.label",
    description: "optimizer.multiFidelityMobo.description",
  },
  turbo: {
    label: "optimizer.turbo.label",
    description: "optimizer.turbo.description",
  },
  saasbo: {
    label: "optimizer.saasbo.label",
    description: "optimizer.saasbo.description",
  },
  surrogate_cma_es: {
    label: "optimizer.surrogateCmaEs.label",
    description: "optimizer.surrogateCmaEs.description",
  },
  bipop_cma_es: {
    label: "optimizer.bipopCmaEs.label",
    description: "optimizer.bipopCmaEs.description",
  },
  optimizer_portfolio: {
    label: "optimizer.portfolio.label",
    description: "optimizer.portfolio.description",
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
