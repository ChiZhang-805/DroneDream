import { useEffect, useId, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";

import { calculateVehicleDiagnostics, type VehicleModelDraft } from "../features/vehicleStudio/model";
import {
  buildVehiclePreviewGeometry,
  previewPositionToModel,
  type VehiclePreviewComponent,
} from "../features/vehicleStudio/preview";

interface PreviewCopy {
  ariaLabel: string;
  unavailable: string;
  interaction: string;
  motors: string;
  ratio: string;
}

interface VehicleModelPreview3DProps {
  draft: VehicleModelDraft;
  copy: PreviewCopy;
  selectedComponentId?: string | null;
  onSelectComponent?: (componentId: string | null) => void;
  wireframe?: boolean;
  exploded?: boolean;
  showGrid?: boolean;
  manipulator?: "select" | "move" | "rotate" | "scale";
  viewPreset?: "isometric" | "top" | "front" | "side";
  transformSpace?: "world" | "local";
  snapEnabled?: boolean;
  translationSnapM?: number;
  showEngineeringOverlay?: boolean;
  isolatedComponentId?: string | null;
  frameMode?: "assembly" | "selection";
  onTransformComponent?: (componentId: string, transform: {
    positionM: { x: number; y: number; z: number };
    rotationDeg: { x: number; y: number; z: number };
    scale: { x: number; y: number; z: number };
  }) => void;
}

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function primitiveGeometry(component: VehiclePreviewComponent): THREE.BufferGeometry {
  const { primitive, size, radius, length } = component;
  if (primitive === "cylinder") return new THREE.CylinderGeometry(Math.max(radius, .012), Math.max(radius, .012), Math.max(length, .02), 32);
  if (primitive === "sphere") return new THREE.SphereGeometry(Math.max(radius, .018), 32, 20);
  if (primitive === "capsule") return new THREE.CapsuleGeometry(Math.max(radius, .012), Math.max(.01, length - radius * 2), 10, 24);
  if (primitive === "cone") return new THREE.ConeGeometry(Math.max(radius, .012), Math.max(length, .02), 32);
  return new THREE.BoxGeometry(Math.max(size.x, .012), Math.max(size.y, .012), Math.max(size.z, .012), 2, 2, 2);
}

const ENGINEERING_PRIMITIVE_BY_KIND: Partial<Record<VehiclePreviewComponent["kind"], VehiclePreviewComponent["primitive"]>> = {
  fuselage: "rounded-box",
  frame: "rounded-box",
  arm: "rounded-box",
  motor: "cylinder",
  propeller: "rounded-box",
  "landing-gear": "rounded-box",
  battery: "rounded-box",
  "flight-controller": "rounded-box",
  sensor: "cylinder",
  "camera-gimbal": "sphere",
  payload: "rounded-box",
};

function materialFor(component: VehiclePreviewComponent, options: Partial<THREE.MeshStandardMaterialParameters> = {}) {
  return new THREE.MeshStandardMaterial({
    color: component.color,
    metalness: component.metalness,
    roughness: component.roughness,
    opacity: component.opacity,
    transparent: component.opacity < .999,
    ...options,
  });
}

function addPart(
  group: THREE.Group,
  geometry: THREE.BufferGeometry,
  material: THREE.Material,
  position: [number, number, number] = [0, 0, 0],
  rotation: [number, number, number] = [0, 0, 0],
) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(...position);
  mesh.rotation.set(...rotation);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function buildEngineeringComponent(component: VehiclePreviewComponent, wireframe: boolean): THREE.Group {
  const group = new THREE.Group();
  const x = Math.max(component.size.x, .018);
  const y = Math.max(component.size.y, .012);
  const z = Math.max(component.size.z, .018);
  const radius = Math.max(component.radius, .012);
  const length = Math.max(component.length, .02);
  const main = materialFor(component, { wireframe });
  const dark = materialFor(component, { color: new THREE.Color(component.color).multiplyScalar(.34), metalness: .72, roughness: .3, wireframe });
  const light = materialFor(component, { color: new THREE.Color(component.color).lerp(new THREE.Color(0xffffff), .42), metalness: .24, roughness: .28, wireframe });
  const carbon = new THREE.MeshStandardMaterial({ color: 0x171421, metalness: .62, roughness: .32, wireframe });

  // The detailed meshes below are visualizations of each built-in part's default
  // primitive. Once the user chooses a different primitive, the viewport must
  // render that exact engineering selection instead of retaining the decoration.
  if (ENGINEERING_PRIMITIVE_BY_KIND[component.kind] !== component.primitive) {
    addPart(group, primitiveGeometry(component), main);
    group.userData.componentId = component.id;
    group.traverse((object) => { object.userData.componentId = component.id; });
    return group;
  }

  switch (component.kind) {
    case "fuselage": {
      const hull = addPart(group, new THREE.CapsuleGeometry(Math.max(z * .42, .03), Math.max(.02, x - z * .84), 12, 32), main, [0, 0, 0], [0, 0, Math.PI / 2]);
      hull.scale.set(1, Math.max(.65, y / z), 1);
      addPart(group, new THREE.SphereGeometry(Math.max(z * .38, .025), 28, 16, 0, Math.PI * 2, 0, Math.PI / 2), light, [x * .08, y * .38, 0], [0, 0, 0]);
      addPart(group, new THREE.BoxGeometry(x * .56, y * .08, z * .8), carbon, [-x * .03, -y * .48, 0]);
      break;
    }
    case "frame": {
      addPart(group, new THREE.BoxGeometry(x, y * .32, z), carbon, [0, y * .2, 0]);
      addPart(group, new THREE.BoxGeometry(x * .86, y * .26, z * .86), main, [0, -y * .28, 0]);
      for (const px of [-x * .38, x * .38]) for (const pz of [-z * .38, z * .38]) {
        addPart(group, new THREE.CylinderGeometry(y * .13, y * .13, y * .88, 16), light, [px, 0, pz]);
      }
      break;
    }
    case "arm": {
      addPart(group, new THREE.BoxGeometry(x, y * .58, z * .68), carbon);
      addPart(group, new THREE.BoxGeometry(x * .2, y * .9, z), main, [-x * .39, 0, 0]);
      addPart(group, new THREE.CylinderGeometry(z * .5, z * .5, y * .76, 20), dark, [x * .45, 0, 0]);
      break;
    }
    case "motor": {
      addPart(group, new THREE.CylinderGeometry(radius, radius * 1.08, length * .55, 32), dark, [0, -length * .08, 0]);
      addPart(group, new THREE.CylinderGeometry(radius * .9, radius * .98, length * .42, 32), main, [0, length * .31, 0]);
      addPart(group, new THREE.CylinderGeometry(radius * .16, radius * .16, length * .45, 18), light, [0, length * .7, 0]);
      addPart(group, new THREE.TorusGeometry(radius * .78, radius * .07, 10, 32), light, [0, length * .22, 0], [Math.PI / 2, 0, 0]);
      break;
    }
    case "propeller": {
      const diameter = Math.max(x, z, .12);
      const bladeLength = diameter * .46;
      const bladeWidth = diameter * .075;
      addPart(group, new THREE.CylinderGeometry(diameter * .055, diameter * .055, y * 1.8, 24), dark);
      for (const sign of [-1, 1]) {
        const blade = addPart(group, new THREE.BoxGeometry(bladeLength, Math.max(y, .008), bladeWidth), main, [sign * bladeLength * .48, 0, 0], [0, sign * .13, sign * .05]);
        blade.geometry.translate(sign * bladeLength * .04, 0, 0);
      }
      addPart(group, new THREE.CylinderGeometry(diameter * .025, diameter * .045, y * 2.7, 20), light, [0, y * 1.3, 0]);
      break;
    }
    case "landing-gear": {
      addPart(group, new THREE.CapsuleGeometry(Math.max(radius, z * .32), Math.max(.02, x - radius * 2), 8, 24), dark, [0, -y * .2, 0], [0, 0, Math.PI / 2]);
      for (const px of [-x * .28, x * .28]) addPart(group, new THREE.CylinderGeometry(radius * .55, radius * .55, y * 3.2, 16), main, [px, y * 1.15, 0], [0, 0, px < 0 ? -.28 : .28]);
      break;
    }
    case "battery": {
      addPart(group, new THREE.BoxGeometry(x, y, z), main);
      addPart(group, new THREE.BoxGeometry(x * .12, y * 1.05, z * 1.04), dark, [-x * .22, 0, 0]);
      addPart(group, new THREE.BoxGeometry(x * .12, y * 1.05, z * 1.04), dark, [x * .22, 0, 0]);
      addPart(group, new THREE.CylinderGeometry(y * .08, y * .08, x * .18, 12), light, [x * .38, y * .55, z * .22], [0, 0, Math.PI / 2]);
      break;
    }
    case "flight-controller": {
      addPart(group, new THREE.BoxGeometry(x, y * .45, z), main);
      addPart(group, new THREE.BoxGeometry(x * .36, y * .34, z * .36), dark, [0, y * .42, 0]);
      for (const px of [-x * .4, x * .4]) for (const pz of [-z * .4, z * .4]) addPart(group, new THREE.CylinderGeometry(y * .12, y * .12, y * 1.5, 12), light, [px, -y * .75, pz]);
      break;
    }
    case "sensor": {
      addPart(group, new THREE.CylinderGeometry(radius, radius * 1.06, length * .65, 24), main);
      addPart(group, new THREE.SphereGeometry(radius * .72, 24, 14, 0, Math.PI * 2, 0, Math.PI / 2), light, [0, length * .34, 0]);
      break;
    }
    case "camera-gimbal": {
      addPart(group, new THREE.TorusGeometry(radius * .92, radius * .11, 10, 32), dark, [0, 0, 0], [0, 0, Math.PI / 2]);
      addPart(group, new THREE.TorusGeometry(radius * .7, radius * .09, 10, 32), main, [0, 0, 0], [Math.PI / 2, 0, 0]);
      addPart(group, new THREE.BoxGeometry(radius * 1.05, radius * .72, radius * .86), carbon, [0, -radius * .05, 0]);
      addPart(group, new THREE.CylinderGeometry(radius * .28, radius * .34, radius * .32, 24), light, [radius * .62, -radius * .05, 0], [0, 0, Math.PI / 2]);
      break;
    }
    case "payload": {
      addPart(group, new THREE.BoxGeometry(x, y, z), main);
      addPart(group, new THREE.BoxGeometry(x * .72, y * .08, z * 1.05), dark, [0, y * .53, 0]);
      for (const px of [-x * .38, x * .38]) addPart(group, new THREE.CylinderGeometry(z * .06, z * .06, y * .45, 12), light, [px, y * .72, 0]);
      break;
    }
    default:
      addPart(group, primitiveGeometry(component), main);
  }
  group.userData.componentId = component.id;
  group.traverse((object) => { object.userData.componentId = component.id; });
  return group;
}

function FlatFallback({ draft }: { draft: VehicleModelDraft }) {
  const geometry = useMemo(() => buildVehiclePreviewGeometry(draft), [draft]);
  return (
    <svg viewBox="0 0 480 320" aria-hidden="true">
      <defs>
        <linearGradient id="vehicleStudioFallbackGradient" x1="0" x2="1">
          <stop offset="0" stopColor="var(--dd-brand-start)" />
          <stop offset="0.52" stopColor="var(--dd-brand-middle)" />
          <stop offset="1" stopColor="var(--dd-brand-end)" />
        </linearGradient>
      </defs>
      {geometry.components.filter((component) => component.visible).map((component) => {
        const x = 240 + component.position.x * 64;
        const y = 154 + component.position.z * 54 - component.position.y * 22;
        const width = Math.max(8, component.size.x * 48);
        const height = Math.max(5, component.size.z * 30);
        return <ellipse key={component.id} cx={x} cy={y} rx={width / 2} ry={height / 2} fill={component.color} opacity={component.opacity} />;
      })}
      <path d="M42 272H438M240 44V286" className="vehicle-preview-path" opacity=".18" />
      <rect x="174" y="282" width="132" height="5" rx="2.5" fill="url(#vehicleStudioFallbackGradient)" />
    </svg>
  );
}

export function VehicleModelPreview3D({
  draft,
  copy,
  selectedComponentId = null,
  onSelectComponent,
  wireframe = false,
  exploded = false,
  showGrid = true,
  manipulator = "select",
  viewPreset = "isometric",
  transformSpace = "local",
  snapEnabled = true,
  translationSnapM = .01,
  showEngineeringOverlay = true,
  isolatedComponentId = null,
  frameMode = "assembly",
  onTransformComponent,
}: VehicleModelPreview3DProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const geometry = useMemo(() => buildVehiclePreviewGeometry(draft), [draft]);
  const diagnostics = useMemo(() => calculateVehicleDiagnostics(draft), [draft]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setWebglUnavailable(true);
      return undefined;
    }
    setWebglUnavailable(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-hidden", "true");
    host.replaceChildren(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 100);
    const model = new THREE.Group();
    const selectable: THREE.Object3D[] = [];
    const componentObjects = new Map<string, THREE.Group>();
    scene.add(model);

    for (const component of geometry.components) {
      if (!component.visible || (isolatedComponentId && component.id !== isolatedComponentId)) continue;
      const mesh = buildEngineeringComponent(component, wireframe);
      const expansion = exploded ? 1.3 : 1;
      mesh.position.set(component.position.x * expansion, component.position.y * expansion, component.position.z * expansion);
      mesh.rotation.set(component.rotationRad.x, component.rotationRad.y, component.rotationRad.z);
      mesh.scale.set(component.scale.x, component.scale.y, component.scale.z);
      mesh.userData.componentId = component.id;
      mesh.traverse((object) => { object.userData.componentId = component.id; });
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      model.add(mesh);
      selectable.push(mesh);
      componentObjects.set(component.id, mesh);

      if (component.id === selectedComponentId && !wireframe) {
        const bounds = new THREE.BoxHelper(mesh, 0xffffff);
        (bounds.material as THREE.LineBasicMaterial).transparent = true;
        (bounds.material as THREE.LineBasicMaterial).opacity = .88;
        model.add(bounds);
      }
    }

    if (showEngineeringOverlay) {
      const overlay = new THREE.Group();
      overlay.name = "engineering-overlays";
      for (const component of geometry.components.filter((candidate) => candidate.visible && candidate.kind === "propeller")) {
        if (isolatedComponentId && component.id !== isolatedComponentId) continue;
        const radius = Math.max(component.size.x * component.scale.x, component.size.z * component.scale.z, component.radius * 2) / 2;
        const disk = new THREE.Mesh(new THREE.RingGeometry(radius * .94, radius, 64), new THREE.MeshBasicMaterial({ color: 0xe548b7, transparent: true, opacity: .18, side: THREE.DoubleSide, depthWrite: false }));
        disk.position.set(component.position.x, component.position.y, component.position.z);
        disk.rotation.x = -Math.PI / 2;
        overlay.add(disk);
      }
      const cgPosition = new THREE.Vector3(
        diagnostics.centerOfMassM.x * geometry.scale,
        diagnostics.centerOfMassM.y * geometry.scale,
        diagnostics.centerOfMassM.z * geometry.scale,
      );
      const thrustPosition = new THREE.Vector3(
        diagnostics.centerOfThrustM.x * geometry.scale,
        diagnostics.centerOfThrustM.y * geometry.scale,
        diagnostics.centerOfThrustM.z * geometry.scale,
      );
      const cg = new THREE.Mesh(
        new THREE.SphereGeometry(.055, 20, 12),
        new THREE.MeshBasicMaterial({ color: 0xffca4f, depthTest: false }),
      );
      cg.position.copy(cgPosition); cg.renderOrder = 5; cg.userData.engineeringOverlay = true; overlay.add(cg);
      const thrust = new THREE.Mesh(
        new THREE.TorusGeometry(.07, .014, 12, 32),
        new THREE.MeshBasicMaterial({ color: 0x45e0c5, depthTest: false }),
      );
      thrust.position.copy(thrustPosition); thrust.rotation.x = Math.PI / 2; thrust.renderOrder = 5; thrust.userData.engineeringOverlay = true; overlay.add(thrust);
      if (cgPosition.distanceTo(thrustPosition) > .006) {
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([cgPosition, thrustPosition]),
          new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: .045, gapSize: .025, transparent: true, opacity: .8, depthTest: false }),
        );
        line.computeLineDistances(); line.renderOrder = 4; overlay.add(line);
      }
      scene.add(overlay);
    }

    const primary = new THREE.Color(cssColor("--dd-brand-start", "#ff5574"));
    const secondary = new THREE.Color(cssColor("--dd-brand-middle", "#6a4cff"));
    const tertiary = new THREE.Color(cssColor("--dd-brand-end", "#e657d1"));
    const grid = new THREE.GridHelper(5.4, 24, secondary, tertiary);
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    for (const material of gridMaterials) { material.transparent = true; material.opacity = .16; }
    grid.position.y = -.62;
    grid.visible = showGrid;
    scene.add(grid);
    const axes = new THREE.AxesHelper(.72);
    axes.position.set(-2.12, -.61, 1.85);
    scene.add(axes);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x221733, 1.85));
    const key = new THREE.DirectionalLight(0xffffff, 3.4);
    key.position.set(-3.2, 5.4, 4.2); key.castShadow = true; scene.add(key);
    const rim = new THREE.PointLight(primary, 9, 12); rim.position.set(-2.8, 2.8, -2.4); scene.add(rim);
    const fill = new THREE.PointLight(tertiary, 8, 12); fill.position.set(3.2, 1.6, 2.8); scene.add(fill);

    const presetAngles = {
      isometric: { yaw: -.72, pitch: .48 },
      top: { yaw: 0, pitch: 1.25 },
      front: { yaw: 0, pitch: .08 },
      side: { yaw: Math.PI / 2, pitch: .08 },
    } as const;
    const selectedObject = selectedComponentId ? componentObjects.get(selectedComponentId) : undefined;
    const framedObject = frameMode === "selection" && selectedObject ? selectedObject : model;
    const framedBounds = new THREE.Box3().setFromObject(framedObject);
    const target = framedBounds.isEmpty() ? new THREE.Vector3() : framedBounds.getCenter(new THREE.Vector3());
    const framedSize = framedBounds.isEmpty() ? new THREE.Vector3(2.8, 1, 2.8) : framedBounds.getSize(new THREE.Vector3());
    const homeDistance = Math.max(frameMode === "selection" ? 2.35 : 3.7, Math.max(framedSize.x, framedSize.y, framedSize.z) * (frameMode === "selection" ? 3.15 : 1.72));
    let yaw: number = presetAngles[viewPreset].yaw;
    let pitch: number = presetAngles[viewPreset].pitch;
    let distance = homeDistance;
    let pointerId: number | null = null;
    let pointerX = 0;
    let pointerY = 0;
    let pointerTravel = 0;
    let transformDragging = false;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const render = () => {
      pitch = Math.max(-.15, Math.min(1.25, pitch));
      distance = Math.max(.45, Math.min(12, distance));
      camera.position.set(
        target.x + Math.sin(yaw) * Math.cos(pitch) * distance,
        target.y + Math.sin(pitch) * distance,
        target.z + Math.cos(yaw) * Math.cos(pitch) * distance,
      );
      camera.lookAt(target);
      renderer.render(scene, camera);
    };

    const transformControl = selectedObject && manipulator !== "select"
      ? new TransformControls(camera, renderer.domElement)
      : null;
    const transformHelper = transformControl?.getHelper();
    const onTransformStart = () => { transformDragging = true; };
    const onTransformChange = () => { render(); };
    const onTransformEnd = () => {
      transformDragging = false;
      if (!selectedObject || !selectedComponentId || !onTransformComponent) return;
      const expansion = exploded ? 1.3 : 1;
      onTransformComponent(selectedComponentId, {
        positionM: previewPositionToModel(selectedObject.position, expansion, geometry.scale),
        rotationDeg: {
          x: THREE.MathUtils.radToDeg(selectedObject.rotation.x),
          y: THREE.MathUtils.radToDeg(selectedObject.rotation.y),
          z: THREE.MathUtils.radToDeg(selectedObject.rotation.z),
        },
        scale: { x: selectedObject.scale.x, y: selectedObject.scale.y, z: selectedObject.scale.z },
      });
    };
    if (transformControl && transformHelper && selectedObject) {
      const transformMode: "translate" | "rotate" | "scale" = manipulator === "rotate" ? "rotate" : manipulator === "scale" ? "scale" : "translate";
      transformControl.setMode(transformMode);
      transformControl.setSpace(transformSpace);
      transformControl.setSize(.72);
      transformControl.translationSnap = snapEnabled ? Math.max(.0001, translationSnapM * geometry.scale) : null;
      transformControl.rotationSnap = snapEnabled ? THREE.MathUtils.degToRad(5) : null;
      transformControl.scaleSnap = snapEnabled ? .05 : null;
      transformControl.attach(selectedObject);
      transformControl.addEventListener("mouseDown", onTransformStart);
      transformControl.addEventListener("objectChange", onTransformChange);
      transformControl.addEventListener("mouseUp", onTransformEnd);
      scene.add(transformHelper);
    }
    const resize = () => {
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height; camera.updateProjectionMatrix(); render();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (transformDragging) return;
      pointerId = event.pointerId; pointerX = event.clientX; pointerY = event.clientY; pointerTravel = 0;
      host.setPointerCapture?.(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (transformDragging) return;
      if (pointerId !== event.pointerId) return;
      const dx = event.clientX - pointerX; const dy = event.clientY - pointerY;
      pointerTravel += Math.abs(dx) + Math.abs(dy); yaw -= dx * .012; pitch += dy * .009;
      pointerX = event.clientX; pointerY = event.clientY; render();
    };
    const onPointerUp = (event: PointerEvent) => {
      if (transformDragging) return;
      if (pointerId !== event.pointerId) return;
      pointerId = null;
      if (pointerTravel > 6 || !onSelectComponent) return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(selectable, true)[0];
      onSelectComponent(hit ? String(hit.object.userData.componentId) : null);
    };
    const onWheel = (event: WheelEvent) => { event.preventDefault(); distance += Math.sign(event.deltaY) * .32; render(); };
    const onKeyDown = (event: KeyboardEvent) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "=", "-", "_", "Home"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") yaw -= .16;
      if (event.key === "ArrowRight") yaw += .16;
      if (event.key === "ArrowUp") pitch += .12;
      if (event.key === "ArrowDown") pitch -= .12;
      if (event.key === "+" || event.key === "=") distance -= .32;
      if (event.key === "-" || event.key === "_") distance += .32;
      if (event.key === "Home") { yaw = presetAngles[viewPreset].yaw; pitch = presetAngles[viewPreset].pitch; distance = homeDistance; }
      render();
    };
    host.addEventListener("pointerdown", onPointerDown);
    host.addEventListener("pointermove", onPointerMove);
    host.addEventListener("pointerup", onPointerUp);
    host.addEventListener("pointercancel", onPointerUp);
    host.addEventListener("wheel", onWheel, { passive: false });
    host.addEventListener("keydown", onKeyDown);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(host); resize();

    return () => {
      observer?.disconnect();
      host.removeEventListener("pointerdown", onPointerDown); host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerup", onPointerUp); host.removeEventListener("pointercancel", onPointerUp);
      host.removeEventListener("wheel", onWheel); host.removeEventListener("keydown", onKeyDown);
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          (Array.isArray(object.material) ? object.material : [object.material]).forEach((material) => material.dispose());
        }
        if (object instanceof THREE.LineSegments || object instanceof THREE.Line) {
          object.geometry.dispose();
          (Array.isArray(object.material) ? object.material : [object.material]).forEach((material) => material.dispose());
        }
      });
      grid.geometry.dispose(); gridMaterials.forEach((material) => material.dispose()); axes.geometry.dispose();
      if (transformControl) {
        transformControl.removeEventListener("mouseDown", onTransformStart);
        transformControl.removeEventListener("objectChange", onTransformChange);
        transformControl.removeEventListener("mouseUp", onTransformEnd);
        transformControl.detach();
        transformControl.dispose();
      }
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    };
  }, [diagnostics, exploded, frameMode, geometry, isolatedComponentId, manipulator, onSelectComponent, onTransformComponent, selectedComponentId, showEngineeringOverlay, showGrid, snapEnabled, transformSpace, translationSnapM, viewPreset, wireframe]);

  return (
    <div className="vehicle-model-preview vehicle-model-preview-pro" data-testid="vehicle-model-preview">
      <div
        ref={hostRef}
        className="vehicle-model-preview-canvas"
        role={webglUnavailable ? "img" : "application"}
        tabIndex={webglUnavailable ? -1 : 0}
        aria-label={copy.ariaLabel}
        aria-describedby={hintId}
        title={copy.interaction}
      >
        {webglUnavailable ? <FlatFallback draft={draft} /> : null}
      </div>
      {showEngineeringOverlay ? <div className="vehicle-engineering-overlay-key" aria-hidden="true"><span className="is-cg" />CG <span className="is-thrust" />Thrust center <span className="is-rotor" />Rotor disk</div> : null}
      <div className="vehicle-model-preview-meta">
        <span>{diagnostics.componentCount} parts · {draft.propulsion.motorCount} {copy.motors}</span>
        <span id={hintId} className="vehicle-model-preview-hint">{webglUnavailable ? copy.unavailable : copy.interaction}</span>
        <strong>{copy.ratio} {diagnostics.thrustToWeight.toFixed(2)}×</strong>
      </div>
    </div>
  );
}
