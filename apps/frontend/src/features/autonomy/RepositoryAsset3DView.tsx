import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { CatalogAssetKind } from "./assetPresentation";
import { createMyDroneModel } from "./myDroneModel";

type Props = {
  kind: CatalogAssetKind;
  previewKey: string | null;
  name: string;
  chinese: boolean;
  onBuildingSelect?: (building: CatalogBuildingSelection | null) => void;
};

type CatalogCollisionPrimitive = {
  center_x: number;
  center_y: number;
  center_z: number;
  size_x: number;
  size_y: number;
  size_z: number;
  yaw_rad: number;
  semantic: string;
};

type CatalogGraphNode = {
  node_id: string;
  position_m: [number, number, number];
  semantic: string;
};

type CatalogGraphEdge = {
  from_node: string;
  to_node: string;
};

type CatalogBuildingFootprint = {
  building_id: string;
  height_m: number;
  points: [number, number][];
  semantic: "building";
  name: string;
  name_zh: string;
  function: string;
  function_zh: string;
};

export type CatalogBuildingSelection = Pick<CatalogBuildingFootprint, "building_id" | "name" | "name_zh" | "function" | "function_zh"> & {
  number: string;
};

type CatalogMapGeometry = {
  schema_version: "dronedream.catalog-map-geometry.v1";
  building_footprints?: CatalogBuildingFootprint[];
  primitives: CatalogCollisionPrimitive[];
  nodes: CatalogGraphNode[];
  edges: CatalogGraphEdge[];
  texture_url?: string;
};

function disposeScene(scene: THREE.Scene): void {
  scene.traverse((object) => {
    if (!(object instanceof THREE.Mesh) && !(object instanceof THREE.Line) && !(object instanceof THREE.Sprite)) return;
    if (object instanceof THREE.Mesh || object instanceof THREE.Line) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => {
      if ("map" in material && material.map instanceof THREE.Texture) material.map.dispose();
      material.dispose();
    });
  });
}

function block(
  width: number,
  height: number,
  depth: number,
  x: number,
  y: number,
  z: number,
  color: number,
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    new THREE.MeshStandardMaterial({ color, roughness: 0.74, metalness: 0.05 }),
  );
  mesh.position.set(x, y + height / 2, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function catalogMapUrl(previewKey: string): string {
  const base = import.meta.env.BASE_URL.endsWith("/") ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}asset-geometry/maps/${encodeURIComponent(previewKey)}.json`;
}

function numberedBuildingFootprints(footprints: CatalogBuildingFootprint[]): Array<CatalogBuildingFootprint & { number: string }> {
  const priority = ["Chemicum", "Exactum and Physicum", "Dynamicum", "Kumpula Campus Library", "Kumpula Campus Sports Centre"];
  return [...footprints]
    .sort((left, right) => {
      const leftPriority = priority.indexOf(left.name);
      const rightPriority = priority.indexOf(right.name);
      if (leftPriority !== rightPriority) {
        if (leftPriority < 0) return 1;
        if (rightPriority < 0) return -1;
        return leftPriority - rightPriority;
      }
      return left.name.localeCompare(right.name, "en");
    })
    .map((footprint, index) => ({ ...footprint, number: String(index + 1).padStart(3, "0") }));
}

function catalogMapModel(geometry: CatalogMapGeometry): { root: THREE.Group; buildings: THREE.Mesh[] } {
  const root = new THREE.Group();
  const base = import.meta.env.BASE_URL.endsWith("/") ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  const terrainTexture = geometry.texture_url
    ? new THREE.TextureLoader().load(`${base}${geometry.texture_url}`)
    : null;
  if (terrainTexture) {
    terrainTexture.colorSpace = THREE.SRGBColorSpace;
    terrainTexture.wrapS = THREE.ClampToEdgeWrapping;
    terrainTexture.wrapT = THREE.ClampToEdgeWrapping;
  }
  const terrainMaterial = new THREE.MeshStandardMaterial({
    color: terrainTexture ? 0xffffff : 0x4e5967,
    map: terrainTexture,
    roughness: 0.92,
    metalness: 0,
  });
  const wallMaterial = new THREE.MeshStandardMaterial({ color: 0xb7bdc9, roughness: 0.78, metalness: 0.03 });
  const obstacleMaterial = new THREE.MeshStandardMaterial({ color: 0x8d96a5, roughness: 0.8, metalness: 0.04 });
  const buildings: THREE.Mesh[] = [];
  const hasExactBuildingFootprints = Boolean(geometry.building_footprints?.length);
  for (const primitive of geometry.primitives) {
    if (primitive.semantic === "building" && hasExactBuildingFootprints) continue;
    const material = primitive.semantic === "terrain"
      ? terrainMaterial
      : primitive.semantic === "wall"
        ? wallMaterial
        : obstacleMaterial;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(primitive.size_x, primitive.size_z, primitive.size_y), material);
    mesh.position.set(primitive.center_x, primitive.center_z, -primitive.center_y);
    mesh.rotation.y = -primitive.yaw_rad;
    mesh.castShadow = primitive.semantic !== "terrain";
    mesh.receiveShadow = true;
    root.add(mesh);
  }

  for (const footprint of numberedBuildingFootprints(geometry.building_footprints ?? [])) {
    if (footprint.points.length < 3 || !Number.isFinite(footprint.height_m) || footprint.height_m <= 0) continue;
    const shape = new THREE.Shape();
    footprint.points.forEach(([x, y], index) => {
      if (index === 0) shape.moveTo(x, y);
      else shape.lineTo(x, y);
    });
    shape.closePath();
    const buildingGeometry = new THREE.ExtrudeGeometry(shape, {
      depth: footprint.height_m,
      bevelEnabled: false,
      curveSegments: 1,
      steps: 1,
    });
    // ExtrudeGeometry grows along local +Z. Rotating -90 degrees maps that
    // height to world +Y while preserving map ENU as world (X, -Z).
    buildingGeometry.rotateX(-Math.PI / 2);
    const building = new THREE.Mesh(buildingGeometry, new THREE.MeshStandardMaterial({
      color: 0xc2c8d2,
      roughness: 0.76,
      metalness: 0.03,
      emissive: 0x000000,
    }));
    building.name = footprint.building_id;
    building.userData.catalogBuilding = {
      building_id: footprint.building_id,
      name: footprint.name,
      name_zh: footprint.name_zh,
      function: footprint.function,
      function_zh: footprint.function_zh,
      number: footprint.number,
    } satisfies CatalogBuildingSelection;
    building.castShadow = true;
    building.receiveShadow = true;
    root.add(building);
    buildings.push(building);
  }

  const nodeById = new Map(geometry.nodes.map((node) => [node.node_id, node]));
  const routePositions: number[] = [];
  for (const edge of geometry.edges) {
    const from = nodeById.get(edge.from_node);
    const to = nodeById.get(edge.to_node);
    if (!from || !to) continue;
    routePositions.push(
      from.position_m[0], from.position_m[2] + 0.09, -from.position_m[1],
      to.position_m[0], to.position_m[2] + 0.09, -to.position_m[1],
    );
  }
  if (routePositions.length) {
    const routeGeometry = new THREE.BufferGeometry();
    routeGeometry.setAttribute("position", new THREE.Float32BufferAttribute(routePositions, 3));
    const routes = new THREE.LineSegments(
      routeGeometry,
      new THREE.LineBasicMaterial({ color: 0x45c9e8, transparent: true, opacity: 0.82 }),
    );
    root.add(routes);
  }

  const bounds = new THREE.Box3().setFromObject(root);
  if (!bounds.isEmpty()) {
    const center = bounds.getCenter(new THREE.Vector3());
    root.position.set(-center.x, -bounds.min.y, -center.z);
  }
  return { root, buildings };
}

function fitCameraToModel(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  model: THREE.Object3D,
  padding = 1.12,
): void {
  const bounds = new THREE.Box3().setFromObject(model);
  if (bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius;
  const verticalFov = THREE.MathUtils.degToRad(camera.fov * 0.5);
  const horizontalFov = Math.atan(Math.tan(verticalFov) * camera.aspect);
  const distance = radius / Math.sin(Math.min(verticalFov, horizontalFov)) * padding;
  controls.target.copy(center);
  camera.position.copy(center).add(
    new THREE.Vector3(0.74, 0.56, 0.86).normalize().multiplyScalar(distance),
  );
  camera.near = Math.max(0.02, distance / 2000);
  camera.far = Math.max(320, distance * 12);
  camera.updateProjectionMatrix();
  controls.minDistance = Math.max(0.1, radius * 0.35);
  controls.maxDistance = Math.max(30, distance * 4);
  controls.update();
}

function vehicleModel(key: string | null): THREE.Group {
  const drone = createMyDroneModel();
  const normalized = key ?? "";
  if (normalized.includes("vtol") || normalized.includes("tiltrotor") || normalized.includes("tailsitter")) {
    const wing = block(6.8, 0.14, 1.1, 0, 0.2, 0, 0xc9ced8);
    drone.add(wing);
  }
  if (normalized.includes("gimbal")) {
    const camera = new THREE.Mesh(
      new THREE.SphereGeometry(0.32, 20, 14),
      new THREE.MeshStandardMaterial({ color: 0x242934, metalness: 0.35, roughness: 0.4 }),
    );
    camera.position.set(0, -0.55, 0.28);
    drone.add(camera);
  }
  return drone;
}

export function RepositoryAsset3DView({ kind, previewKey, name, chinese, onBuildingSelect }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const onBuildingSelectRef = useRef(onBuildingSelect);

  useEffect(() => {
    onBuildingSelectRef.current = onBuildingSelect;
  }, [onBuildingSelect]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
    if (navigator.userAgent.toLocaleLowerCase("en-US").includes("jsdom")) return undefined;
    setUnavailable(false);
    setLoading(false);
    let cancelled = false;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
    } catch {
      setUnavailable(true);
      return undefined;
    }
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.02;
    renderer.shadowMap.enabled = true;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    mount.appendChild(renderer.domElement);
    onBuildingSelectRef.current?.(null);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf7fafc);
    scene.add(new THREE.HemisphereLight(0xffffff, 0xd9e0e8, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 3.2);
    sun.position.set(-18, 28, 16);
    sun.castShadow = true;
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 320);
    camera.position.set(kind === "map" ? 30 : 7.8, kind === "map" ? 24 : 5.8, kind === "map" ? 34 : 8.5);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = true;
    controls.enableZoom = true;
    controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
    controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.minDistance = kind === "map" ? 5 : 2.8;
    controls.maxDistance = kind === "map" ? 125 : 30;
    controls.target.set(0, kind === "map" ? 2.6 : 0, 0);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDown: { x: number; y: number } | null = null;
    let buildings: THREE.Mesh[] = [];
    let selectedBuildingId: string | null = null;
    const themeColorText = getComputedStyle(mount).getPropertyValue("--dd-brand-middle").trim() || "#a94cff";
    const themeColor = new THREE.Color(themeColorText);
    const selectBuilding = (selection: CatalogBuildingSelection | null) => {
      if (!selection) return;
      selectedBuildingId = selection.building_id;
      for (const building of buildings) {
        const material = building.material as THREE.MeshStandardMaterial;
        const selected = building.userData.catalogBuilding?.building_id === selectedBuildingId;
        material.color.set(selected ? themeColor : 0xc2c8d2);
        material.emissive.set(selected ? themeColor : 0x000000);
        material.emissiveIntensity = selected ? 0.26 : 0;
        material.roughness = selected ? 0.52 : 0.76;
        building.scale.y = selected ? 1.025 : 1;
      }
      onBuildingSelectRef.current?.(selection);
    };
    const onPointerDown = (event: PointerEvent) => {
      pointerDown = { x: event.clientX, y: event.clientY };
    };
    const onPointerUp = (event: PointerEvent) => {
      if (kind !== "map" || !pointerDown) return;
      const distance = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
      pointerDown = null;
      if (distance > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(modelRoot.children, true)
        .find((intersection) => Boolean(intersection.object.userData.catalogBuilding));
      const selection = hit?.object.userData.catalogBuilding as CatalogBuildingSelection | undefined;
      if (selection) selectBuilding(selection);
    };
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);

    const modelRoot = new THREE.Group();
    scene.add(modelRoot);
    if (kind === "vehicle") {
      const model = vehicleModel(previewKey);
      model.scale.setScalar(2.4);
      modelRoot.add(model);
      fitCameraToModel(camera, controls, modelRoot);
    } else if (previewKey) {
      setLoading(true);
      void fetch(catalogMapUrl(previewKey))
        .then(async (response) => {
          if (!response.ok) throw new Error(`Map geometry returned ${response.status}`);
          return await response.json() as CatalogMapGeometry;
        })
        .then((geometry) => {
          if (cancelled || geometry.schema_version !== "dronedream.catalog-map-geometry.v1") return;
          const model = catalogMapModel(geometry);
          buildings = model.buildings;
          modelRoot.add(model.root);
          fitCameraToModel(camera, controls, modelRoot, 0.94);
          const firstBuilding = buildings[0]?.userData.catalogBuilding as CatalogBuildingSelection | undefined;
          if (firstBuilding) selectBuilding(firstBuilding);
          setLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          setLoading(false);
          setUnavailable(true);
        });
    } else {
      setUnavailable(true);
    }

    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      if (modelRoot.children.length) fitCameraToModel(camera, controls, modelRoot, kind === "map" ? 0.94 : 1.12);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    let frame = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = window.requestAnimationFrame(render);
    };
    render();
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      controls.dispose();
      disposeScene(scene);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [kind, previewKey]);

  return (
    <div
      ref={mountRef}
      className="autonomy-repository-3d-view"
      role="img"
      aria-label={chinese ? `${name} 的交互式三维视图` : `Interactive 3D view of ${name}`}
    >
      {unavailable ? <p>{kind === "map"
        ? (chinese ? "没有可验证的三维几何，未生成替代模型。" : "No verified 3D geometry is available; no substitute model was generated.")
        : (chinese ? "当前设备无法创建三维视图。" : "3D view is unavailable on this device.")}</p> : null}
      {loading ? <p className="autonomy-repository-3d-loading">{chinese ? "正在加载三维场景…" : "Loading 3D scene…"}</p> : null}
    </div>
  );
}
