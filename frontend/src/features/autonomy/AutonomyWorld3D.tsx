import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

type MissionId = "coffee" | "gates" | "narrow";

interface AutonomyWorld3DProps {
  missionId: MissionId;
  progress: number;
  planned: boolean;
  obstacleInjected: boolean;
  dynamicEntityActive: boolean;
  perception: "fusion" | "vision" | "map";
  mapName: string;
}

const ROUTES: Record<MissionId, Array<[number, number, number]>> = {
  coffee: [
    [-14, 8.4, 8], [-10, 8.4, 4], [-7, 6.6, 1], [-7, 4.4, -2],
    [-5, 2.4, -5], [1, 1.8, -7], [8, 1.8, -4], [14, 1.6, 3],
    [8, 2.0, -3], [0, 2.6, -7], [-7, 4.6, -2], [-10, 7.0, 4], [-14, 8.4, 8],
  ],
  gates: [
    [-15, 1.8, -6], [-10, 2.0, -3], [-5, 2.4, 0], [0, 2.2, 2],
    [5, 2.7, 1], [10, 2.3, 4], [15, 1.6, 6],
  ],
  narrow: [
    [-14, 1.5, -7], [-10, 1.8, -3], [-5, 2.0, -1], [-1, 1.7, 4],
    [4, 1.9, 1], [8, 1.6, 5], [14, 1.2, 7],
  ],
};

function material(color: number, roughness = 0.72, opacity = 1) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness,
    metalness: 0.08,
    transparent: opacity < 1,
    opacity,
  });
}

function addBox(
  group: THREE.Group,
  size: [number, number, number],
  position: [number, number, number],
  color = 0xc9c4d4,
) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material(color));
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function addTree(group: THREE.Group, x: number, z: number, height = 4.8) {
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(0.25, 0.38, height * 0.56, 12),
    material(0x765846),
  );
  trunk.position.set(x, height * 0.28, z);
  trunk.castShadow = true;
  group.add(trunk);
  const crownMaterial = material(0x5aa880);
  [[0, 0], [-0.8, 0.2], [0.75, 0.15]].forEach(([offsetX, offsetZ], index) => {
    const crown = new THREE.Mesh(
      new THREE.IcosahedronGeometry(index === 0 ? 1.4 : 1.05, 1),
      crownMaterial,
    );
    crown.position.set(x + offsetX, height * 0.72 + index * 0.18, z + offsetZ);
    crown.castShadow = true;
    group.add(crown);
  });
}

function addGate(group: THREE.Group, x: number, y: number, z: number, color = 0x8b68f5) {
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(1.65, 0.14, 16, 64),
    material(color, 0.35),
  );
  ring.position.set(x, y, z);
  ring.castShadow = true;
  group.add(ring);
  const left = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, y * 2, 10), material(0x6d6479));
  left.position.set(x - 1.65, y / 2, z);
  const right = left.clone();
  right.position.x = x + 1.65;
  group.add(left, right);
}

function buildCoffeeWorld(group: THREE.Group) {
  addBox(group, [9, 0.45, 7], [-12, 1, 5], 0xe5e0e8);
  addBox(group, [9, 0.45, 7], [-12, 4.1, 5], 0xded7e5);
  addBox(group, [9, 0.45, 7], [-12, 7.2, 5], 0xd6cde0);
  addBox(group, [7, 3.2, 0.35], [-12, 8.8, 1.55], 0xc7bfd0);
  addBox(group, [0.35, 3.2, 7], [-16.4, 8.8, 5], 0xc7bfd0);
  for (let index = 0; index < 12; index += 1) {
    addBox(group, [1.25, 0.22, 2.2], [-7.8 + index * 0.47, 6.9 - index * 0.43, 0.4 - index * 0.52], 0xa99fb7);
  }
  addBox(group, [7.2, 5.5, 6], [7.5, 2.75, 6.2], 0xbfc7d7);
  addBox(group, [4.5, 3.8, 5], [13, 1.9, -6], 0xd4c6cf);
  addTree(group, 2.5, -3.2, 5.4);
  addTree(group, 8.5, -7.5, 4.7);
  addTree(group, 13, 0.8, 5.8);
  const signPost = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 2.4, 10), material(0x675f6d));
  signPost.position.set(3.5, 1.2, 4.3);
  group.add(signPost);
  addBox(group, [1.7, 0.85, 0.14], [3.5, 2.1, 4.3], 0xf1c85b);
  const dock = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 0.16, 48), material(0xe4a83d));
  dock.position.set(14, 0.08, 3);
  group.add(dock);
}

function buildGateWorld(group: THREE.Group) {
  for (let index = 0; index < 16; index += 1) {
    const x = -14 + index * 1.9;
    const z = (index % 2 === 0 ? 6.5 : -7) + Math.sin(index * 1.6) * 1.4;
    addTree(group, x, z, 4 + (index % 4) * 0.55);
  }
  addGate(group, -5, 2.4, 0);
  addGate(group, 0, 2.2, 2);
  addGate(group, 5, 2.7, 1);
  addBox(group, [3.5, 4.2, 2.2], [-1, 2.1, -5.2], 0x9b94a4);
}

function buildNarrowWorld(group: THREE.Group) {
  addBox(group, [30, 4.8, 0.4], [0, 2.4, -9], 0xc6c1cf);
  addBox(group, [30, 4.8, 0.4], [0, 2.4, 9], 0xc6c1cf);
  addBox(group, [4.8, 4, 5.2], [-7, 2, -3], 0xbab3c6);
  addBox(group, [5.5, 4.6, 4.2], [1, 2.3, 5.8], 0xd0cad8);
  addBox(group, [4.4, 3.8, 5], [8.5, 1.9, -2.8], 0xbab3c6);
  const dock = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 0.14, 48), material(0x62c9df));
  dock.position.set(14, 0.07, 7);
  group.add(dock);
}

function createDrone() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.3, 0.65), material(0x393347, 0.3));
  group.add(body);
  const armMaterial = material(0x665f74, 0.3);
  const armA = new THREE.Mesh(new THREE.BoxGeometry(2.15, 0.1, 0.12), armMaterial);
  armA.rotation.y = Math.PI / 4;
  const armB = armA.clone();
  armB.rotation.y = -Math.PI / 4;
  group.add(armA, armB);
  const rotorMaterial = new THREE.MeshBasicMaterial({ color: 0x65d5e8, transparent: true, opacity: 0.65 });
  [[-0.75, -0.75], [-0.75, 0.75], [0.75, -0.75], [0.75, 0.75]].forEach(([x, z]) => {
    const rotor = new THREE.Mesh(new THREE.TorusGeometry(0.43, 0.035, 8, 32), rotorMaterial);
    rotor.rotation.x = Math.PI / 2;
    rotor.position.set(x, 0.18, z);
    group.add(rotor);
  });
  const sensor = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.22, 0.2), material(0xe24ac1, 0.25));
  sensor.position.set(0, -0.05, -0.42);
  group.add(sensor);
  group.scale.setScalar(0.78);
  return group;
}

function createPerson() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.32, 1.05, 6, 12), material(0xe24a7e));
  body.position.y = 1.05;
  group.add(body);
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1.15, 1.24, 64),
    new THREE.MeshBasicMaterial({ color: 0xe24a7e, transparent: true, opacity: 0.5, side: THREE.DoubleSide }),
  );
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.025;
  group.add(ring);
  return group;
}

export function AutonomyWorld3D({
  missionId,
  progress,
  planned,
  obstacleInjected,
  dynamicEntityActive,
  perception,
  mapName,
}: AutonomyWorld3DProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const progressRef = useRef(progress);
  const [webglError, setWebglError] = useState(false);
  progressRef.current = progress;

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
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(perception === "vision" ? 0x15131b : 0xf4f2f7);
    scene.fog = new THREE.Fog(scene.background, perception === "vision" ? 22 : 38, 58);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 160);
    camera.position.set(25, 22, 28);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 10;
    controls.maxDistance = 70;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.target.set(0, 2.5, 0);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x696270, perception === "vision" ? 1.15 : 2.0));
    const key = new THREE.DirectionalLight(0xffffff, perception === "vision" ? 1.8 : 2.6);
    key.position.set(-12, 24, 14);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    scene.add(key);
    const accent = new THREE.PointLight(0x9b64ff, 10, 35);
    accent.position.set(10, 10, -8);
    scene.add(accent);

    const world = new THREE.Group();
    scene.add(world);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(42, 32),
      material(perception === "vision" ? 0x28232e : 0xebe8ef, 0.95),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    world.add(ground);
    const grid = new THREE.GridHelper(42, 42, 0x8e7fad, perception === "vision" ? 0x35303b : 0xd7d0df);
    grid.position.y = 0.02;
    world.add(grid);
    if (missionId === "coffee") buildCoffeeWorld(world);
    else if (missionId === "gates") buildGateWorld(world);
    else buildNarrowWorld(world);

    const routePoints = ROUTES[missionId].map(([x, y, z]) => new THREE.Vector3(x, y, z));
    const curve = new THREE.CatmullRomCurve3(routePoints, false, "centripetal", 0.25);
    const routeGeometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(240));
    const route = new THREE.Line(
      routeGeometry,
      new THREE.LineBasicMaterial({ color: obstacleInjected ? 0xe44cc6 : 0x7565f3, transparent: true, opacity: planned ? 0.95 : 0.14 }),
    );
    world.add(route);

    const start = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.12, 48), material(0x6d56dc));
    start.position.copy(routePoints[0]);
    start.position.y = 0.06;
    world.add(start);
    const drone = createDrone();
    drone.visible = planned;
    world.add(drone);
    const person = createPerson();
    person.visible = dynamicEntityActive;
    world.add(person);

    if (perception !== "map") {
      const coneGeometry = new THREE.ConeGeometry(2.4, 7, 32, 1, true);
      const coneMaterial = new THREE.MeshBasicMaterial({ color: 0x43d1df, transparent: true, opacity: 0.09, side: THREE.DoubleSide, depthWrite: false });
      const cone = new THREE.Mesh(coneGeometry, coneMaterial);
      cone.rotation.x = Math.PI / 2;
      cone.position.set(0, -0.4, -3.2);
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
      const position = curve.getPointAt(routeProgress);
      const tangent = curve.getTangentAt(Math.min(0.999, routeProgress));
      drone.position.copy(position);
      drone.position.y += Math.sin(elapsed * 3.2) * 0.06;
      drone.rotation.y = Math.atan2(tangent.x, tangent.z);
      person.visible = dynamicEntityActive;
      person.position.set(position.x + 1.2, 0, position.z + 0.4);
      person.rotation.y = elapsed * 0.25;
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
      controls.dispose();
      scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh) && !(object instanceof THREE.Line)) return;
        object.geometry.dispose();
        const objectMaterial = object.material;
        if (Array.isArray(objectMaterial)) objectMaterial.forEach((item) => item.dispose());
        else objectMaterial.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [dynamicEntityActive, missionId, obstacleInjected, perception, planned]);

  return (
    <div className="autonomy-world-3d" data-scene={missionId} data-perception={perception}>
      <div ref={mountRef} className="autonomy-world-3d-canvas" aria-label={`${mapName} interactive 3D mission world`} />
      <div className="autonomy-world-3d-toolbar">
        <span><i />3D WORLD</span>
        <span>{perception === "fusion" ? "MAP + LIVE FUSION" : perception === "vision" ? "LIVE LOCAL SLAM" : "PRIOR MAP"}</span>
        <small>Drag to orbit · Wheel to zoom</small>
      </div>
      {webglError ? <div className="autonomy-world-3d-error">WebGL is unavailable. The mission contract remains visible, but the 3D world cannot be rendered on this device.</div> : null}
    </div>
  );
}
