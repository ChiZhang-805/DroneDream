import type { BrandEditionId } from "../../brand/edition-brand.generated";

export const ASSISTANT_ARTIFACT_KINDS = [
  "autonomy_mission_plan",
  "external_asset_qualification_plan",
  "universal_vehicle_model",
  "universal_simulation_experiment",
  "universal_cross_edition_workflow",
  "simulation_experiment",
  "lab_simulation_experiment",
  "lab_hardware_validation",
  "lab_calibration_workflow",
  "lab_sim_to_real_workflow",
  "lab_real_to_sim_workflow",
  "field_task_plan",
] as const;

export type AssistantArtifactKind = typeof ASSISTANT_ARTIFACT_KINDS[number];

export function isAssistantArtifactKind(value: unknown): value is AssistantArtifactKind {
  return typeof value === "string"
    && ASSISTANT_ARTIFACT_KINDS.includes(value as AssistantArtifactKind);
}

interface AssistantArtifactPolicyOptions {
  legacyRead?: boolean;
}

/**
 * Product-owned artifact boundary shared by parsing, local persistence, and UI routing.
 *
 * Universal and AGENT used to expose Vehicle Studio. Existing records remain readable
 * so users do not lose task history, but all new asset work must use an external asset
 * import and qualification plan instead of an in-app geometry editor.
 */
export function assistantArtifactMatchesEdition(
  edition: BrandEditionId,
  artifactKind: AssistantArtifactKind,
  options: AssistantArtifactPolicyOptions = {},
): boolean {
  if (edition === "universal") {
    return artifactKind === "autonomy_mission_plan"
      || artifactKind === "external_asset_qualification_plan"
      || (options.legacyRead === true && artifactKind === "universal_vehicle_model")
      || artifactKind === "universal_simulation_experiment"
      || artifactKind === "universal_cross_edition_workflow"
      || artifactKind === "lab_hardware_validation"
      || artifactKind === "lab_calibration_workflow"
      || artifactKind === "lab_sim_to_real_workflow"
      || artifactKind === "lab_real_to_sim_workflow"
      || artifactKind === "field_task_plan";
  }
  if (edition === "sim") {
    return artifactKind === "autonomy_mission_plan"
      || artifactKind === "external_asset_qualification_plan"
      || artifactKind === "simulation_experiment";
  }
  if (edition === "field") {
    return artifactKind === "autonomy_mission_plan"
      || artifactKind === "external_asset_qualification_plan"
      || artifactKind === "field_task_plan";
  }
  if (edition === "autonomy") {
    return artifactKind === "autonomy_mission_plan"
      || artifactKind === "external_asset_qualification_plan"
      || artifactKind === "simulation_experiment"
      || (options.legacyRead === true && artifactKind === "universal_vehicle_model");
  }
  return artifactKind === "autonomy_mission_plan"
    || artifactKind === "external_asset_qualification_plan"
    || artifactKind.startsWith("lab_");
}
