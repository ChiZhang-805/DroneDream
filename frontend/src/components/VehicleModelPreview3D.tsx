import { useEffect, useId, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { VehicleModelDraft } from "../features/vehicleStudio/model";
import {
  buildVehiclePreviewGeometry,
  type VehiclePreviewGeometry,
} from "../features/vehicleStudio/preview";

interface PreviewCopy {
  ariaLabel: string;
  unavailable: string;
  interaction: string;
  motors: string;
  ratio: string;
}

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function addArm(
  group: THREE.Group,
  rotor: VehiclePreviewGeometry["rotors"][number],
  material: THREE.Material,
) {
  const length = Math.hypot(rotor.x, rotor.z);
  const arm = new THREE.Mesh(new THREE.BoxGeometry(length, 0.045, 0.045), material);
  arm.position.set(rotor.x / 2, 0, rotor.z / 2);
  arm.rotation.y = -Math.atan2(rotor.z, rotor.x);
  group.add(arm);
}

function FlatFallback({ draft }: { draft: VehicleModelDraft }) {
  const geometry = useMemo(() => buildVehiclePreviewGeometry(draft), [draft]);
  return (
    <svg viewBox="0 0 320 240" aria-hidden="true">
      <defs>
        <linearGradient id="vehicleStudioFallbackGradient" x1="0" x2="1">
          <stop offset="0" stopColor="var(--dd-brand-start)" />
          <stop offset="0.52" stopColor="var(--dd-brand-middle)" />
          <stop offset="1" stopColor="var(--dd-brand-end)" />
        </linearGradient>
      </defs>
      {geometry.rotors.map((rotor, index) => {
        const x = 160 + rotor.x * 34;
        const y = 112 + rotor.z * 30;
        const radius = Math.max(10, rotor.radius * 28);
        return (
          <g key={index}>
            <line x1="160" y1="112" x2={x} y2={y} className="vehicle-preview-arm" />
            <ellipse cx={x} cy={y} rx={radius} ry={Math.max(4, radius * 0.28)} className="vehicle-preview-rotor" />
            <circle cx={x} cy={y} r="7" className="vehicle-preview-motor" />
          </g>
        );
      })}
      <rect x="122" y="84" width="76" height="56" rx="18" fill="url(#vehicleStudioFallbackGradient)" />
      <path d="M137 111h46M160 92v39" className="vehicle-preview-path" />
    </svg>
  );
}

export function VehicleModelPreview3D({
  draft,
  copy,
}: {
  draft: VehicleModelDraft;
  copy: PreviewCopy;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const geometry = useMemo(() => buildVehiclePreviewGeometry(draft), [draft]);
  const ratio = draft.propulsion.motorCount * draft.propulsion.maximumThrustPerMotorN
    / Math.max(0.001, draft.body.massKg * 9.80665);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebglUnavailable(true);
      return undefined;
    }
    setWebglUnavailable(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-hidden", "true");
    host.replaceChildren(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 100);
    const primary = new THREE.Color(cssColor("--dd-brand-start", "#ff5574"));
    const secondary = new THREE.Color(cssColor("--dd-brand-middle", "#6a4cff"));
    const tertiary = new THREE.Color(cssColor("--dd-brand-end", "#e657d1"));
    const model = new THREE.Group();
    scene.add(model);

    const bodyMaterial = new THREE.MeshStandardMaterial({
      color: secondary,
      emissive: secondary,
      emissiveIntensity: 0.12,
      metalness: 0.38,
      roughness: 0.28,
    });
    const armMaterial = new THREE.MeshStandardMaterial({ color: tertiary, metalness: 0.32, roughness: 0.34 });
    const motorMaterial = new THREE.MeshStandardMaterial({ color: primary, metalness: 0.55, roughness: 0.24 });
    const propellerMaterial = new THREE.MeshBasicMaterial({
      color: tertiary,
      transparent: true,
      opacity: 0.3,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const bodyMesh = new THREE.Mesh(
      geometry.body.shape === "box"
        ? new THREE.BoxGeometry(geometry.body.x, geometry.body.y, geometry.body.z)
        : new THREE.CylinderGeometry(geometry.body.z / 2, geometry.body.z / 2, geometry.body.y, 40),
      bodyMaterial,
    );
    model.add(bodyMesh);
    for (const rotor of geometry.rotors) {
      addArm(model, rotor, armMaterial);
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.12, 24), motorMaterial);
      motor.position.set(rotor.x, 0.04, rotor.z);
      model.add(motor);
      const propeller = new THREE.Mesh(
        new THREE.CylinderGeometry(rotor.radius, rotor.radius, 0.012, 40),
        propellerMaterial,
      );
      propeller.position.set(rotor.x, 0.12, rotor.z);
      model.add(propeller);
    }

    const grid = new THREE.GridHelper(5.2, 12, secondary, tertiary);
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    for (const material of gridMaterials) {
      material.transparent = true;
      material.opacity = 0.2;
    }
    grid.position.y = -0.42;
    scene.add(grid);
    scene.add(new THREE.HemisphereLight(0xffffff, secondary, 1.65));
    const rim = new THREE.PointLight(primary, 8, 12);
    rim.position.set(-2.4, 2.8, 2.2);
    scene.add(rim);
    const fill = new THREE.PointLight(tertiary, 6, 10);
    fill.position.set(2.5, 1.3, -2.4);
    scene.add(fill);

    let yaw = -0.68;
    let pitch = 0.52;
    let distance = 4.5;
    let pointerId: number | null = null;
    let pointerX = 0;
    let pointerY = 0;
    const render = () => {
      pitch = Math.max(-0.15, Math.min(1.25, pitch));
      distance = Math.max(2.9, Math.min(7.2, distance));
      camera.position.set(
        Math.sin(yaw) * Math.cos(pitch) * distance,
        Math.sin(pitch) * distance,
        Math.cos(yaw) * Math.cos(pitch) * distance,
      );
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);
    };
    const resize = () => {
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      render();
    };
    const onPointerDown = (event: PointerEvent) => {
      pointerId = event.pointerId;
      pointerX = event.clientX;
      pointerY = event.clientY;
      host.setPointerCapture?.(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (pointerId !== event.pointerId) return;
      yaw -= (event.clientX - pointerX) * 0.012;
      pitch += (event.clientY - pointerY) * 0.009;
      pointerX = event.clientX;
      pointerY = event.clientY;
      render();
    };
    const onPointerUp = (event: PointerEvent) => {
      if (pointerId === event.pointerId) pointerId = null;
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      distance += Math.sign(event.deltaY) * 0.32;
      render();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const handled = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "=", "-", "_", "Home"];
      if (!handled.includes(event.key)) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") yaw -= 0.16;
      if (event.key === "ArrowRight") yaw += 0.16;
      if (event.key === "ArrowUp") pitch += 0.12;
      if (event.key === "ArrowDown") pitch -= 0.12;
      if (event.key === "+" || event.key === "=") distance -= 0.32;
      if (event.key === "-" || event.key === "_") distance += 0.32;
      if (event.key === "Home") {
        yaw = -0.68;
        pitch = 0.52;
        distance = 4.5;
      }
      render();
    };
    host.addEventListener("pointerdown", onPointerDown);
    host.addEventListener("pointermove", onPointerMove);
    host.addEventListener("pointerup", onPointerUp);
    host.addEventListener("pointercancel", onPointerUp);
    host.addEventListener("wheel", onWheel, { passive: false });
    host.addEventListener("keydown", onKeyDown);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(host);
    resize();

    return () => {
      observer?.disconnect();
      host.removeEventListener("pointerdown", onPointerDown);
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerup", onPointerUp);
      host.removeEventListener("pointercancel", onPointerUp);
      host.removeEventListener("wheel", onWheel);
      host.removeEventListener("keydown", onKeyDown);
      const disposedGeometries = new Set<THREE.BufferGeometry>();
      const disposedMaterials = new Set<THREE.Material>();
      scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        if (!disposedGeometries.has(object.geometry)) {
          disposedGeometries.add(object.geometry);
          object.geometry.dispose();
        }
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) {
          if (disposedMaterials.has(material)) continue;
          disposedMaterials.add(material);
          material.dispose();
        }
      });
      grid.geometry.dispose();
      gridMaterials.forEach((material) => material.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [geometry]);

  return (
    <div className="vehicle-model-preview" data-testid="vehicle-model-preview">
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
      <div className="vehicle-model-preview-meta">
        <span>{draft.propulsion.motorCount} {copy.motors}</span>
        <span id={hintId} className="vehicle-model-preview-hint">{webglUnavailable ? copy.unavailable : copy.interaction}</span>
        <strong>{copy.ratio} {ratio.toFixed(2)}×</strong>
      </div>
    </div>
  );
}
