import fieldLockup from "../assets/brand/field-lockup-primary.png";
import fieldMark from "../assets/brand/field-mark.png";
import labLockup from "../assets/brand/lab-lockup-primary.png";
import labMark from "../assets/brand/lab-mark.png";
import simLockup from "../assets/brand/sim-lockup-primary.png";
import simMark from "../assets/brand/sim-mark.png";
import type { PrimaryEditionId } from "./editionAvailability";

export const editionBrandAssets: Record<PrimaryEditionId, {
  mark: string;
  lockup: string;
}> = {
  sim: { mark: simMark, lockup: simLockup },
  lab: { mark: labMark, lockup: labLockup },
  field: { mark: fieldMark, lockup: fieldLockup },
};
