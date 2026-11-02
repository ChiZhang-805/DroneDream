import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { getPreferredAirspace, type AirspaceRequest } from "./agentCore";
import { parseAirspaceSnapshot, type AirspaceSnapshot } from "./preferredAirspaceContract";
import type { AutonomyVector3 } from "./workspaceStore";
import "./PreferredAirspaceView.css";

// 功能：
//   展示真实地图派生的透明全图空间及单条任务路线，支持剖切和体积边界查询。
// 输入：
//   request、route、chinese：当前资产对、已绑定路线和语言。
// 输出：
//   view：只读空间视图，不产生控制命令。
export function PreferredAirspaceView({ request, route = [], chinese }: { request: AirspaceRequest; route?: AutonomyVector3[]; chinese: boolean }) {
  const [data, setData] = useState<AirspaceSnapshot | null>(null);
  const [error, setError] = useState("");
  const [cut, setCut] = useState<number | null>(null);
  const [points, setPoints] = useState(false);
  const [selection, setSelection] = useState<number | null>(null);
  const mount = useRef<HTMLDivElement>(null);
  const display = useRef<((height: number | null, showPoints: boolean) => void) | null>(null);
  const identity = JSON.stringify(request);
  const routeIdentity = JSON.stringify(route);
  useEffect(() => {
    let cancelled = false;
    setData(null); setError(""); setSelection(null); setCut(null);
    const expected = JSON.parse(identity) as AirspaceRequest;
    void getPreferredAirspace(expected).then((raw) => {
      const next = parseAirspaceSnapshot(raw, expected);
      if (!cancelled) setData(next);
    }).catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "AIRSPACE_UNAVAILABLE"); });
    return () => { cancelled = true; };
  }, [identity]);
  const maxZ = data ? Math.ceil(data.volumes.reduce((z, v) => Math.max(z, v[2] + v[5] / 2), 1) * 10) / 10 : 10;
  const minZ = data ? Math.floor(data.volumes.reduce((z, v) => Math.min(z, v[2] - v[5] / 2), 0) * 10) / 10 : 0;

  useEffect(() => {
    if (!data || !mount.current) return undefined;
    const host = mount.current;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError("WEBGL_UNAVAILABLE"); return undefined; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.localClippingEnabled = true;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(48, 1, 0.05, 20000);
    camera.up.set(0, 0, 1); // Core 和渲染均采用 ENU，不套用旧 School Map 的 Y-up 坐标。
    const controls = new OrbitControls(camera, renderer.domElement);
    const bounds = new THREE.Box3();
    for (const item of data.obstacles) {
      bounds.expandByPoint(new THREE.Vector3(item[0], item[1], item[2]));
      bounds.expandByPoint(new THREE.Vector3(item[3], item[4], item[5]));
    }
    const center = bounds.isEmpty() ? new THREE.Vector3() : bounds.getCenter(new THREE.Vector3());
    const span = bounds.isEmpty() ? 10 : Math.max(5, bounds.getSize(new THREE.Vector3()).length());
    camera.position.copy(center).add(new THREE.Vector3(span * .6, -span * .7, span * .65));
    camera.far = Math.max(2000, span * 8); camera.updateProjectionMatrix();
    controls.target.copy(center);
    const clips: THREE.Plane[] = [];
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const grey = new THREE.MeshBasicMaterial({ color: 0x817d87, transparent: true, opacity: .2, depthWrite: false, clippingPlanes: clips });
    const blue = new THREE.MeshBasicMaterial({ color: 0x149dd5, transparent: true, opacity: .22, depthWrite: false, clippingPlanes: clips });
    const obstacles = new THREE.InstancedMesh(geometry, grey, data.obstacles.length);
    const volumes = new THREE.InstancedMesh(geometry, blue, data.volumes.length);
    const dummy = new THREE.Object3D();
    data.obstacles.forEach((v, i) => {
      dummy.position.set((v[0] + v[3]) / 2, (v[1] + v[4]) / 2, (v[2] + v[5]) / 2);
      dummy.scale.set(v[3] - v[0], v[4] - v[1], v[5] - v[2]); dummy.updateMatrix();
      obstacles.setMatrixAt(i, dummy.matrix);
    });
    data.volumes.forEach((v, i) => {
      dummy.position.set(v[0], v[1], v[2]); dummy.scale.set(v[3], v[4], v[5]); dummy.updateMatrix();
      volumes.setMatrixAt(i, dummy.matrix);
    });
    const centers = new THREE.BufferGeometry().setFromPoints(data.volumes.map((v) => new THREE.Vector3(v[0], v[1], v[2])));
    const pointMaterial = new THREE.PointsMaterial({ color: 0x149dd5, size: .12, clippingPlanes: clips });
    const cloud = new THREE.Points(centers, pointMaterial);
    scene.add(obstacles, volumes, cloud);
    const routePoints = JSON.parse(routeIdentity) as AutonomyVector3[];
    // 保留实际折线，不以样条平滑穿过障碍；屏幕像素宽度避免路线在全图视角消失。
    const routeGeometry = new LineGeometry();
    const routeMaterial = new LineMaterial({ color: 0xff8900, linewidth: 3, transparent: true, opacity: 1, depthWrite: false, clippingPlanes: clips });
    if (routePoints.length > 1) {
      routeGeometry.setPositions(routePoints.flatMap((p) => [p.x, p.y, p.z]));
      const routeLine = new Line2(routeGeometry, routeMaterial);
      routeLine.renderOrder = 10;
      scene.add(routeLine);
    }
    let clippingHeight: number | null = null;
    // 功能：
    //   只更新剖切及体积显示，不重建相机，保留用户选择的观察角度。
    // 输入：
    //   height、showPoints：剖切高度及中心点显示开关。
    // 输出：
    //   void：更新材质及可见性，不返回业务数据。
    display.current = (height, showPoints) => {
      clippingHeight = height;
      const planes = height === null ? [] : [new THREE.Plane(new THREE.Vector3(0, 0, -1), height)];
      for (const material of [grey, blue, pointMaterial, routeMaterial]) {
        material.clippingPlanes = planes; material.needsUpdate = true;
      }
      volumes.visible = !showPoints; cloud.visible = showPoints;
    };
    // 功能：
    //   同步画布、投影和路线线宽所需的像素分辨率。
    // 输入：
    //   host：当前视图容器。
    // 输出：
    //   void：更新渲染尺寸，不改变地图数据。
    const resize = () => {
      const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight);
      renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
      routeMaterial.resolution.set(width, height);
    };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    const ray = new THREE.Raycaster();
    // 功能：
    //   选择射线命中且未被高度剖切隐藏的真实空间体积。
    // 输入：
    //   event：画布上的鼠标点击事件。
    // 输出：
    //   void：更新所选体积索引，不生成飞行命令。
    const onClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), camera);
      const hit = ray.intersectObject(volumes).find((hit) => clippingHeight === null || hit.point.z <= clippingHeight);
      setSelection(hit?.instanceId ?? null);
    };
    renderer.domElement.addEventListener("click", onClick);
    let frame = 0;
    // 功能：
    //   使用当前相机绘制空间视图，并记录可在组件卸载时取消的动画帧。
    // 输入：
    //   scene、camera：当前真实空间场景及观察相机。
    // 输出：
    //   void：提交绘制，不更改业务状态。
    const render = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(render); };
    render();
    return () => {
      display.current = null;
      cancelAnimationFrame(frame); observer.disconnect(); controls.dispose();
      renderer.domElement.removeEventListener("click", onClick);
      geometry.dispose(); grey.dispose(); blue.dispose(); centers.dispose(); pointMaterial.dispose();
      routeGeometry.dispose(); routeMaterial.dispose(); renderer.dispose(); renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [data, routeIdentity]);

  useEffect(() => { display.current?.(cut, points); }, [data, routeIdentity, cut, points]);

  const selected = selection === null ? null : data?.volumes[selection];
  const halfHeight = (data?.binding.height_m ?? 0) / 2;
  const view = <section className="preferred-airspace-view" aria-label="3D UAV Corridor">
    <header><strong>3D UAV Corridor</strong><span>{chinese ? "蓝：理想空间 · 灰：保守障碍 · 橙：当前路线" : "Blue: preference · Grey: conservative obstacles · Orange: route"}</span></header>
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">{chinese ? "正在读取空间数据…" : "Loading spatial data…"}</p> : null}
    <div className="preferred-airspace-canvas" ref={mount} />
    {data ? <footer>
      <label><input type="checkbox" checked={cut !== null} onChange={(e) => setCut(e.target.checked ? maxZ : null)} />{chinese ? "高度剖切" : "Height clipping"}</label>
      <input aria-label={chinese ? "剖切高度" : "Clipping height"} type="range" min={minZ} max={maxZ} step="0.1" disabled={cut === null} value={cut ?? maxZ} onChange={(e) => setCut(Number(e.target.value))} />
      <output>{cut === null ? "—" : `${cut.toFixed(1)} m ENU`}</output>
      <label><input type="checkbox" checked={points} onChange={(e) => setPoints(e.target.checked)} />{chinese ? "体积中心点" : "Volume centers"}</label>
      {selected ? <output>{chinese ? "中心高度带" : "Center-height band"}: {(selected[2] - selected[5] / 2).toFixed(2)}–{(selected[2] + selected[5] / 2).toFixed(2)} m ENU · {chinese ? "下方边界" : "Lower surface"}: {selected[6].toFixed(2)} m · {chinese ? "顶部" : "Ceiling"}: {selected[7]?.toFixed(2) ?? "?"} m</output> : null}
      {selected ? <output>{chinese ? "整个高度带内机身最小下方净空" : "Minimum clearance below the body across this band"}: {(selected[2] - selected[5] / 2 - halfHeight - selected[6]).toFixed(2)} m · {chinese ? "最小顶部净空" : "Minimum overhead clearance"}: {selected[7] === null ? (chinese ? "地图未提供顶部" : "No mapped ceiling") : `${(selected[7] - selected[2] - selected[5] / 2 - halfHeight).toFixed(2)} m`}</output> : null}
      <small>{chinese ? "静态偏好，不是飞行许可；负载和实时感知仍需校验。" : "Static preference, not flight permission; payload and live perception still require checks."}</small>
    </footer> : null}
  </section>;
  return view;
}
