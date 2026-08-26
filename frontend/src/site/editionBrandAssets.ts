import agentLockup from "../../../brand/icons/agent-lockup.png";
import agentMark from "../../../brand/icons/agent-mark.png";
import fieldLockup from "../../../brand/icons/field-lockup.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labLockup from "../../../brand/icons/lab-lockup.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simLockup from "../../../brand/icons/sim-lockup.png";
import simMark from "../../../brand/icons/sim-mark.png";
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
