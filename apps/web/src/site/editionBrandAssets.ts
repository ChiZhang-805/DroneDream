import agentLockup from "../../../../shared/brand/icons/agent-lockup.png";
import agentMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldLockup from "../../../../shared/brand/icons/field-lockup.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labLockup from "../../../../shared/brand/icons/lab-lockup.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simLockup from "../../../../shared/brand/icons/sim-lockup.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import type { EditionAvailabilityId } from "./editionAvailability";

export const editionBrandAssets: Record<EditionAvailabilityId, {
  mark: string;
  lockup: string;
}> = {
  sim: { mark: simMark, lockup: simLockup },
  lab: { mark: labMark, lockup: labLockup },
  field: { mark: fieldMark, lockup: fieldLockup },
  autonomy: { mark: agentMark, lockup: agentLockup },
};
