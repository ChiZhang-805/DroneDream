import { useEffect, useRef, useState, type MutableRefObject } from "react";
import * as THREE from "three";

import { useI18n } from "../i18n/I18nProvider";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import type { EditionTheme3D } from "../theme/editionTheme";
import {
  DRONE_STARFLIGHT_DURATION_SECONDS,
  getDroneStarflightPose,
} from "./droneStarflight";
import {
  AdaptiveDprController,
  DRONE_IDLE_FPS,
  DRONE_INTERACTION_TAIL_MS,
  DRONE_INTERACTIVE_FPS,
  estimateRefreshInterval,
  renderGapBudget,
  shouldRunDroneRenderLoop,
} from "./droneRenderPerformance";

type DroneLaunchSceneProps = {
  active?: boolean;
  progress?: number | null;
  starflightControllerRef?: MutableRefObject<(() => void) | null>;
  telemetryActiveLabel?: string;
  telemetryStandbyLabel?: string;
  telemetrySystemLabel?: string;
  themeOverride?: EditionTheme3D;
  visualOffsetX?: number;
};

export type DroneLaunchSceneLabels = {
  locale: "en" | "zh-CN";
  tagline: string;
  system: string;
  active: string;
  standby: string;
  attitude: string;
  hold: string;
  cruise: string;
};

type MovingCityVehicle = {
  object: THREE.Group;
  axis: "x" | "z";
  direction: 1 | -1;
  offset: number;
  speed: number;
  lane: number;
};

type NightCity = {
  group: THREE.Group;
  movingVehicles: MovingCityVehicle[];
  waterMaterial: THREE.MeshStandardMaterial;
  beaconMaterials: THREE.MeshBasicMaterial[];
};

type DroneLaunchSceneCoreProps = Omit<
  DroneLaunchSceneProps,
  "telemetryActiveLabel" | "telemetryStandbyLabel" | "telemetrySystemLabel"
> & {
  labels: DroneLaunchSceneLabels;
};

function launchTaglineLines(labels: DroneLaunchSceneLabels) {
  if (labels.locale !== "en") return [labels.tagline];

  const words = labels.tagline.trim().split(/\s+/);
  if (words.length < 2) return [labels.tagline];

  const splitAt = Math.floor(words.length / 2);
  return [words.slice(0, splitAt).join(" "), words.slice(splitAt).join(" ")];
}

const CARBON = 0x171827;
const GRAPHITE = 0x30334a;
const METAL = 0x697087;

function rgba(color: number, alpha: number) {
  const value = color.toString(16).padStart(6, "0");
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${red},${green},${blue},${alpha})`;
}

function disposeScene(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    const objectMaterials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of objectMaterials) {
      if (material) materials.add(material);
    }
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

function tubeBetween(
  start: THREE.Vector3,
  end: THREE.Vector3,
  radius: number,
  material: THREE.Material,
) {
  const direction = new THREE.Vector3().subVectors(end, start);
  const tube = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius * 1.04, direction.length(), 14),
    material,
  );
  tube.position.copy(start).add(end).multiplyScalar(0.5);
  tube.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize(),
  );
  tube.castShadow = true;
  return tube;
}

function buildDrone(accentGlowTexture: THREE.Texture | null, theme: EditionTheme3D) {
  const drone = new THREE.Group();
  drone.name = "procedural-quadcopter";

  const carbon = new THREE.MeshPhysicalMaterial({
    color: CARBON,
    roughness: 0.28,
    metalness: 0.72,
    clearcoat: 0.75,
    clearcoatRoughness: 0.18,
  });
  const graphite = new THREE.MeshStandardMaterial({
    color: GRAPHITE,
    roughness: 0.34,
    metalness: 0.7,
  });
  const metal = new THREE.MeshStandardMaterial({
    color: METAL,
    roughness: 0.22,
    metalness: 0.9,
  });
  const glass = new THREE.MeshPhysicalMaterial({
    color: 0x07121c,
    emissive: 0x0b3e56,
    emissiveIntensity: 0.78,
    roughness: 0.05,
    metalness: 0.2,
    transmission: 0.22,
    transparent: true,
    opacity: 0.92,
  });
  const magentaLight = new THREE.MeshBasicMaterial({
    color: theme.tertiary,
    toneMapped: false,
  });
  const cyanLight = new THREE.MeshBasicMaterial({
    color: theme.primary,
    toneMapped: false,
  });
  const cyanHotLight = new THREE.MeshBasicMaterial({
    color: theme.primary,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  const magentaHotLight = new THREE.MeshBasicMaterial({
    color: theme.tertiary,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  const cyanGlow = accentGlowTexture
    ? new THREE.SpriteMaterial({
        map: accentGlowTexture,
        color: theme.primary,
        transparent: true,
        opacity: 0.96,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      })
    : null;
  const magentaGlow = accentGlowTexture
    ? new THREE.SpriteMaterial({
        map: accentGlowTexture,
        color: theme.tertiary,
        transparent: true,
        opacity: 0.94,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      })
    : null;
  const addAccentGlow = (
    position: THREE.Vector3,
    material: THREE.SpriteMaterial | null,
    width: number,
    height = width,
  ) => {
    if (!material) return;
    const glow = new THREE.Sprite(material);
    glow.position.copy(position);
    glow.scale.set(width, height, 1);
    glow.renderOrder = 3;
    drone.add(glow);
  };

  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.48, 0.82, 10, 24), carbon);
  body.rotation.x = Math.PI / 2;
  body.scale.set(1.08, 0.68, 1.28);
  body.castShadow = true;
  drone.add(body);

  const upperShell = new THREE.Mesh(new THREE.SphereGeometry(0.7, 32, 18), graphite);
  upperShell.scale.set(1.02, 0.36, 1.2);
  upperShell.position.y = 0.28;
  upperShell.position.z = -0.05;
  upperShell.castShadow = true;
  drone.add(upperShell);

  const battery = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.25, 0.9), carbon);
  battery.position.set(0, 0.39, -0.15);
  battery.rotation.x = -0.04;
  battery.castShadow = true;
  drone.add(battery);

  const batteryStripe = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.018, 0.16), cyanLight);
  batteryStripe.position.set(0, 0.523, -0.25);
  drone.add(batteryStripe);
  const batteryStripeCore = new THREE.Mesh(
    new THREE.BoxGeometry(0.56, 0.022, 0.048),
    cyanHotLight,
  );
  batteryStripeCore.position.set(0, 0.535, -0.25);
  drone.add(batteryStripeCore);
  addAccentGlow(new THREE.Vector3(0, 0.56, -0.25), cyanGlow, 1.65, 0.56);
  addAccentGlow(new THREE.Vector3(0, 0.565, -0.25), cyanGlow, 0.72, 0.22);

  const cyanAccentLight = new THREE.PointLight(theme.primary, 14, 3.5, 2);
  cyanAccentLight.position.set(-0.62, 0.12, -0.18);
  drone.add(cyanAccentLight);
  const magentaAccentLight = new THREE.PointLight(theme.tertiary, 14, 3.5, 2);
  magentaAccentLight.position.set(0.62, 0.12, 0.18);
  drone.add(magentaAccentLight);

  const motorPositions = [
    new THREE.Vector3(-1.58, 0.04, -1.3),
    new THREE.Vector3(1.58, 0.04, -1.3),
    new THREE.Vector3(-1.58, 0.04, 1.3),
    new THREE.Vector3(1.58, 0.04, 1.3),
  ];
  const rotors: THREE.Group[] = [];

  for (const [index, position] of motorPositions.entries()) {
    const rotorColor = index % 2 === 0 ? theme.primary : theme.tertiary;
    const rotorLightMaterial = index % 2 === 0 ? cyanLight : magentaLight;
    const rotorHotLightMaterial = index % 2 === 0 ? cyanHotLight : magentaHotLight;
    const rotorGlowMaterial = index % 2 === 0 ? cyanGlow : magentaGlow;
    const shoulder = position.clone().multiplyScalar(0.34);
    shoulder.y = 0.02;
    const elbow = position.clone().multiplyScalar(0.72);
    elbow.y = position.z > 0 ? 0.02 : 0.1;
    drone.add(tubeBetween(shoulder, elbow, 0.095, carbon));
    drone.add(tubeBetween(elbow, position, 0.082, graphite));

    const collar = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.19, 0.18, 24), metal);
    collar.position.copy(position);
    collar.castShadow = true;
    drone.add(collar);

    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.18, 0.26, 24), carbon);
    motor.position.copy(position);
    motor.position.y += 0.17;
    motor.castShadow = true;
    drone.add(motor);

    const rotor = new THREE.Group();
    rotor.position.copy(position);
    rotor.position.y += 0.33;
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.08, 18), metal);
    hub.position.y = 0.03;
    rotor.add(hub);

    const bladeMaterial = new THREE.MeshPhysicalMaterial({
      color: index < 2 ? 0x596177 : 0x3f465b,
      roughness: 0.22,
      metalness: 0.42,
      transparent: true,
      opacity: 0.82,
      side: THREE.DoubleSide,
    });
    const bladeGeometry = new THREE.BoxGeometry(1.42, 0.026, 0.105, 8, 1, 2);
    const firstBlade = new THREE.Mesh(bladeGeometry, bladeMaterial);
    firstBlade.position.x = 0.02;
    firstBlade.rotation.y = 0.08;
    firstBlade.castShadow = true;
    rotor.add(firstBlade);
    const secondBlade = firstBlade.clone();
    secondBlade.rotation.y = Math.PI / 2 + 0.08;
    rotor.add(secondBlade);

    const rotorLightGeometry = new THREE.BoxGeometry(0.98, 0.016, 0.056);
    const rotorLightBar = new THREE.Mesh(rotorLightGeometry, rotorLightMaterial);
    rotorLightBar.position.y = 0.061;
    rotorLightBar.rotation.y = 0.08;
    rotor.add(rotorLightBar);
    const secondRotorLightBar = rotorLightBar.clone();
    secondRotorLightBar.rotation.y = Math.PI / 2 + 0.08;
    rotor.add(secondRotorLightBar);

    const rotorCoreGeometry = new THREE.BoxGeometry(0.58, 0.019, 0.018);
    const rotorCoreBar = new THREE.Mesh(rotorCoreGeometry, rotorHotLightMaterial);
    rotorCoreBar.position.y = 0.071;
    rotorCoreBar.rotation.y = 0.08;
    rotor.add(rotorCoreBar);
    const secondRotorCoreBar = rotorCoreBar.clone();
    secondRotorCoreBar.rotation.y = Math.PI / 2 + 0.08;
    rotor.add(secondRotorCoreBar);

    const wash = new THREE.Mesh(
      new THREE.RingGeometry(0.28, 0.76, 48),
      new THREE.MeshBasicMaterial({
        color: rotorColor,
        transparent: true,
        opacity: 0.19,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    );
    wash.rotation.x = -Math.PI / 2;
    wash.position.y = -0.025;
    rotor.add(wash);
    rotors.push(rotor);
    drone.add(rotor);

    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.078, 16, 10),
      rotorLightMaterial,
    );
    led.position.copy(position);
    led.position.y -= 0.11;
    led.position.z += position.z > 0 ? 0.11 : -0.11;
    drone.add(led);
    const ledCore = new THREE.Mesh(
      new THREE.SphereGeometry(0.035, 14, 8),
      rotorHotLightMaterial,
    );
    ledCore.position.copy(led.position);
    ledCore.position.z += position.z > 0 ? 0.055 : -0.055;
    drone.add(ledCore);
    addAccentGlow(
      led.position,
      rotorGlowMaterial,
      0.78,
    );
    addAccentGlow(ledCore.position, rotorGlowMaterial, 0.32);

    const rotorPointLight = new THREE.PointLight(rotorColor, 5.2, 2.2, 2);
    rotorPointLight.position.copy(position);
    rotorPointLight.position.y += 0.22;
    drone.add(rotorPointLight);
  }

  const gimbalYaw = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.16, 24), metal);
  gimbalYaw.position.set(0, -0.47, 0.49);
  drone.add(gimbalYaw);
  const gimbalArm = tubeBetween(
    new THREE.Vector3(0, -0.48, 0.49),
    new THREE.Vector3(0, -0.69, 0.7),
    0.045,
    metal,
  );
  drone.add(gimbalArm);
  const cameraBody = new THREE.Mesh(new THREE.BoxGeometry(0.43, 0.35, 0.38), graphite);
  cameraBody.position.set(0, -0.71, 0.78);
  cameraBody.rotation.x = -0.13;
  cameraBody.castShadow = true;
  drone.add(cameraBody);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.125, 0.145, 0.09, 28), glass);
  lens.rotation.x = Math.PI / 2;
  lens.position.set(0, -0.73, 1.005);
  drone.add(lens);
  const lensCore = new THREE.Mesh(new THREE.CircleGeometry(0.07, 24), cyanLight);
  lensCore.position.set(0, -0.73, 1.054);
  drone.add(lensCore);
  const lensHotCore = new THREE.Mesh(new THREE.CircleGeometry(0.032, 24), cyanHotLight);
  lensHotCore.position.set(0, -0.73, 1.059);
  drone.add(lensHotCore);
  addAccentGlow(new THREE.Vector3(0, -0.73, 1.075), cyanGlow, 0.84);
  addAccentGlow(new THREE.Vector3(0, -0.73, 1.08), cyanGlow, 0.32);

  for (const x of [-0.52, 0.52]) {
    const hip = new THREE.Vector3(x, -0.3, -0.22);
    const footFront = new THREE.Vector3(x * 1.28, -0.94, 0.68);
    const footRear = new THREE.Vector3(x * 1.28, -0.94, -0.7);
    drone.add(tubeBetween(hip, footFront, 0.043, metal));
    drone.add(tubeBetween(hip, footRear, 0.043, metal));
    drone.add(tubeBetween(footRear, footFront, 0.038, graphite));
  }

  const sideAccentGeometry = new THREE.BoxGeometry(0.035, 0.12, 0.74);
  for (const x of [-0.585, 0.585]) {
    const isCyan = x < 0;
    const accent = new THREE.Mesh(sideAccentGeometry, isCyan ? cyanLight : magentaLight);
    accent.position.set(x, 0.04, 0.02);
    drone.add(accent);
    const accentCore = new THREE.Mesh(
      new THREE.BoxGeometry(0.041, 0.045, 0.46),
      isCyan ? cyanHotLight : magentaHotLight,
    );
    accentCore.position.set(x + (isCyan ? -0.004 : 0.004), 0.04, 0.02);
    drone.add(accentCore);
    addAccentGlow(
      new THREE.Vector3(x + (isCyan ? -0.045 : 0.045), 0.04, 0.04),
      isCyan ? cyanGlow : magentaGlow,
      0.68,
      1.15,
    );
    addAccentGlow(
      new THREE.Vector3(x + (isCyan ? -0.05 : 0.05), 0.04, 0.04),
      isCyan ? cyanGlow : magentaGlow,
      0.28,
      0.6,
    );
  }

  return { drone, rotors };
}

function createSeededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function makeRadialTexture(stops: Array<[number, string]>, size = 128) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (!context) return null;
  const centre = size / 2;
  const gradient = context.createRadialGradient(centre, centre, 0, centre, centre, centre);
  stops.forEach(([offset, color]) => gradient.addColorStop(offset, color));
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function makeBuildingFacadeTexture(
  windowColor: string,
  random: () => number,
) {
  const canvas = document.createElement("canvas");
  canvas.width = 192;
  canvas.height = 384;
  const context = canvas.getContext("2d");
  if (!context) return null;

  const facade = context.createLinearGradient(0, 0, canvas.width, 0);
  facade.addColorStop(0, "#090d1b");
  facade.addColorStop(0.46, "#171c31");
  facade.addColorStop(1, "#080c19");
  context.fillStyle = facade;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.fillStyle = "rgba(210,225,255,0.08)";
  for (let x = 0; x <= canvas.width; x += 24) context.fillRect(x, 0, 2, canvas.height);
  for (let y = 7; y <= canvas.height; y += 24) context.fillRect(0, y, canvas.width, 2);

  for (let y = 12; y < canvas.height - 10; y += 24) {
    for (let x = 6; x < canvas.width - 8; x += 24) {
      const lit = random() > 0.34;
      context.fillStyle = lit
        ? windowColor
        : random() > 0.5
          ? "rgba(36,46,72,0.72)"
          : "rgba(12,18,34,0.84)";
      context.fillRect(x, y, 13, 10);
      if (lit) {
        context.fillStyle = "rgba(255,255,255,0.34)";
        context.fillRect(x + 1, y + 1, 2, 8);
      }
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

function buildStarLayer({
  count,
  size,
  opacity,
  texture,
  random,
  accent = false,
}: {
  count: number;
  size: number;
  opacity: number;
  texture: THREE.Texture | null;
  random: () => number;
  accent?: boolean;
}) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const palette = [
    new THREE.Color(0xffffff),
    new THREE.Color(0xffffff),
    new THREE.Color(0xffffff),
    new THREE.Color(0xffffff),
    new THREE.Color(0xfbfdfd),
    new THREE.Color(0xf7f9ff),
  ];
  for (let index = 0; index < count; index += 1) {
    const spread = accent ? 17 : 24;
    positions[index * 3] = (random() - 0.5) * spread;
    positions[index * 3 + 1] = (random() - 0.38) * (accent ? 10 : 14);
    positions[index * 3 + 2] = -3.5 - random() * (accent ? 10 : 19);
    const color = palette[Math.floor(random() * palette.length)]
      .clone()
      .multiplyScalar(1 + random() * 0.32);
    colors[index * 3] = color.r;
    colors[index * 3 + 1] = color.g;
    colors[index * 3 + 2] = color.b;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size,
    map: texture ?? undefined,
    alphaTest: texture ? 0.025 : 0,
    transparent: true,
    opacity,
    vertexColors: true,
    depthWrite: false,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    fog: false,
    toneMapped: false,
  });
  return { points: new THREE.Points(geometry, material), material };
}

function buildGalacticDust(
  texture: THREE.Texture | null,
  random: () => number,
  count: number,
  theme: EditionTheme3D,
) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const cyan = new THREE.Color(theme.primary);
  const violet = new THREE.Color(theme.secondary);
  const magenta = new THREE.Color(theme.tertiary);
  for (let index = 0; index < count; index += 1) {
    const distance = (random() - 0.5) * 18;
    positions[index * 3] = distance;
    positions[index * 3 + 1] = distance * 0.18 + (random() - 0.5) * 1.35;
    positions[index * 3 + 2] = -6 - random() * 10;
    const mix = random();
    const color = mix < 0.45
      ? cyan.clone().lerp(violet, mix / 0.45)
      : violet.clone().lerp(magenta, (mix - 0.45) / 0.55);
    color.multiplyScalar(0.58 + random() * 0.46);
    colors[index * 3] = color.r;
    colors[index * 3 + 1] = color.g;
    colors[index * 3 + 2] = color.b;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size: 0.085,
    map: texture ?? undefined,
    alphaTest: texture ? 0.015 : 0,
    transparent: true,
    opacity: 0.34,
    vertexColors: true,
    depthWrite: false,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    fog: false,
    toneMapped: false,
  });
  const dust = new THREE.Points(geometry, material);
  dust.rotation.z = -0.08;
  return { dust, material };
}

function buildNightCity(
  random: () => number,
  theme: EditionTheme3D,
): NightCity {
  const group = new THREE.Group();
  group.name = "night-city";
  group.position.y = -1.25;

  const asphalt = new THREE.MeshStandardMaterial({
    color: 0x080b17,
    roughness: 0.94,
    metalness: 0.08,
  });
  const road = new THREE.MeshStandardMaterial({
    color: 0x101526,
    roughness: 0.82,
    metalness: 0.18,
  });
  const roadLine = new THREE.MeshBasicMaterial({
    color: 0xffd976,
    transparent: true,
    opacity: 0.72,
    toneMapped: false,
  });
  const pavement = new THREE.MeshStandardMaterial({
    color: 0x202438,
    roughness: 0.82,
    metalness: 0.18,
  });
  const waterMaterial = new THREE.MeshStandardMaterial({
    color: 0x071d36,
    emissive: theme.primary,
    emissiveIntensity: 0.12,
    roughness: 0.18,
    metalness: 0.38,
    transparent: true,
    opacity: 0.92,
  });
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(34, 34), asphalt);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  group.add(ground);

  const addFlatBox = (
    width: number,
    depth: number,
    x: number,
    z: number,
    material: THREE.Material,
    y = 0.018,
  ) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, 0.035, depth), material);
    mesh.position.set(x, y, z);
    mesh.receiveShadow = true;
    group.add(mesh);
    return mesh;
  };

  // Road surfaces and paint must remain coplanar. Thin boxes made the lane
  // paint behave like a curb, so wheels appeared to intersect the markings.
  const addRoadSurface = (
    width: number,
    depth: number,
    x: number,
    z: number,
    material: THREE.Material,
    y = 0.006,
  ) => {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(x, y, z);
    mesh.receiveShadow = true;
    group.add(mesh);
    return mesh;
  };

  addRoadSurface(31, 1.3, 0, 1.6, road);
  addRoadSurface(1.35, 31, 0, 0, road);
  addRoadSurface(31, 1.05, 0, -6.2, road);

  const sidewalk = new THREE.MeshStandardMaterial({
    color: 0x2b2e3d,
    roughness: 0.88,
    metalness: 0.08,
  });
  const addHorizontalCurb = (z: number) => {
    for (const x of [-8.24, 8.24]) addFlatBox(14.52, 0.23, x, z, sidewalk, 0.055);
  };
  for (const z of [0.8, 2.4, -6.86, -5.55]) addHorizontalCurb(z);
  const verticalCurbSegments: Array<[number, number]> = [
    [-11.18, 8.64],
    [-2.38, 5.98],
    [8.98, 13.04],
  ];
  for (const x of [-0.82, 0.82]) {
    for (const [z, depth] of verticalCurbSegments) {
      addFlatBox(0.23, depth, x, z, sidewalk, 0.055);
    }
  }

  for (let x = -14; x <= 14; x += 1.7) {
    // A centre line terminates before an intersection; it never crosses the
    // pedestrian zone or continues through the junction itself.
    if (Math.abs(x) > 1.42) {
      addRoadSurface(0.76, 0.05, x, 1.6, roadLine, 0.012);
      addRoadSurface(0.76, 0.05, x, -6.2, roadLine, 0.012);
    }
  }
  for (let z = -14; z <= 14; z += 1.7) {
    const insideNorthJunction = Math.abs(z - 1.6) < 1.18;
    const insideSouthJunction = Math.abs(z + 6.2) < 1.05;
    if (!insideNorthJunction && !insideSouthJunction) {
      addRoadSurface(0.05, 0.76, 0, z, roadLine, 0.012);
    }
  }

  const crosswalkMaterial = new THREE.MeshBasicMaterial({
    color: 0xeaf1ff,
    transparent: true,
    opacity: 0.68,
    toneMapped: false,
  });
  for (const junctionZ of [1.6, -6.2]) {
    const horizontalRoadDepth = junctionZ > 0 ? 1.3 : 1.05;
    // Two crossings across the east-west road, one on each side of the
    // junction. The bars run in the walking direction and stop at the curbs.
    for (const crossingX of [-1.12, 1.12]) {
      for (let stripe = -2; stripe <= 2; stripe += 1) {
        addRoadSurface(
          0.12,
          horizontalRoadDepth * 0.76,
          crossingX + stripe * 0.17,
          junctionZ,
          crosswalkMaterial,
          0.014,
        );
      }
    }
    // North and south crossings span the vertical road. Keeping them outside
    // the turning box prevents the unrealistic white grid seen at the centre.
    const crossingOffset = horizontalRoadDepth / 2 + 0.34;
    for (const crossingZ of [junctionZ - crossingOffset, junctionZ + crossingOffset]) {
      for (let stripe = -2; stripe <= 2; stripe += 1) {
        addRoadSurface(
          1.02,
          0.11,
          0,
          crossingZ + stripe * 0.17,
          crosswalkMaterial,
          0.014,
        );
      }
    }
  }

  const river = addFlatBox(3.1, 32, 6.15, 0, waterMaterial, 0.025);
  river.rotation.y = -0.08;
  const riverGlowMaterial = new THREE.MeshBasicMaterial({
    color: theme.primary,
    transparent: true,
    opacity: 0.22,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  for (let z = -13; z <= 13; z += 1.4) {
    const ripple = addFlatBox(1.7 + random() * 0.8, 0.026, 6.15, z, riverGlowMaterial, 0.065);
    ripple.rotation.y = -0.08 + (random() - 0.5) * 0.12;
  }

  const bridgeDeck = addFlatBox(5.4, 1.22, 6.15, 1.6, pavement, 0.16);
  bridgeDeck.castShadow = true;
  const bridgeRail = new THREE.MeshBasicMaterial({
    color: theme.tertiary,
    transparent: true,
    opacity: 0.68,
    toneMapped: false,
  });
  for (const z of [1.05, 2.15]) {
    const rail = new THREE.Mesh(new THREE.BoxGeometry(5.4, 0.12, 0.05), bridgeRail);
    rail.position.set(6.15, 0.34, z);
    group.add(rail);
  }

  const facadeTextures = [
    makeBuildingFacadeTexture(rgba(theme.primary, 0.92), random),
    makeBuildingFacadeTexture(rgba(theme.tertiary, 0.9), random),
    makeBuildingFacadeTexture("rgba(255,218,132,0.92)", random),
  ];
  const buildingMaterials = facadeTextures.map((texture, index) => new THREE.MeshPhysicalMaterial({
    color: index === 0 ? 0x27304a : index === 1 ? 0x302542 : 0x27303b,
    map: texture ?? undefined,
    emissiveMap: texture ?? undefined,
    emissive: index === 0 ? theme.primary : index === 1 ? theme.tertiary : 0xffc866,
    emissiveIntensity: 0.3,
    roughness: 0.54,
    metalness: 0.42,
    clearcoat: 0.18,
  }));
  const buildingEdgeMaterials = [
    new THREE.MeshBasicMaterial({ color: theme.primary, transparent: true, opacity: 0.42, toneMapped: false }),
    new THREE.MeshBasicMaterial({ color: theme.tertiary, transparent: true, opacity: 0.38, toneMapped: false }),
    new THREE.MeshBasicMaterial({ color: 0xffd981, transparent: true, opacity: 0.34, toneMapped: false }),
  ];
  const beaconMaterials: THREE.MeshBasicMaterial[] = [];
  const buildingPositions: Array<[number, number]> = [];
  for (const x of [-12.6, -10.2, -7.8, -5.4, -2.8, 2.4, 4.1, 8.5, 11, 13]) {
    for (const z of [-11.8, -9.1, -3.9, -1.1, 4.5, 7.3, 10.2, 12.6]) {
      // Reserve the full stadium footprint plus a visual buffer. Buildings at
      // x=-5.4 previously sat directly in front of the track from the camera.
      const stadiumZone = x < -5.05 && z > -6.05 && z < 0.2;
      const riverZone = x > 4.45 && x < 7.9;
      const roadZone = Math.abs(z - 1.6) < 1.15 || Math.abs(z + 6.2) < 1.0;
      const launchClearance = Math.hypot(x, z) < 4.45;
      // The camera approaches the launch pad from positive Z. Keep the whole
      // foreground band low and open so no tower can sit between the viewer
      // and the idle drone, including at the widest supported aspect ratios.
      const cameraViewClearance = z > 2.2 && z < 9.1;
      if (stadiumZone || riverZone || roadZone || launchClearance || cameraViewClearance) continue;
      buildingPositions.push([x + (random() - 0.5) * 0.65, z + (random() - 0.5) * 0.55]);
    }
  }

  for (const [index, [x, z]] of buildingPositions.entries()) {
    const width = 0.92 + random() * 1.15;
    const depth = 0.82 + random() * 1.2;
    const height = 0.72 + random() * (Math.abs(x) > 9 ? 1.35 : 2.7);
    const facadeMaterial = buildingMaterials[index % buildingMaterials.length];
    const edgeMaterial = buildingEdgeMaterials[index % buildingEdgeMaterials.length];
    const lot = new THREE.Mesh(
      new THREE.BoxGeometry(width + 0.3, 0.06, depth + 0.3),
      pavement,
    );
    lot.position.set(x, 0.065, z);
    lot.receiveShadow = true;
    group.add(lot);

    const podiumHeight = index % 4 === 0 ? Math.min(0.34, height * 0.24) : 0;
    if (podiumHeight > 0) {
      const podium = new THREE.Mesh(
        new THREE.BoxGeometry(width * 1.12, podiumHeight, depth * 1.12),
        facadeMaterial,
      );
      podium.position.set(x, podiumHeight / 2 + 0.08, z);
      podium.castShadow = true;
      group.add(podium);
    }
    const building = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      facadeMaterial,
    );
    building.position.set(x, height / 2 + podiumHeight, z);
    building.castShadow = true;
    building.receiveShadow = true;
    group.add(building);

    const roof = new THREE.Mesh(
      new THREE.BoxGeometry(width * 0.5, 0.1, depth * 0.46),
      pavement,
    );
    roof.position.set(x, height + podiumHeight + 0.05, z);
    group.add(roof);

    for (const cornerX of [-1, 1]) {
      for (const cornerZ of [-1, 1]) {
        const edge = new THREE.Mesh(
          new THREE.BoxGeometry(0.025, height * 0.96, 0.025),
          edgeMaterial,
        );
        edge.position.set(
          x + cornerX * width * 0.498,
          podiumHeight + height * 0.51,
          z + cornerZ * depth * 0.498,
        );
        group.add(edge);
      }
    }

    if (index % 3 === 1) {
      const crown = new THREE.Mesh(
        new THREE.CylinderGeometry(width * 0.19, width * 0.3, 0.2, 8),
        facadeMaterial,
      );
      crown.position.set(x, height + podiumHeight + 0.16, z);
      crown.castShadow = true;
      group.add(crown);
    }

    if (index % 4 === 2) {
      const antenna = new THREE.Mesh(
        new THREE.CylinderGeometry(0.018, 0.024, 0.52, 8),
        buildingEdgeMaterials[index % buildingEdgeMaterials.length],
      );
      antenna.position.set(x, height + podiumHeight + 0.34, z);
      group.add(antenna);
    }

    if (height > 1.6 && index % 3 === 0) {
      const beaconMaterial = new THREE.MeshBasicMaterial({
        color: index % 2 === 0 ? theme.primary : theme.tertiary,
        transparent: true,
        opacity: 0.88,
        toneMapped: false,
      });
      beaconMaterials.push(beaconMaterial);
      const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 8), beaconMaterial);
      beacon.position.set(x, height + podiumHeight + 0.2, z);
      group.add(beacon);
    }
  }

  const stadium = new THREE.Group();
  stadium.position.set(-8.9, 0.045, -3.1);
  const stadiumBase = new THREE.Mesh(
    new THREE.BoxGeometry(4.35, 0.1, 2.65),
    pavement,
  );
  stadiumBase.position.y = -0.035;
  stadiumBase.receiveShadow = true;
  stadium.add(stadiumBase);
  const field = new THREE.Mesh(
    new THREE.PlaneGeometry(3.55, 1.7),
    new THREE.MeshStandardMaterial({ color: 0x0a392d, roughness: 0.92, metalness: 0.04 }),
  );
  field.rotation.x = -Math.PI / 2;
  stadium.add(field);
  const track = new THREE.Mesh(
    new THREE.RingGeometry(1.18, 1.48, 64),
    new THREE.MeshBasicMaterial({ color: 0xb74365, transparent: true, opacity: 0.86, side: THREE.DoubleSide }),
  );
  track.rotation.x = -Math.PI / 2;
  track.scale.set(1.32, 0.72, 1);
  track.position.y = 0.018;
  stadium.add(track);
  const laneMaterial = new THREE.MeshBasicMaterial({
    color: 0xffecf2,
    transparent: true,
    opacity: 0.62,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  for (const radius of [1.24, 1.34, 1.44]) {
    const lane = new THREE.Mesh(new THREE.RingGeometry(radius, radius + 0.012, 72), laneMaterial);
    lane.rotation.x = -Math.PI / 2;
    lane.scale.set(1.32, 0.72, 1);
    lane.position.y = 0.026;
    stadium.add(lane);
  }
  const centreLine = new THREE.Mesh(
    new THREE.BoxGeometry(0.035, 0.03, 1.36),
    new THREE.MeshBasicMaterial({ color: 0xd9f8e8, transparent: true, opacity: 0.52 }),
  );
  centreLine.position.y = 0.035;
  stadium.add(centreLine);
  const fieldLineMaterial = new THREE.MeshBasicMaterial({
    color: 0xe7fff3,
    transparent: true,
    opacity: 0.72,
    toneMapped: false,
  });
  for (const z of [-0.78, 0.78]) {
    const goalLine = new THREE.Mesh(new THREE.BoxGeometry(2.35, 0.018, 0.025), fieldLineMaterial);
    goalLine.position.set(0, 0.04, z);
    stadium.add(goalLine);
  }
  const standsMaterial = new THREE.MeshStandardMaterial({ color: 0x35334d, roughness: 0.74, metalness: 0.24 });
  for (const x of [-1.95, 1.95]) {
    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.34, 2.1), standsMaterial);
    stand.position.set(x, 0.14, 0);
    stand.rotation.z = x < 0 ? -0.12 : 0.12;
    stadium.add(stand);
  }
  for (const x of [-2.08, 2.08]) {
    for (const z of [-1.2, 1.2]) {
      const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.035, 1.3, 8), pavement);
      mast.position.set(x, 0.62, z);
      stadium.add(mast);
      const floodlight = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.12, 0.08), new THREE.MeshBasicMaterial({ color: 0xeafcff, toneMapped: false }));
      floodlight.position.set(x, 1.24, z);
      floodlight.rotation.y = x < 0 ? -0.2 : 0.2;
      stadium.add(floodlight);
    }
  }
  group.add(stadium);

  const parkMaterial = new THREE.MeshStandardMaterial({ color: 0x102e25, roughness: 0.94 });
  addFlatBox(4.1, 3.1, 9.9, -3.1, parkMaterial, 0.04);
  const treeMaterial = new THREE.MeshStandardMaterial({ color: 0x17634c, roughness: 0.86 });
  for (let index = 0; index < 18; index += 1) {
    const tree = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.52, 8), treeMaterial);
    tree.position.set(8.3 + random() * 3.2, 0.28, -4.25 + random() * 2.3);
    group.add(tree);
  }

  const lampMaterial = new THREE.MeshBasicMaterial({ color: 0xcffaff, toneMapped: false });
  const lampPoleMaterial = new THREE.MeshStandardMaterial({ color: 0x576178, roughness: 0.48, metalness: 0.7 });
  for (let index = 0; index < 22; index += 1) {
    const eastWest = index < 12;
    const lampX = eastWest ? -13 + index * 2.35 : index % 2 === 0 ? -0.82 : 0.82;
    const lampZ = eastWest ? 0.77 : -12 + (index - 12) * 2.5;
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.024, 0.46, 8), lampPoleMaterial);
    pole.position.set(lampX, 0.23, lampZ);
    group.add(pole);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.045, 9, 7), lampMaterial);
    lamp.position.set(lampX, 0.48, lampZ);
    group.add(lamp);
  }

  const movingVehicles: MovingCityVehicle[] = [];
  const vehicleColors = [theme.primary, theme.tertiary, 0xffc55c, 0xe7f5ff];
  for (let index = 0; index < 14; index += 1) {
    const axis: "x" | "z" = index < 9 ? "x" : "z";
    const direction: 1 | -1 = index % 2 === 0 ? 1 : -1;
    const vehicle = new THREE.Group();
    const bodyMaterial = new THREE.MeshPhysicalMaterial({
        color: vehicleColors[index % vehicleColors.length],
        emissive: vehicleColors[index % vehicleColors.length],
        emissiveIntensity: 0.12,
        roughness: 0.28,
        metalness: 0.58,
        clearcoat: 0.72,
        clearcoatRoughness: 0.2,
      });
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.4, 0.12, 0.21),
      bodyMaterial,
    );
    body.position.y = 0.12;
    vehicle.add(body);
    const cabin = new THREE.Mesh(
      new THREE.BoxGeometry(0.2, 0.1, 0.18),
      new THREE.MeshPhysicalMaterial({
        color: 0x18253d,
        roughness: 0.12,
        metalness: 0.45,
        transmission: 0.16,
        transparent: true,
        opacity: 0.88,
      }),
    );
    cabin.position.set(-direction * 0.025, 0.22, 0);
    vehicle.add(cabin);
    const wheelMaterial = new THREE.MeshStandardMaterial({ color: 0x030407, roughness: 0.84 });
    for (const wheelX of [-0.12, 0.12]) {
      for (const wheelZ of [-0.115, 0.115]) {
        const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.043, 0.043, 0.035, 12), wheelMaterial);
        wheel.rotation.x = Math.PI / 2;
        wheel.position.set(wheelX, 0.075, wheelZ);
        vehicle.add(wheel);
      }
    }
    const headlight = new THREE.Mesh(
      new THREE.BoxGeometry(0.025, 0.045, 0.11),
      new THREE.MeshBasicMaterial({ color: 0xeaffff, toneMapped: false }),
    );
    headlight.position.set(direction * 0.18, 0.13, 0);
    vehicle.add(headlight);
    const tailLight = new THREE.Mesh(
      new THREE.BoxGeometry(0.018, 0.042, 0.12),
      new THREE.MeshBasicMaterial({ color: 0xff335d, toneMapped: false }),
    );
    tailLight.position.set(-direction * 0.205, 0.13, 0);
    vehicle.add(tailLight);
    if (axis === "z") vehicle.rotation.y = Math.PI / 2;
    group.add(vehicle);
    movingVehicles.push({
      object: vehicle,
      axis,
      direction,
      offset: random() * 27,
      speed: 0.75 + random() * 0.9,
      lane: axis === "x" ? (index % 2 === 0 ? 1.3 : 1.9) : (index % 2 === 0 ? -0.28 : 0.28),
    });
  }

  return { group, movingVehicles, waterMaterial, beaconMaterials };
}

export function DroneLaunchSceneCore({
  active = false,
  progress = null,
  starflightControllerRef,
  labels,
  themeOverride,
  visualOffsetX = 0,
}: DroneLaunchSceneCoreProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  const [fallback, setFallback] = useState(false);
  const [starflightActive, setStarflightActive] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const editionTheme = useEditionTheme();
  const sceneTheme = themeOverride ?? editionTheme.three;
  const lightAppearance = editionTheme.appearance === "light";

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    setStarflightActive(false);
    if (typeof navigator !== "undefined" && /jsdom/iu.test(navigator.userAgent)) {
      setFallback(true);
      return;
    }

    const random = createSeededRandom(0x4452_444d);
    const qualityController = new AdaptiveDprController(window.devicePixelRatio, performance.now());

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch {
      setFallback(true);
      return;
    }

    setFallback(false);
    renderer.setPixelRatio(qualityController.currentDpr);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.22;
    renderer.domElement.className = "drone-launch-canvas";
    renderer.domElement.setAttribute("aria-hidden", "true");
    renderer.domElement.style.cursor = reducedMotion ? "default" : "crosshair";
    host.appendChild(renderer.domElement);
    host.dataset.renderDpr = qualityController.currentDpr.toFixed(2);
    host.dataset.renderFps = reducedMotion ? "0" : String(DRONE_IDLE_FPS);
    host.dataset.renderState = reducedMotion ? "static" : "idle";

    let contextHealthy = true;
    let forceShadowUpdate = true;
    let reconcileLoop = () => undefined;

    const onContextLost = (event: Event) => {
      event.preventDefault();
      contextHealthy = false;
      renderer.domElement.style.visibility = "hidden";
      reconcileLoop();
      setFallback(true);
    };
    const onContextRestored = () => {
      contextHealthy = true;
      forceShadowUpdate = true;
      qualityController.resetMeasurements(performance.now());
      renderer.domElement.style.visibility = "visible";
      reconcileLoop();
      setFallback(false);
    };
    renderer.domElement.addEventListener("webglcontextlost", onContextLost);
    renderer.domElement.addEventListener("webglcontextrestored", onContextRestored);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050611);
    scene.fog = new THREE.FogExp2(0x08091a, 0.036);
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(5.3, 3.35, 7.5);
    camera.lookAt(0, 0.05, 0);
    const visualOffsetDirection = new THREE.Vector3(0.82, 0, -0.58).normalize();
    const visualOffset = new THREE.Vector3();

    const starTexture = makeRadialTexture([
      [0, "rgba(255,255,255,1)"],
      [0.12, "rgba(255,255,255,1)"],
      [0.38, "rgba(255,255,255,0.8)"],
      [0.68, "rgba(255,255,255,0.24)"],
      [1, "rgba(255,255,255,0)"],
    ]);
    const accentGlowTexture = makeRadialTexture([
      [0, "rgba(255,255,255,1)"],
      [0.1, "rgba(255,255,255,1)"],
      [0.32, "rgba(255,255,255,0.52)"],
      [0.58, "rgba(255,255,255,0.15)"],
      [1, "rgba(255,255,255,0)"],
    ], 256);
    const cyanNebulaTexture = makeRadialTexture([
      [0, rgba(sceneTheme.primary, 0.62)],
      [0.2, rgba(sceneTheme.secondary, 0.3)],
      [0.52, rgba(sceneTheme.tertiary, 0.13)],
      [1, rgba(sceneTheme.darkSurface, 0)],
    ], 256);
    const magentaNebulaTexture = makeRadialTexture([
      [0, rgba(sceneTheme.tertiary, 0.56)],
      [0.24, rgba(sceneTheme.secondary, 0.3)],
      [0.58, rgba(sceneTheme.primary, 0.12)],
      [1, rgba(sceneTheme.darkSurface, 0)],
    ], 256);

    const celestialBackdrop = new THREE.Group();
    const distantStars = buildStarLayer({
      count: 1_100,
      size: 0.098,
      opacity: 0.98,
      texture: starTexture,
      random,
    });
    const accentStars = buildStarLayer({
      count: 260,
      size: 0.2,
      opacity: 1,
      texture: starTexture,
      random,
      accent: true,
    });
    const beaconStars = buildStarLayer({
      count: 54,
      size: 0.36,
      opacity: 1,
      texture: starTexture,
      random,
      accent: true,
    });
    const galacticDust = buildGalacticDust(
      starTexture,
      random,
      440,
      sceneTheme,
    );
    beaconStars.points.position.z = -1.6;
    celestialBackdrop.add(
      distantStars.points,
      accentStars.points,
      beaconStars.points,
      galacticDust.dust,
    );

    const cyanNebulaMaterial = new THREE.SpriteMaterial({
      map: cyanNebulaTexture ?? undefined,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      fog: false,
    });
    const cyanNebula = new THREE.Sprite(cyanNebulaMaterial);
    cyanNebula.position.set(-5.8, 2.9, -11.5);
    cyanNebula.scale.set(10.5, 7.2, 1);
    celestialBackdrop.add(cyanNebula);

    const magentaNebulaMaterial = new THREE.SpriteMaterial({
      map: magentaNebulaTexture ?? undefined,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      fog: false,
    });
    const magentaNebula = new THREE.Sprite(magentaNebulaMaterial);
    magentaNebula.position.set(6.4, 1.8, -13.5);
    magentaNebula.scale.set(11.5, 7.8, 1);
    celestialBackdrop.add(magentaNebula);
    celestialBackdrop.visible = true;
    scene.add(celestialBackdrop);

    scene.add(new THREE.HemisphereLight(
      0xb9d8ff,
      0x15051e,
      2.05,
    ));
    const key = new THREE.DirectionalLight(0xf5eaff, 4.8);
    key.position.set(4.5, 7, 5.5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = 24;
    scene.add(key);
    const cyanRim = new THREE.PointLight(sceneTheme.primary, 52, 13, 2);
    cyanRim.position.set(-4, 1.2, 2.5);
    scene.add(cyanRim);
    const magentaRim = new THREE.PointLight(sceneTheme.tertiary, 54, 13, 2);
    magentaRim.position.set(4, 1.6, -2.6);
    scene.add(magentaRim);

    const { drone, rotors } = buildDrone(accentGlowTexture, sceneTheme);
    drone.rotation.y = -0.2;
    drone.position.y = 0.35;
    scene.add(drone);

    const nightCity = buildNightCity(random, sceneTheme);
    scene.add(nightCity.group);

    const particleCount = 240;
    const particlePositions = new Float32Array(particleCount * 3);
    for (let index = 0; index < particleCount; index += 1) {
      const radius = 2.3 + random() * 4.1;
      const angle = random() * Math.PI * 2;
      particlePositions[index * 3] = Math.cos(angle) * radius;
      particlePositions[index * 3 + 1] = -0.9 + random() * 4.5;
      particlePositions[index * 3 + 2] = Math.sin(angle) * radius;
    }
    const particleGeometry = new THREE.BufferGeometry();
    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    const particles = new THREE.Points(
      particleGeometry,
      new THREE.PointsMaterial({
        color: sceneTheme.secondary,
        size: 0.035,
        transparent: true,
        opacity: 0.52,
        depthWrite: false,
        sizeAttenuation: true,
      }),
    );
    particles.visible = true;
    scene.add(particles);

    const pointer = new THREE.Vector2();
    const pointerTarget = new THREE.Vector2();
    const pointerNdc = new THREE.Vector2();
    const raycaster = new THREE.Raycaster();
    const droneHitSphere = new THREE.Sphere(new THREE.Vector3(), 2.55);
    const refreshIntervals: number[] = [];
    let sceneElapsedSeconds = 0;
    let starflightStartedAt: number | null = null;
    let pendingPointerX = 0;
    let pendingPointerY = 0;
    let pointerDirty = false;
    let lastHitTestAt = Number.NEGATIVE_INFINITY;
    let cursorHitsDrone = false;
    let interactionUntil = 0;

    const updatePointerNdc = (clientX: number, clientY: number, rect: DOMRect) => {
      pointerNdc.x = ((clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
      pointerNdc.y = -((clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1;
    };

    const isDroneHit = (clientX: number, clientY: number, rect: DOMRect) => {
      updatePointerNdc(clientX, clientY, rect);
      raycaster.setFromCamera(pointerNdc, camera);
      droneHitSphere.center.copy(drone.position);
      droneHitSphere.radius = 2.55 * drone.scale.x;
      return raycaster.ray.intersectsSphere(droneHitSphere);
    };

    const setDroneCursorHit = (hit: boolean) => {
      if (cursorHitsDrone === hit || starflightStartedAt !== null) return;
      cursorHitsDrone = hit;
      renderer.domElement.style.cursor = hit ? "pointer" : "crosshair";
    };

    const beginStarflight = () => {
      if (starflightStartedAt !== null || reducedMotion) return;
      starflightStartedAt = sceneElapsedSeconds;
      interactionUntil = Number.POSITIVE_INFINITY;
      renderer.domElement.style.cursor = "progress";
      setStarflightActive(true);
    };
    if (starflightControllerRef) starflightControllerRef.current = beginStarflight;

    const onPointerMove = (event: PointerEvent) => {
      pendingPointerX = event.clientX;
      pendingPointerY = event.clientY;
      pointerDirty = true;
      interactionUntil = performance.now() + DRONE_INTERACTION_TAIL_MS;
    };
    const onPointerUp = (event: PointerEvent) => {
      if (event.button !== 0 || starflightStartedAt !== null) return;
      interactionUntil = performance.now() + DRONE_INTERACTION_TAIL_MS;
      const rect = host.getBoundingClientRect();
      if (!isDroneHit(event.clientX, event.clientY, rect)) return;
      beginStarflight();
    };
    const onPointerLeave = () => {
      pointerDirty = false;
      pointerTarget.set(0, 0);
      setDroneCursorHit(false);
    };
    if (!reducedMotion) {
      host.addEventListener("pointermove", onPointerMove, { passive: true });
      host.addEventListener("pointerup", onPointerUp);
      host.addEventListener("pointerleave", onPointerLeave, { passive: true });
    }

    let cameraDistanceScale = 1;
    const resize = () => {
      const width = Math.max(host.clientWidth, 1);
      const height = Math.max(host.clientHeight, 1);
      renderer.setSize(width, height, false);
      forceShadowUpdate = true;
      qualityController.resetMeasurements(performance.now());
      camera.aspect = width / height;
      cameraDistanceScale = THREE.MathUtils.clamp(1.18 / camera.aspect, 1, 1.65);
      const wideLayoutFactor = THREE.MathUtils.clamp((camera.aspect - 1.05) / 0.5, 0, 1);
      visualOffset.copy(visualOffsetDirection).multiplyScalar(visualOffsetX * wideLayoutFactor);
      particles.position.x = visualOffset.x;
      particles.position.z = visualOffset.z;
      camera.updateProjectionMatrix();
      if (reducedMotion) {
        camera.position.set(
          5.3 * cameraDistanceScale,
          3.35 * Math.min(cameraDistanceScale, 1.28),
          7.5 * cameraDistanceScale,
        );
        camera.lookAt(0, 0.02, 0);
        renderer.render(scene, camera);
      }
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    window.addEventListener("resize", resize, { passive: true });
    resize();

    let animationFrame = 0;
    let inViewport = true;
    let documentVisible = !document.hidden;
    let exitViewportTimer: number | null = null;
    let lastRafTimestamp = 0;
    let lastSceneTimestamp = 0;
    let nextRenderDue = 0;
    let lastRenderedAt = 0;
    let awaitingPostRenderSample = false;
    let lastShadowUpdateAt = Number.NEGATIVE_INFINITY;
    let renderMode: "idle" | "interactive" = "idle";

    const updateRenderState = (state: "stopped" | "idle" | "interactive" | "static") => {
      host.dataset.renderState = state;
      host.dataset.renderFps = state === "interactive"
        ? String(DRONE_INTERACTIVE_FPS)
        : state === "idle"
          ? String(DRONE_IDLE_FPS)
          : "0";
    };

    const applyRenderDpr = (pixelRatio: number, now: number) => {
      renderer.setPixelRatio(pixelRatio);
      renderer.setSize(Math.max(host.clientWidth, 1), Math.max(host.clientHeight, 1), false);
      host.dataset.renderDpr = pixelRatio.toFixed(2);
      forceShadowUpdate = true;
      lastSceneTimestamp = now;
    };

    const resetLoopTiming = (now: number) => {
      lastRafTimestamp = 0;
      lastSceneTimestamp = 0;
      nextRenderDue = now;
      lastRenderedAt = 0;
      awaitingPostRenderSample = false;
      refreshIntervals.length = 0;
      qualityController.resetMeasurements(now);
    };

    const canRun = () => shouldRunDroneRenderLoop({
      inViewport,
      documentVisible,
      contextHealthy,
      reducedMotion,
    });

    reconcileLoop = () => {
      const now = performance.now();
      if (!canRun()) {
        if (animationFrame) cancelAnimationFrame(animationFrame);
        animationFrame = 0;
        resetLoopTiming(now);
        updateRenderState(reducedMotion ? "static" : "stopped");
        return;
      }
      if (animationFrame === 0) {
        resetLoopTiming(now);
        updateRenderState("idle");
        animationFrame = requestAnimationFrame(tick);
      }
    };

    const onVisibility = () => {
      documentVisible = !document.hidden;
      reconcileLoop();
    };

    const initialRect = host.getBoundingClientRect();
    inViewport = initialRect.bottom > 0 && initialRect.top < window.innerHeight;
    const viewportObserver = typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        if (entry.isIntersecting) {
          if (exitViewportTimer !== null) window.clearTimeout(exitViewportTimer);
          exitViewportTimer = null;
          inViewport = true;
          reconcileLoop();
          return;
        }
        if (exitViewportTimer !== null) window.clearTimeout(exitViewportTimer);
        exitViewportTimer = window.setTimeout(() => {
          exitViewportTimer = null;
          inViewport = false;
          reconcileLoop();
        }, 150);
      }, { threshold: [0, 0.01] });
    viewportObserver?.observe(host);

    function renderScene(now: number, interactive: boolean) {
      const targetInterval = 1000 /
        (interactive ? DRONE_INTERACTIVE_FPS : DRONE_IDLE_FPS);
      const deltaSeconds = lastSceneTimestamp > 0
        ? Math.min((now - lastSceneTimestamp) / 1000, 0.1)
        : targetInterval / 1000;
      lastSceneTimestamp = now;
      sceneElapsedSeconds += deltaSeconds;

      if (pointerDirty) {
        const rect = host!.getBoundingClientRect();
        pointerTarget.x = ((pendingPointerX - rect.left) / Math.max(rect.width, 1) - 0.5) * 2;
        pointerTarget.y = ((pendingPointerY - rect.top) / Math.max(rect.height, 1) - 0.5) * 2;
        if (now - lastHitTestAt >= 1000 / 30) {
          setDroneCursorHit(isDroneHit(pendingPointerX, pendingPointerY, rect));
          lastHitTestAt = now;
          pointerDirty = false;
        }
      }

      const pointerBlend = 1 - Math.exp(-deltaSeconds * 2.14);
      pointer.lerp(pointerTarget, pointerBlend);
      const elapsed = sceneElapsedSeconds;
      const motion = reducedMotion ? 0 : 1;

      const idleY = 0.34 + Math.sin(elapsed * 0.72) * 0.075 * motion;
      const idleYaw = -0.2 + Math.sin(elapsed * 0.18) * 0.1 * motion + pointer.x * 0.055;
      const idlePitch = Math.sin(elapsed * 0.31) * 0.04 * motion + pointer.y * 0.02;
      const idleRoll = Math.sin(elapsed * 0.27 + 0.8) * 0.055 * motion - pointer.x * 0.02;
      let flightPose = getDroneStarflightPose(0);

      if (starflightStartedAt !== null) {
        const starflightProgress = (elapsed - starflightStartedAt) /
          DRONE_STARFLIGHT_DURATION_SECONDS;
        flightPose = getDroneStarflightPose(starflightProgress);
        if (starflightProgress >= 1) {
          starflightStartedAt = null;
          interactionUntil = now + DRONE_INTERACTION_TAIL_MS;
          renderer.domElement.style.cursor = cursorHitsDrone ? "pointer" : "crosshair";
          setStarflightActive(false);
        }
      }

      drone.position.set(
        flightPose.x + visualOffset.x,
        idleY + flightPose.y,
        flightPose.z + visualOffset.z,
      );
      drone.scale.setScalar(flightPose.scale);
      drone.rotation.y = idleYaw + flightPose.yaw;
      drone.rotation.x = idlePitch + flightPose.pitch;
      drone.rotation.z = idleRoll + flightPose.roll;
      rotors.forEach((rotor, index) => {
        const rotorSpeed = activeRef.current || starflightStartedAt !== null ? 43.2 : 20.4;
        rotor.rotation.y += rotorSpeed * deltaSeconds * (index % 2 === 0 ? 1 : -1) * motion;
      });
      particles.rotation.y = elapsed * 0.012 * motion;
      particles.position.y = Math.sin(elapsed * 0.3) * 0.08 * motion;
      celestialBackdrop.rotation.y = Math.sin(elapsed * 0.025) * 0.025 * motion;
      distantStars.material.opacity = 0.97 + Math.sin(elapsed * 0.36) * 0.03 * motion;
      accentStars.material.opacity = 0.99 + Math.sin(elapsed * 0.7 + 1.4) * 0.01 * motion;
      beaconStars.material.opacity = 0.99 + Math.sin(elapsed * 1.05 + 0.8) * 0.01 * motion;
      beaconStars.points.rotation.z = elapsed * 0.006 * motion;
      galacticDust.material.opacity = 0.36 + Math.sin(elapsed * 0.2) * 0.04 * motion;
      cyanNebulaMaterial.opacity = 0.31 + Math.sin(elapsed * 0.12) * 0.035 * motion;
      magentaNebulaMaterial.opacity = 0.27 + Math.sin(elapsed * 0.1 + 2.2) * 0.04 * motion;
      nightCity.waterMaterial.emissiveIntensity = 0.1 + Math.sin(elapsed * 0.55) * 0.035 * motion;
      nightCity.beaconMaterials.forEach((material, index) => {
        material.opacity = 0.42 + (Math.sin(elapsed * 2.4 + index * 0.73) + 1) * 0.27;
      });
      nightCity.movingVehicles.forEach((vehicle) => {
        const travel = ((elapsed * vehicle.speed + vehicle.offset) % 28) - 14;
        if (vehicle.axis === "x") {
          vehicle.object.position.set(travel * vehicle.direction, 0, vehicle.lane);
        } else {
          vehicle.object.position.set(vehicle.lane, 0, travel * vehicle.direction);
        }
      });
      camera.position.x = (5.3 + pointer.x * 0.28) * cameraDistanceScale;
      camera.position.y = (3.35 - pointer.y * 0.16) * Math.min(cameraDistanceScale, 1.28);
      camera.position.z = 7.5 * cameraDistanceScale;
      camera.lookAt(0, 0.02, 0);
      const shadowInterval = interactive ? 1000 / 30 : 1000 / 15;
      if (forceShadowUpdate || now - lastShadowUpdateAt >= shadowInterval) {
        renderer.shadowMap.needsUpdate = true;
        forceShadowUpdate = false;
        lastShadowUpdateAt = now;
      }
      renderer.render(scene, camera);
      lastRenderedAt = now;
      awaitingPostRenderSample = true;
    }

    function tick(now: number) {
      animationFrame = 0;
      if (!canRun()) return;

      if (lastRafTimestamp > 0) {
        const refreshGap = now - lastRafTimestamp;
        if (refreshGap >= 4 && refreshGap <= 50) {
          refreshIntervals.push(refreshGap);
          if (refreshIntervals.length > 90) refreshIntervals.shift();
        }
      }
      lastRafTimestamp = now;

      const interactive = starflightStartedAt !== null || now < interactionUntil;
      const nextMode = interactive ? "interactive" : "idle";
      if (renderMode !== nextMode) {
        renderMode = nextMode;
        nextRenderDue = now;
        updateRenderState(nextMode);
      }

      if (awaitingPostRenderSample && lastRenderedAt > 0) {
        awaitingPostRenderSample = false;
        const refreshInterval = estimateRefreshInterval(refreshIntervals);
        const changedDpr = qualityController.recordFrameGap({
          gapMs: now - lastRenderedAt,
          budgetMs: renderGapBudget(refreshInterval),
          now,
          interactive,
        });
        if (changedDpr !== null) applyRenderDpr(changedDpr, now);
      }

      const frameInterval = 1000 /
        (interactive ? DRONE_INTERACTIVE_FPS : DRONE_IDLE_FPS);
      if (nextRenderDue <= 0) nextRenderDue = now;
      if (now + 0.5 >= nextRenderDue) {
        const missedFrames = Math.max(0, Math.floor((now - nextRenderDue) / frameInterval));
        nextRenderDue += (missedFrames + 1) * frameInterval;
        renderScene(now, interactive);
      }

      animationFrame = requestAnimationFrame(tick);
    }

    document.addEventListener("visibilitychange", onVisibility);
    if (reducedMotion) {
      updateRenderState("static");
      renderScene(performance.now(), false);
    } else {
      reconcileLoop();
    }

    return () => {
      inViewport = false;
      documentVisible = false;
      if (animationFrame) cancelAnimationFrame(animationFrame);
      if (exitViewportTimer !== null) window.clearTimeout(exitViewportTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerup", onPointerUp);
      host.removeEventListener("pointerleave", onPointerLeave);
      if (starflightControllerRef) starflightControllerRef.current = null;
      viewportObserver?.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener("resize", resize);
      renderer.domElement.removeEventListener("webglcontextlost", onContextLost);
      renderer.domElement.removeEventListener("webglcontextrestored", onContextRestored);
      disposeScene(scene);
      starTexture?.dispose();
      accentGlowTexture?.dispose();
      cyanNebulaTexture?.dispose();
      magentaNebulaTexture?.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [editionTheme.id, lightAppearance, reducedMotion, sceneTheme, starflightControllerRef, visualOffsetX]);

  const taglineLines = launchTaglineLines(labels);

  return (
    <div
      className="drone-launch-scene"
      ref={hostRef}
      data-progress={progress ?? undefined}
      data-flight-state={starflightActive ? "starflight" : "hover"}
      data-theme-edition={editionTheme.id}
      data-theme-appearance={editionTheme.appearance}
      data-scene-stars="true"
      data-scene-particles="true"
      data-reduced-motion={reducedMotion ? "true" : "false"}
      data-theme-primary={`#${sceneTheme.primary.toString(16).padStart(6, "0")}`}
      data-theme-secondary={`#${sceneTheme.secondary.toString(16).padStart(6, "0")}`}
      data-theme-tertiary={`#${sceneTheme.tertiary.toString(16).padStart(6, "0")}`}
      data-theme-grants-hardware-authority="false"
    >
      <div className="drone-launch-aura" aria-hidden="true" />
      <h1
        className={`drone-launch-tagline drone-launch-tagline-${labels.locale === "zh-CN" ? "zh" : "en"}${starflightActive ? " is-hidden" : ""}`}
        aria-label={labels.tagline}
        data-line-count={taglineLines.length}
      >
        {taglineLines.map((line, index) => (
          <span className="drone-launch-tagline-line" key={`${index}:${line}`}>
            {line}{index < taglineLines.length - 1 ? " " : null}
          </span>
        ))}
      </h1>
      {fallback ? (
        <div className="drone-launch-fallback" aria-hidden="true">
          <span className="drone-launch-fallback-body" />
          <span className="drone-launch-fallback-rotor rotor-a" />
          <span className="drone-launch-fallback-rotor rotor-b" />
          <span className="drone-launch-fallback-rotor rotor-c" />
          <span className="drone-launch-fallback-rotor rotor-d" />
        </div>
      ) : null}
    </div>
  );
}

export function DroneLaunchScene({
  telemetryActiveLabel,
  telemetryStandbyLabel,
  telemetrySystemLabel,
  ...props
}: DroneLaunchSceneProps) {
  const { locale, t } = useI18n();
  return (
    <DroneLaunchSceneCore
      {...props}
      labels={{
        locale,
        tagline: t("launcher.tagline"),
        system: telemetrySystemLabel ?? t("launcher.telemetry.system"),
        active: telemetryActiveLabel ?? t("launcher.telemetry.linkActive"),
        standby: telemetryStandbyLabel ?? t("launcher.telemetry.standby"),
        attitude: t("launcher.telemetry.attitude"),
        hold: t("launcher.telemetry.hold"),
        cruise: t("launcher.telemetry.cruise"),
      }}
    />
  );
}
