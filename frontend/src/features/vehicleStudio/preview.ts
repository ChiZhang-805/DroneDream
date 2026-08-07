import type { VehicleModelDraft } from "./model";

export interface VehiclePreviewGeometry {
  body: { shape: VehicleModelDraft["body"]["shape"]; x: number; y: number; z: number };
  rotors: Array<{ x: number; z: number; radius: number }>;
  scale: number;
}

export function buildVehiclePreviewGeometry(
  draft: VehicleModelDraft,
): VehiclePreviewGeometry {
  const maximumSpan = Math.max(
    draft.body.lengthM,
    draft.body.widthM,
    draft.body.heightM,
    draft.propulsion.armLengthM * 2 + draft.propulsion.propellerDiameterM,
    0.01,
  );
  const scale = 2.35 / maximumSpan;
  return {
    body: {
      shape: draft.body.shape,
      x: draft.body.lengthM * scale,
      y: draft.body.heightM * scale,
      z: draft.body.widthM * scale,
    },
    rotors: Array.from({ length: draft.propulsion.motorCount }, (_, index) => {
      const angle = (Math.PI * 2 * index) / draft.propulsion.motorCount;
      return {
        x: Math.cos(angle) * draft.propulsion.armLengthM * scale,
        z: Math.sin(angle) * draft.propulsion.armLengthM * scale,
        radius: draft.propulsion.propellerDiameterM * scale / 2,
      };
    }),
    scale,
  };
}
