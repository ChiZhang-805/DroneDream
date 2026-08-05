import fieldDotLockup from "./assets/editions/dronedream-field-dot-lockup.png";
import fieldMark from "./assets/editions/dronedream-field-mark.png";
import labDotLockup from "./assets/editions/dronedream-lab-dot-lockup.png";
import labMark from "./assets/editions/dronedream-lab-mark.png";
import simDotLockup from "./assets/editions/dronedream-sim-dot-lockup.png";
import simMark from "./assets/editions/dronedream-sim-mark.png";
import type { PrimaryEditionId } from "./editionAvailability";

type EditionBrandAsset = {
  mark: string;
  dotLockup: string;
};

export const editionBrandAssets: Record<PrimaryEditionId, EditionBrandAsset> = {
  sim: { mark: simMark, dotLockup: simDotLockup },
  lab: { mark: labMark, dotLockup: labDotLockup },
  field: { mark: fieldMark, dotLockup: fieldDotLockup },
};
