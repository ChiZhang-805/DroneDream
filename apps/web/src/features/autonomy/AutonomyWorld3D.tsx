import { useEffect, useRef, useState } from "react";
import { Building2, Eye, EyeOff, Layers3 } from "lucide-react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { createMyDroneModel } from "./myDroneModel";
import {
  buildSchoolMapScene,
  SCHOOL_MAP_CONTRACT,
  SCHOOL_MAP_ROAD_NETWORK,
  type SchoolMapFloor,
  type SchoolMapMissionId,
} from "./schoolMapScene";
import { useI18n } from "../../i18n/I18nProvider";

type MissionId = SchoolMapMissionId;

interface AutonomyWorld3DProps {
  missionId: MissionId;
  progress: number;
  planned: boolean;
  obstacleInjected: boolean;
  dynamicEntityActive: boolean;
  perception: "fusion" | "vision" | "map";
  mapName: string;
  vehicleEnvelopeCenterWorldEnuM?: { x: number; y: number; z: number } | null;
}

function material(color: number, roughness = 0.72, opacity = 1) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness,
    metalness: 0.08,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity > 0.45,
  });
}

function createPerson() {
  const group = new THREE.Group();
  group.name = "dynamic-person";
  group.userData = { semanticKind: "person", trackId: "person-live-01" };
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.96, 6, 12), material(0xe24a7e));
  body.position.y = 0.98;
  body.castShadow = true;
  group.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.22, 18, 12), material(0xd89a78));
  head.position.y = 1.73;
  head.castShadow = true;
  group.add(head);
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1.15, 1.24, 64),
    new THREE.MeshBasicMaterial({ color: 0xe24a7e, transparent: true, opacity: 0.45, side: THREE.DoubleSide }),
  );
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.025;
  group.add(ring);
  return group;
}

function floorLabel(floor: SchoolMapFloor, chinese: boolean) {
  if (floor === "all") return chinese ? "全部" : "ALL";
  return chinese ? `${floor} 层` : `L${floor}`;
}

export function AutonomyWorld3D({
  missionId,
  progress,
  planned,
  obstacleInjected,
  dynamicEntityActive,
  perception,
  mapName,
  vehicleEnvelopeCenterWorldEnuM = null,
}: AutonomyWorld3DProps) {
  const { locale } = useI18n();
  const chinese = locale === "zh-CN";
  const mountRef = useRef<HTMLDivElement | null>(null);
  const progressRef = useRef(progress);
  const vehicleEnvelopeCenterRef = useRef(vehicleEnvelopeCenterWorldEnuM);
  const [webglError, setWebglError] = useState(false);
  const [xRay, setXRay] = useState(false);
  const [floor, setFloor] = useState<SchoolMapFloor>("all");
  progressRef.current = progress;
  vehicleEnvelopeCenterRef.current = vehicleEnvelopeCenterWorldEnuM;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
    setWebglError(false);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setWebglError(true);
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.92;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(perception === "vision" ? 0x121017 : 0xdfe8ef);
    scene.fog = new THREE.Fog(scene.background, perception === "vision" ? 80 : 128, 230);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 360);
    if (floor === "all") camera.position.set(74, 58, -86);
    else camera.position.set(35, 24, 43);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.minDistance = 5;
    controls.maxDistance = 190;
    controls.maxPolarAngle = Math.PI * 0.495;
    if (floor === "all") controls.target.set(-4, 3.2, 1);
    else controls.target.set(-27, (floor - 1) * 3.6 + 1.8, 5);
    const cameraPresets = {
      "teaching-entrance": { position: [-25, 5.8, -12], target: [-25, 1.35, 2] },
      "teaching-stair": { position: [15, 10, -1], target: [-0.1, 3.6, 10.5] },
      "cafeteria-entrance": { position: [30, 6.2, -8], target: [30, 1.5, 7.5] },
      "cafeteria-stair": { position: [54, 8, 8], target: [40, 2.2, 20] },
    } satisfies Record<string, { position: [number, number, number]; target: [number, number, number] }>;
    const applyCameraPreset = (event: Event) => {
      const presetName = (event as CustomEvent<{ preset?: keyof typeof cameraPresets }>).detail?.preset;
      if (!presetName) return;
      const preset = cameraPresets[presetName];
      camera.position.set(...preset.position);
      controls.target.set(...preset.target);
      controls.update();
    };
    window.addEventListener("dronedream:school-map-camera", applyCameraPreset);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x6c6974, perception === "vision" ? 1.2 : 1.25));
    const sun = new THREE.DirectionalLight(0xfff9ef, perception === "vision" ? 1.7 : 1.9);
    sun.position.set(-42, 72, 28);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -70;
    sun.shadow.camera.right = 70;
    sun.shadow.camera.top = 62;
    sun.shadow.camera.bottom = -62;
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0xcdbfff, 0.62);
    fill.position.set(60, 28, -45);
    scene.add(fill);
    const accent = new THREE.PointLight(0xd85bcf, 8, 45);
    accent.position.set(48, 10, 2);
    scene.add(accent);

    const world = new THREE.Group();
    scene.add(world);
    const school = buildSchoolMapScene(world, { xRay, floor });
    const routePoints = school.routes[missionId];
    const curve = new THREE.CatmullRomCurve3(routePoints, false, "centripetal", 0.18);
    const routeGeometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(640));
    const route = new THREE.Line(
      routeGeometry,
      new THREE.LineBasicMaterial({
        color: obstacleInjected ? 0xe44cc6 : 0x6659f5,
        transparent: true,
        opacity: planned ? 0.96 : 0.12,
      }),
    );
    route.name = "qualified-school-route";
    route.userData = { semanticKind: "trajectory", missionId, mapId: "school-campus-v1" };
    world.add(route);

    const start = new THREE.Mesh(
      new THREE.CylinderGeometry(0.86, 0.86, 0.07, 48),
      material(0x6d56dc, 0.38, 0.92),
    );
    start.position.copy(routePoints[0]);
    start.position.y -= 0.08;
    start.name = "mission-start-marker";
    world.add(start);
    const drone = createMyDroneModel();
    drone.visible = planned;
    world.add(drone);
    const droneHalo = new THREE.Mesh(
      new THREE.TorusGeometry(0.48, 0.025, 10, 48),
      new THREE.MeshBasicMaterial({ color: 0x54d8e3, transparent: true, opacity: 0.75, depthTest: false }),
    );
    droneHalo.rotation.x = Math.PI / 2;
    droneHalo.position.y = 0.2;
    droneHalo.renderOrder = 12;
    drone.add(droneHalo);
    const person = createPerson();
    person.visible = dynamicEntityActive;
    world.add(person);

    if (perception !== "map") {
      const coneGeometry = new THREE.ConeGeometry(0.85, 4.2, 32, 1, true);
      const coneMaterial = new THREE.MeshBasicMaterial({ color: 0x43d1df, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false });
      const cone = new THREE.Mesh(coneGeometry, coneMaterial);
      cone.rotation.x = Math.PI / 2;
      cone.position.set(0, -0.02, -2.05);
      cone.name = "rgbd-frustum";
      drone.add(cone);
    }

    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    let animationFrame = 0;
    const clock = new THREE.Clock();
    const render = () => {
      const elapsed = clock.getElapsedTime();
      const routeProgress = Math.min(1, Math.max(0, progressRef.current));
      const routePosition = curve.getPointAt(routeProgress);
      const worldEnuPosition = vehicleEnvelopeCenterRef.current;
      const position = worldEnuPosition
        ? new THREE.Vector3(worldEnuPosition.x, worldEnuPosition.z, worldEnuPosition.y)
        : routePosition;
      const tangent = curve.getTangentAt(Math.min(0.999, routeProgress));
      drone.position.copy(position);
      if (!worldEnuPosition) drone.position.y += Math.sin(elapsed * 3.1) * 0.025;
      drone.rotation.y = Math.atan2(tangent.x, tangent.z);
      droneHalo.rotation.z = elapsed * 0.65;
      person.visible = dynamicEntityActive;
      person.position.set(position.x + 1.45 + Math.sin(elapsed * 0.45) * 0.35, Math.max(0, position.y - 1.4), position.z + 0.85);
      person.rotation.y = elapsed * 0.18;
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
      window.removeEventListener("dronedream:school-map-camera", applyCameraPreset);
      controls.dispose();
      const geometries = new Set<THREE.BufferGeometry>();
      const materials = new Set<THREE.Material>();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite) {
          if ("geometry" in object && object.geometry instanceof THREE.BufferGeometry) geometries.add(object.geometry);
          const objectMaterial = object.material;
          (Array.isArray(objectMaterial) ? objectMaterial : [objectMaterial]).forEach((item) => materials.add(item));
        }
      });
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((item) => {
        if (item instanceof THREE.SpriteMaterial && item.map) item.map.dispose();
        item.dispose();
      });
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [dynamicEntityActive, floor, missionId, obstacleInjected, perception, planned, xRay]);

  return (
    <div
      className="autonomy-world-3d autonomy-school-world"
      data-scene="school-campus-v1"
      data-mission={missionId}
      data-perception={perception}
      data-xray={xRay ? "true" : "false"}
      data-road-segments={SCHOOL_MAP_ROAD_NETWORK.segments.length}
      data-road-junctions={SCHOOL_MAP_ROAD_NETWORK.junctions.length}
      data-vehicle-collision-diameter-m={SCHOOL_MAP_CONTRACT.simulation.vehicleCollisionDiameterM}
      data-min-road-width-m={SCHOOL_MAP_CONTRACT.simulation.minimumRoadWidthM}
      data-open-door-clearance-m={SCHOOL_MAP_CONTRACT.simulation.minimumOpenDoorClearanceM}
    >
      <div ref={mountRef} className="autonomy-world-3d-canvas" aria-label={chinese ? `${mapName}交互式语义三维校园` : `${mapName} interactive semantic 3D campus`} />
      <div className="autonomy-world-3d-toolbar">
        <span><i />{chinese ? "校园地图" : "SCHOOL MAP"}</span>
        <span>{perception === "fusion"
          ? chinese ? "地图与实时感知融合" : "MAP + LIVE FUSION"
          : perception === "vision"
            ? chinese ? "实时局部 SLAM" : "LIVE LOCAL SLAM"
            : chinese ? "先验地图" : "PRIOR MAP"}</span>
        <small>{chinese ? "拖动旋转 · 滚轮缩放" : "Drag to orbit · Wheel to zoom"}</small>
      </div>
      <div className="autonomy-world-3d-inspector" aria-label={chinese ? "校园地图视图控制" : "School Map view controls"}>
        <button type="button" className={xRay ? "is-active" : ""} onClick={() => setXRay((current) => !current)} aria-pressed={xRay}>
          {xRay ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          {xRay ? chinese ? "实体" : "Solid" : chinese ? "透视" : "X-ray"}
        </button>
        <span aria-hidden="true"><Layers3 /></span>
        {(["all", 1, 2, 3] as SchoolMapFloor[]).map((item) => (
          <button type="button" key={item} className={floor === item ? "is-active" : ""} onClick={() => setFloor(item)} aria-pressed={floor === item}>
            {item === "all" ? <Building2 aria-hidden="true" /> : null}{floorLabel(item, chinese)}
          </button>
        ))}
      </div>
      {webglError ? <div className="autonomy-world-3d-error">{chinese
        ? "当前设备无法使用 WebGL。任务合同仍可查看，但无法渲染三维校园。"
        : "WebGL is unavailable. The mission contract remains visible, but the 3D campus cannot be rendered on this device."}</div> : null}
    </div>
  );
}
