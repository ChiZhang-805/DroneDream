import type {
  BackendCapabilitiesResponse,
  OptimizerStrategy,
  SimulatorBackend,
} from "../../types/api";

export interface RuntimeCapabilityErrors {
  simulator_backend?: string;
  optimizer_strategy?: string;
}

/** Convert discovered backend prerequisites into form-level blocking errors. */
export function runtimeCapabilityErrors(
  simulatorBackend: SimulatorBackend,
  optimizerStrategy: OptimizerStrategy,
  capabilities: BackendCapabilitiesResponse | null,
): RuntimeCapabilityErrors {
  if (!capabilities) return {};
  const errors: RuntimeCapabilityErrors = {};
  if (simulatorBackend === "real_cli" && capabilities.simulators.authoritative) {
    const capability = capabilities.simulators.items.real_cli;
    if (!capability || !capability.ready) {
      errors.simulator_backend =
        capability?.reason ?? "The real simulator runtime is not ready";
    }
  }
  if (optimizerStrategy === "gpt") {
    const capability = capabilities.optimizers.items.gpt;
    // A negative result from the API process is authoritative because job
    // creation cannot encrypt the supplied credential. A positive result is
    // advisory until a separately deployed worker publishes its own health.
    if (!capability || !capability.ready) {
      errors.optimizer_strategy =
        capability?.reason ??
        "The backend secret store is not configured for GPT optimization";
    }
  }
  return errors;
}
