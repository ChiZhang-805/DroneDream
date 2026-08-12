import fieldMark from "../assets/brand/field-mark.png";
import labMark from "../assets/brand/lab-mark.png";
import simMark from "../assets/brand/sim-mark.png";
import type { PrimaryEditionId } from "./editionAvailability";

export const editionBrandAssets: Record<PrimaryEditionId, {
  mark: string;
}> = {
  sim: { mark: simMark },
  lab: { mark: labMark },
  field: { mark: fieldMark },
};
