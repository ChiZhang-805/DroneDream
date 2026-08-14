import type {
  VehicleComponentDraft,
  VehicleModelDraft,
  VehiclePrimitive,
  VehicleVector3,
} from "./model";

export interface VehiclePreviewComponent {
  id: string;
  name: string;
  kind: VehicleComponentDraft["kind"];
  primitive: VehiclePrimitive;
  position: VehicleVector3;
  rotationRad: VehicleVector3;
  scale: VehicleVector3;
  size: VehicleVector3;
  radius: number;
  length: number;
  color: string;
  metalness: number;
  roughness: number;
  opacity: number;
  visible: boolean;
}

export interface VehiclePreviewGeometry {
  body: { shape: VehicleModelDraft["body"]["shape"]; x: number; y: number; z: number };
  rotors: Array<{ x: number; z: number; radius: number }>;
  components: VehiclePreviewComponent[];
  scale: number;
  bounds: { span: number; height: number };
}

function componentExtent(component: VehicleComponentDraft): number {
  const geometryExtent = Math.max(
    component.geometry.sizeM.x * component.transform.scale.x,
    component.geometry.sizeM.y * component.transform.scale.y,
    component.geometry.sizeM.z * component.transform.scale.z,
    component.geometry.radiusM * 2,
    component.geometry.lengthM,
  );
  return Math.max(
    Math.abs(component.transform.positionM.x) * 2 + geometryExtent,
    Math.abs(component.transform.positionM.z) * 2 + geometryExtent,
  );
}

function toPreviewComponent(component: VehicleComponentDraft, scale: number): VehiclePreviewComponent {
  return {
    id: component.id,
    name: component.name,
    kind: component.kind,
    primitive: component.geometry.primitive,
    position: {
      x: component.transform.positionM.x * scale,
      y: component.transform.positionM.y * scale,
      z: component.transform.positionM.z * scale,
    },
    rotationRad: {
      x: component.transform.rotationDeg.x * Math.PI / 180,
      y: component.transform.rotationDeg.y * Math.PI / 180,
      z: component.transform.rotationDeg.z * Math.PI / 180,
    },
    scale: { ...component.transform.scale },
    size: {
      x: component.geometry.sizeM.x * scale,
      y: component.geometry.sizeM.y * scale,
      z: component.geometry.sizeM.z * scale,
    },
    radius: component.geometry.radiusM * scale,
    length: component.geometry.lengthM * scale,
    color: component.material.baseColor,
    metalness: component.material.metalness,
    roughness: component.material.roughness,
    opacity: component.material.opacity,
    visible: component.visible,
  };
}

export function buildVehiclePreviewGeometry(draft: VehicleModelDraft): VehiclePreviewGeometry {
  const componentSpan = draft.components.reduce(
    (maximum, component) => Math.max(maximum, componentExtent(component)),
    0,
  );
  const maximumSpan = Math.max(
    componentSpan,
    draft.body.lengthM,
    draft.body.widthM,
    draft.body.heightM,
    draft.propulsion.armLengthM * 2 + draft.propulsion.propellerDiameterM,
    0.01,
  );
  const scale = 2.85 / maximumSpan;
  const components = draft.components.map((component) => toPreviewComponent(component, scale));
  const height = draft.components.reduce((maximum, component) => Math.max(
    maximum,
    Math.abs(component.transform.positionM.y) * 2 + Math.max(component.geometry.sizeM.y, component.geometry.radiusM * 2),
  ), 0) * scale;

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
    components,
    scale,
    bounds: { span: maximumSpan * scale, height },
  };
}
