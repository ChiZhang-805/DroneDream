import fieldLockup from "../assets/brand/field-lockup-primary.png";
import fieldMark from "./assets/editions/dronedream-field-mark.png";
import labLockup from "../assets/brand/lab-lockup-primary.png";
import labMark from "./assets/editions/dronedream-lab-mark.png";
import simLockup from "../assets/brand/sim-lockup-primary.png";
import simMark from "./assets/editions/dronedream-sim-mark.png";
import universalLockup from "../assets/drone-dream-lockup-primary.png";
import universalMark from "../assets/drone-dream-mark.png";
import type { EditionId } from "./editionAvailability";

type EditionBrandAsset = {
  mark: string;
  lockup: string;
  lockupWidth: number;
  lockupHeight: number;
};

export const editionBrandAssets: Record<EditionId, EditionBrandAsset> = {
  sim: { mark: simMark, lockup: simLockup, lockupWidth: 2337, lockupHeight: 218 },
  lab: { mark: labMark, lockup: labLockup, lockupWidth: 2386, lockupHeight: 218 },
  field: { mark: fieldMark, lockup: fieldLockup, lockupWidth: 2581, lockupHeight: 218 },
  universal: {
    mark: universalMark,
    lockup: universalLockup,
    lockupWidth: 1749,
    lockupHeight: 220,
  },
};
