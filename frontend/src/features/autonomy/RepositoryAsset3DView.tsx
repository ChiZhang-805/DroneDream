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

type CatalogMapGeometry = {
  schema_version: "dronedream.catalog-map-geometry.v1";
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

function catalogMapModel(geometry: CatalogMapGeometry): THREE.Group {
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
  for (const primitive of geometry.primitives) {
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
  return root;
}

function fitCameraToModel(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  model: THREE.Object3D,
): void {
  const bounds = new THREE.Box3().setFromObject(model);
  if (bounds.isEmpty()) return;
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y * 1.6, size.z) * 0.62;
  const distance = Math.max(8, radius / Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)));
  controls.target.copy(center);
  camera.position.set(center.x + distance * 0.74, center.y + distance * 0.56, center.z + distance * 0.86);
  camera.near = Math.max(0.02, distance / 2000);
  camera.far = Math.max(320, distance * 12);
  camera.updateProjectionMatrix();
  controls.minDistance = Math.max(1.5, radius * 0.08);
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

export function RepositoryAsset3DView({ kind, previewKey, name, chinese }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);

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
          modelRoot.add(model);
          fitCameraToModel(camera, controls, modelRoot);
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
