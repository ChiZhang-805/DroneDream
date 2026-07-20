import { useEffect, useRef, useState, type MutableRefObject } from "react";
import * as THREE from "three";

import { useI18n } from "../i18n/I18nProvider";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
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
  visualOffsetX?: number;
};

const CARBON = 0x171827;
const GRAPHITE = 0x30334a;
const METAL = 0x697087;
const CYAN = 0x68e8ff;
const BLUE = 0x6d8cff;
const VIOLET = 0x9b72ff;
const MAGENTA = 0xf166d8;

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

function buildDrone(accentGlowTexture: THREE.Texture | null) {
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
    color: MAGENTA,
    toneMapped: false,
  });
  const cyanLight = new THREE.MeshBasicMaterial({
    color: CYAN,
    toneMapped: false,
  });
  const cyanHotLight = new THREE.MeshBasicMaterial({
    color: CYAN,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  const magentaHotLight = new THREE.MeshBasicMaterial({
    color: MAGENTA,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  const cyanGlow = accentGlowTexture
    ? new THREE.SpriteMaterial({
        map: accentGlowTexture,
        color: CYAN,
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
        color: MAGENTA,
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

  const cyanAccentLight = new THREE.PointLight(CYAN, 14, 3.5, 2);
  cyanAccentLight.position.set(-0.62, 0.12, -0.18);
  drone.add(cyanAccentLight);
  const magentaAccentLight = new THREE.PointLight(MAGENTA, 14, 3.5, 2);
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
    const rotorColor = index % 2 === 0 ? CYAN : MAGENTA;
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
) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const cyan = new THREE.Color(CYAN);
  const violet = new THREE.Color(VIOLET);
  const magenta = new THREE.Color(MAGENTA);
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

export function DroneLaunchScene({
  active = false,
  progress = null,
  starflightControllerRef,
  visualOffsetX = 0,
}: DroneLaunchSceneProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const attitudeValueRef = useRef<HTMLSpanElement>(null);
  const activeRef = useRef(active);
  const [fallback, setFallback] = useState(false);
  const [starflightActive, setStarflightActive] = useState(false);
  const { locale, t } = useI18n();
  const reducedMotion = usePrefersReducedMotion();

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
    renderer.toneMappingExposure = 1.25;
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
    scene.fog = new THREE.FogExp2(0x090319, 0.042);
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
      [0, "rgba(105,238,255,0.62)"],
      [0.2, "rgba(70,170,255,0.3)"],
      [0.52, "rgba(78,70,190,0.13)"],
      [1, "rgba(20,5,60,0)"],
    ], 256);
    const magentaNebulaTexture = makeRadialTexture([
      [0, "rgba(255,108,221,0.56)"],
      [0.24, "rgba(190,75,255,0.3)"],
      [0.58, "rgba(70,45,165,0.12)"],
      [1, "rgba(20,5,60,0)"],
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
    scene.add(celestialBackdrop);

    scene.add(new THREE.HemisphereLight(0xb9d8ff, 0x15051e, 2.1));
    const key = new THREE.DirectionalLight(0xf5eaff, 5.2);
    key.position.set(4.5, 7, 5.5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = 24;
    scene.add(key);
    const cyanRim = new THREE.PointLight(CYAN, 52, 13, 2);
    cyanRim.position.set(-4, 1.2, 2.5);
    scene.add(cyanRim);
    const magentaRim = new THREE.PointLight(MAGENTA, 54, 13, 2);
    magentaRim.position.set(4, 1.6, -2.6);
    scene.add(magentaRim);

    const { drone, rotors } = buildDrone(accentGlowTexture);
    drone.rotation.y = -0.2;
    drone.position.y = 0.35;
    scene.add(drone);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(36, 36),
      new THREE.MeshStandardMaterial({
        color: 0x0a0719,
        roughness: 0.86,
        metalness: 0.15,
        transparent: true,
        opacity: 0.44,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.25;
    floor.receiveShadow = true;
    scene.add(floor);

    const grid = new THREE.GridHelper(28, 56, MAGENTA, 0x34244f);
    grid.position.y = -1.23;
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    gridMaterials.forEach((material) => {
      material.transparent = true;
      material.opacity = 0.28;
      material.depthWrite = false;
    });
    scene.add(grid);

    const telemetryRing = new THREE.Group();
    for (const [radius, color, opacity] of [
      [2.5, CYAN, 0.34],
      [3.25, MAGENTA, 0.22],
      [4.05, VIOLET, 0.14],
    ] as const) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius, 0.012, 8, 120),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }),
      );
      ring.rotation.x = Math.PI / 2;
      telemetryRing.add(ring);
    }
    telemetryRing.position.y = -0.88;
    scene.add(telemetryRing);

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
        color: BLUE,
        size: 0.035,
        transparent: true,
        opacity: 0.52,
        depthWrite: false,
        sizeAttenuation: true,
      }),
    );
    scene.add(particles);

    const pointer = new THREE.Vector2();
    const pointerTarget = new THREE.Vector2();
    const pointerNdc = new THREE.Vector2();
    const raycaster = new THREE.Raycaster();
    const droneHitSphere = new THREE.Sphere(new THREE.Vector3(), 2.55);
    const refreshIntervals: number[] = [];
    let sceneElapsedSeconds = 0;
    let starflightStartedAt: number | null = null;
    let lastAttitudeUpdate = -1;
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
      telemetryRing.position.x = visualOffset.x;
      telemetryRing.position.z = visualOffset.z;
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
      telemetryRing.rotation.y = elapsed * 0.055 * motion;
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
      camera.position.x = (5.3 + pointer.x * 0.28) * cameraDistanceScale;
      camera.position.y = (3.35 - pointer.y * 0.16) * Math.min(cameraDistanceScale, 1.28);
      camera.position.z = 7.5 * cameraDistanceScale;
      camera.lookAt(0, 0.02, 0);
      if (elapsed - lastAttitudeUpdate >= 0.1 && attitudeValueRef.current) {
        const rollDegrees = THREE.MathUtils.radToDeg(drone.rotation.z);
        attitudeValueRef.current.textContent = `${rollDegrees >= 0 ? "+" : ""}${rollDegrees.toFixed(1)}°`;
        lastAttitudeUpdate = elapsed;
      }

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
  }, [reducedMotion, starflightControllerRef, visualOffsetX]);

  return (
    <div
      className="drone-launch-scene"
      ref={hostRef}
      data-progress={progress ?? undefined}
      data-flight-state={starflightActive ? "starflight" : "hover"}
    >
      <div className="drone-launch-aura" aria-hidden="true" />
      <h1
        className={`drone-launch-tagline drone-launch-tagline-${locale === "zh-CN" ? "zh" : "en"}${starflightActive ? " is-hidden" : ""}`}
      >
        {t("launcher.tagline")}
      </h1>
      <div className="drone-launch-hud drone-launch-hud-left" aria-hidden="true">
        <span>{t("launcher.telemetry.system")}</span>
        <strong>{active
          ? t("launcher.telemetry.linkActive")
          : t("launcher.telemetry.standby")}</strong>
      </div>
      <div className="drone-launch-hud drone-launch-hud-right" aria-hidden="true">
        <span>{t("launcher.telemetry.attitude")}</span>
        <strong>
          {t(starflightActive ? "launcher.telemetry.cruise" : "launcher.telemetry.hold")} ·{" "}
          <span ref={attitudeValueRef}>+0.0°</span>
        </strong>
      </div>
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
