import { LabSetup } from "./LabSetup";

/**
 * The primary LAB sidebar lands directly on the qualification evidence tool,
 * while the full LAB workspace keeps all calibration/setup/safety tabs.
 */
export function LabValidationWorkspace() {
  return <LabSetup initialView="evidence" />;
}
