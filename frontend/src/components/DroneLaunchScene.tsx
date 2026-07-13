import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

import { useI18n } from "../i18n/I18nProvider";
import {
  DRONE_STARFLIGHT_DURATION_SECONDS,
  getDroneStarflightPose,
} from "./droneStarflight";

type DroneLaunchSceneProps = {
  active?: boolean;
  progress?: number | null;
};

const CARBON = 0x171827;
const GRAPHITE = 0x30334a;
const METAL = 0x697087;
const MAGENTA = 0xff4fd8;
const CYAN = 0x54e8ff;

function disposeScene(root: THREE.Object3D) {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) material?.dispose();
  });
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

function buildDrone() {
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
    emissiveIntensity: 0.55,
    roughness: 0.05,
    metalness: 0.2,
    transmission: 0.22,
    transparent: true,
    opacity: 0.92,
  });
  const magentaLight = new THREE.MeshStandardMaterial({
    color: MAGENTA,
    emissive: MAGENTA,
    emissiveIntensity: 4.2,
    toneMapped: false,
  });
  const cyanLight = new THREE.MeshStandardMaterial({
    color: CYAN,
    emissive: CYAN,
    emissiveIntensity: 4.2,
    toneMapped: false,
  });

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

  const motorPositions = [
    new THREE.Vector3(-1.58, 0.04, -1.3),
    new THREE.Vector3(1.58, 0.04, -1.3),
    new THREE.Vector3(-1.58, 0.04, 1.3),
    new THREE.Vector3(1.58, 0.04, 1.3),
  ];
  const rotors: THREE.Group[] = [];

  for (const [index, position] of motorPositions.entries()) {
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

    const wash = new THREE.Mesh(
      new THREE.RingGeometry(0.28, 0.76, 48),
      new THREE.MeshBasicMaterial({
        color: index % 2 === 0 ? CYAN : MAGENTA,
        transparent: true,
        opacity: 0.075,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    wash.rotation.x = -Math.PI / 2;
    wash.position.y = -0.025;
    rotor.add(wash);
    rotors.push(rotor);
    drone.add(rotor);

    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.055, 16, 10),
      position.z > 0 ? magentaLight : cyanLight,
    );
    led.position.copy(position);
    led.position.y -= 0.11;
    led.position.z += position.z > 0 ? 0.11 : -0.11;
    drone.add(led);
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
    const accent = new THREE.Mesh(sideAccentGeometry, x < 0 ? cyanLight : magentaLight);
    accent.position.set(x, 0.04, 0.02);
    drone.add(accent);
  }

  return { drone, rotors };
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
  accent = false,
}: {
  count: number;
  size: number;
  opacity: number;
  texture: THREE.Texture | null;
  accent?: boolean;
}) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const palette = [
    new THREE.Color(0xe9f7ff),
    new THREE.Color(0x86eaff),
    new THREE.Color(0xc7b4ff),
    new THREE.Color(0xff9ce7),
  ];
  for (let index = 0; index < count; index += 1) {
    const spread = accent ? 17 : 24;
    positions[index * 3] = (Math.random() - 0.5) * spread;
    positions[index * 3 + 1] = (Math.random() - 0.38) * (accent ? 10 : 14);
    positions[index * 3 + 2] = -3.5 - Math.random() * (accent ? 10 : 19);
    const color = palette[Math.floor(Math.random() * palette.length)]
      .clone()
      .multiplyScalar(0.72 + Math.random() * 0.42);
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
  });
  return { points: new THREE.Points(geometry, material), material };
}

function buildGalacticDust(texture: THREE.Texture | null) {
  const count = 440;
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const cyan = new THREE.Color(0x54dfff);
  const violet = new THREE.Color(0xa56cff);
  const magenta = new THREE.Color(0xff63d8);
  for (let index = 0; index < count; index += 1) {
    const distance = (Math.random() - 0.5) * 18;
    positions[index * 3] = distance;
    positions[index * 3 + 1] = distance * 0.18 + (Math.random() - 0.5) * 1.35;
    positions[index * 3 + 2] = -6 - Math.random() * 10;
    const mix = Math.random();
    const color = mix < 0.45
      ? cyan.clone().lerp(violet, mix / 0.45)
      : violet.clone().lerp(magenta, (mix - 0.45) / 0.55);
    color.multiplyScalar(0.45 + Math.random() * 0.45);
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
    opacity: 0.3,
    vertexColors: true,
    depthWrite: false,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    fog: false,
  });
  const dust = new THREE.Points(geometry, material);
  dust.rotation.z = -0.08;
  return { dust, material };
}

export function DroneLaunchScene({ active = false, progress = null }: DroneLaunchSceneProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const attitudeValueRef = useRef<HTMLSpanElement>(null);
  const [fallback, setFallback] = useState(false);
  const [starflightActive, setStarflightActive] = useState(false);
  const { locale, t } = useI18n();

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    setStarflightActive(false);
    if (typeof navigator !== "undefined" && /jsdom/iu.test(navigator.userAgent)) {
      setFallback(true);
      return;
    }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setFallback(true);
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    renderer.domElement.className = "drone-launch-canvas";
    renderer.domElement.setAttribute("aria-hidden", "true");
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x090319, 0.042);
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(5.3, 3.35, 7.5);
    camera.lookAt(0, 0.05, 0);

    const starTexture = makeRadialTexture([
      [0, "rgba(255,255,255,1)"],
      [0.16, "rgba(235,247,255,0.98)"],
      [0.48, "rgba(150,215,255,0.42)"],
      [1, "rgba(130,165,255,0)"],
    ]);
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
      size: 0.082,
      opacity: 0.88,
      texture: starTexture,
    });
    const accentStars = buildStarLayer({
      count: 240,
      size: 0.16,
      opacity: 0.94,
      texture: starTexture,
      accent: true,
    });
    const beaconStars = buildStarLayer({
      count: 44,
      size: 0.28,
      opacity: 0.98,
      texture: starTexture,
      accent: true,
    });
    const galacticDust = buildGalacticDust(starTexture);
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
    const cyanRim = new THREE.PointLight(CYAN, 30, 13, 2);
    cyanRim.position.set(-4, 1.2, 2.5);
    scene.add(cyanRim);
    const magentaRim = new THREE.PointLight(MAGENTA, 32, 13, 2);
    magentaRim.position.set(4, 1.6, -2.6);
    scene.add(magentaRim);

    const { drone, rotors } = buildDrone();
    drone.rotation.y = -0.2;
    drone.position.y = 0.35;
    scene.add(drone);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(5.4, 72),
      new THREE.MeshStandardMaterial({
        color: 0x0a0719,
        roughness: 0.86,
        metalness: 0.15,
        transparent: true,
        opacity: 0.62,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.25;
    floor.receiveShadow = true;
    scene.add(floor);

    const grid = new THREE.GridHelper(12, 28, MAGENTA, 0x34244f);
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
      [4.05, 0x9d7bff, 0.14],
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
      const radius = 2.3 + Math.random() * 4.1;
      const angle = Math.random() * Math.PI * 2;
      particlePositions[index * 3] = Math.cos(angle) * radius;
      particlePositions[index * 3 + 1] = -0.9 + Math.random() * 4.5;
      particlePositions[index * 3 + 2] = Math.sin(angle) * radius;
    }
    const particleGeometry = new THREE.BufferGeometry();
    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    const particles = new THREE.Points(
      particleGeometry,
      new THREE.PointsMaterial({
        color: 0xb7a6ff,
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
    const clock = new THREE.Clock();
    let starflightStartedAt: number | null = null;
    let lastAttitudeUpdate = -1;

    const updatePointerNdc = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      pointerNdc.x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
      pointerNdc.y = -((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1;
      return rect;
    };

    const isDroneHit = (event: PointerEvent) => {
      updatePointerNdc(event);
      raycaster.setFromCamera(pointerNdc, camera);
      return raycaster.intersectObject(drone, true).length > 0;
    };

    const beginStarflight = () => {
      if (starflightStartedAt !== null || reducedMotion) return;
      starflightStartedAt = clock.getElapsedTime();
      renderer.domElement.style.cursor = "progress";
      setStarflightActive(true);
    };

    const onPointerMove = (event: PointerEvent) => {
      const rect = updatePointerNdc(event);
      pointerTarget.x = ((event.clientX - rect.left) / Math.max(rect.width, 1) - 0.5) * 2;
      pointerTarget.y = ((event.clientY - rect.top) / Math.max(rect.height, 1) - 0.5) * 2;
      if (starflightStartedAt === null && !reducedMotion) {
        renderer.domElement.style.cursor = isDroneHit(event) ? "pointer" : "crosshair";
      }
    };
    const onPointerUp = (event: PointerEvent) => {
      if (event.button !== 0 || starflightStartedAt !== null || !isDroneHit(event)) return;
      beginStarflight();
    };
    host.addEventListener("pointermove", onPointerMove, { passive: true });
    host.addEventListener("pointerup", onPointerUp);

    const resize = () => {
      const width = Math.max(host.clientWidth, 1);
      const height = Math.max(host.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    resize();

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let animationFrame = 0;
    let visible = true;
    const onVisibility = () => {
      visible = !document.hidden;
      if (visible && animationFrame === 0) animationFrame = requestAnimationFrame(render);
    };

    function render() {
      animationFrame = 0;
      if (!visible) return;
      const elapsed = clock.getElapsedTime();
      const motion = reducedMotion ? 0.18 : 1;
      pointer.lerp(pointerTarget, 0.035);

      const idleY = 0.34 + Math.sin(elapsed * 0.72) * 0.075 * motion;
      const idleYaw = -0.2 + Math.sin(elapsed * 0.18) * 0.1 * motion + pointer.x * 0.055;
      const idlePitch = Math.sin(elapsed * 0.31) * 0.04 * motion + pointer.y * 0.02;
      const idleRoll = Math.sin(elapsed * 0.27 + 0.8) * 0.055 * motion - pointer.x * 0.02;
      let flightPose = getDroneStarflightPose(0);

      if (starflightStartedAt !== null) {
        const starflightProgress = (elapsed - starflightStartedAt) / DRONE_STARFLIGHT_DURATION_SECONDS;
        flightPose = getDroneStarflightPose(starflightProgress);
        if (starflightProgress >= 1) {
          starflightStartedAt = null;
          renderer.domElement.style.cursor = "crosshair";
          setStarflightActive(false);
        }
      }

      drone.position.set(flightPose.x, idleY + flightPose.y, flightPose.z);
      drone.scale.setScalar(flightPose.scale);
      drone.rotation.y = idleYaw + flightPose.yaw;
      drone.rotation.x = idlePitch + flightPose.pitch;
      drone.rotation.z = idleRoll + flightPose.roll;
      rotors.forEach((rotor, index) => {
        const rotorSpeed = active || starflightStartedAt !== null ? 0.72 : 0.34;
        rotor.rotation.y += rotorSpeed * (index % 2 === 0 ? 1 : -1) * motion;
      });
      telemetryRing.rotation.y = elapsed * 0.055 * motion;
      particles.rotation.y = elapsed * 0.012 * motion;
      particles.position.y = Math.sin(elapsed * 0.3) * 0.08 * motion;
      celestialBackdrop.rotation.y = Math.sin(elapsed * 0.025) * 0.025 * motion;
      distantStars.material.opacity = 0.82 + Math.sin(elapsed * 0.36) * 0.07 * motion;
      accentStars.material.opacity = 0.87 + Math.sin(elapsed * 0.7 + 1.4) * 0.1 * motion;
      beaconStars.material.opacity = 0.84 + Math.sin(elapsed * 1.05 + 0.8) * 0.14 * motion;
      beaconStars.points.rotation.z = elapsed * 0.006 * motion;
      galacticDust.material.opacity = 0.27 + Math.sin(elapsed * 0.2) * 0.035 * motion;
      cyanNebulaMaterial.opacity = 0.31 + Math.sin(elapsed * 0.12) * 0.035 * motion;
      magentaNebulaMaterial.opacity = 0.27 + Math.sin(elapsed * 0.1 + 2.2) * 0.04 * motion;
      camera.position.x = 5.3 + pointer.x * 0.28;
      camera.position.y = 3.35 - pointer.y * 0.16;
      camera.lookAt(0, 0.02, 0);
      if (elapsed - lastAttitudeUpdate >= 0.1 && attitudeValueRef.current) {
        const rollDegrees = THREE.MathUtils.radToDeg(drone.rotation.z);
        attitudeValueRef.current.textContent = `${rollDegrees >= 0 ? "+" : ""}${rollDegrees.toFixed(1)}°`;
        lastAttitudeUpdate = elapsed;
      }
      renderer.render(scene, camera);
      animationFrame = requestAnimationFrame(render);
    }

    document.addEventListener("visibilitychange", onVisibility);
    animationFrame = requestAnimationFrame(render);

    return () => {
      visible = false;
      if (animationFrame) cancelAnimationFrame(animationFrame);
      document.removeEventListener("visibilitychange", onVisibility);
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerup", onPointerUp);
      resizeObserver.disconnect();
      disposeScene(scene);
      starTexture?.dispose();
      cyanNebulaTexture?.dispose();
      magentaNebulaTexture?.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [active]);

  return (
    <div
      className="drone-launch-scene"
      ref={hostRef}
      data-progress={progress ?? undefined}
      data-flight-state={starflightActive ? "starflight" : "hover"}
    >
      <div className="drone-launch-aura" aria-hidden="true" />
      <div
        className={`drone-launch-tagline drone-launch-tagline-${locale === "zh-CN" ? "zh" : "en"}${starflightActive ? " is-hidden" : ""}`}
      >
        {t("launcher.tagline")}
      </div>
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
