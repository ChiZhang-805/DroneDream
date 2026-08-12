import fieldLockup from "../../../brand/commercial/field-lockup.png";
import fieldMark from "../../../brand/commercial/field-mark.png";
import labLockup from "../../../brand/commercial/lab-lockup.png";
import labMark from "../../../brand/commercial/lab-mark.png";
import simLockup from "../../../brand/commercial/sim-lockup.png";
import simMark from "../../../brand/commercial/sim-mark.png";
import type { PrimaryEditionId } from "./editionAvailability";

export const editionBrandAssets: Record<PrimaryEditionId, {
  mark: string;
  lockup: string;
}> = {
  sim: { mark: simMark, lockup: simLockup },
  lab: { mark: labMark, lockup: labLockup },
  field: { mark: fieldMark, lockup: fieldLockup },
};
