import { useEffect, useMemo, useState } from "react";

import { getAgentCoreLiveMap, getAgentCoreLiveMapImage, type AgentCoreLiveMap, type AgentCoreLiveTelemetry } from "./agentCore";
import { projectLiveTelemetry, validLiveMap } from "./liveMapProjection";

export function LiveMapView({ threadId, telemetry, chinese }: {
  threadId: string;
  telemetry: AgentCoreLiveTelemetry | null;
  chinese: boolean;
}) {
  const [registeredMap, setRegisteredMap] = useState<{ map: AgentCoreLiveMap; imageUrl: string } | null>(null);
  const [mapIssue, setMapIssue] = useState(false);
  const mapId = telemetry?.map_id;
  const mapHash = telemetry?.map_content_sha256;
  useEffect(() => {
    setRegisteredMap(null);
    setMapIssue(false);
    if (!threadId) return undefined;
    let cancelled = false;
    let imageUrl = "";
    const load = async () => {
      try {
        const map = await getAgentCoreLiveMap(threadId);
        if (!validLiveMap(map) || (mapHash && mapHash !== map.map_content_sha256)
          || (mapId && mapId !== map.map_id)) throw new Error("LIVE_MAP_VERSION_MISMATCH");
        const blob = await getAgentCoreLiveMapImage(threadId, map.map_content_sha256);
        if (cancelled) return;
        imageUrl = URL.createObjectURL(blob);
        setRegisteredMap({ map, imageUrl });
      } catch {
        if (!cancelled) setMapIssue(true);
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [threadId, mapId, mapHash]);

  const geometry = useMemo(() => registeredMap ? projectLiveTelemetry(registeredMap.map, telemetry) : null, [registeredMap, telemetry]);
  const map = registeredMap?.map;
  const markerRadius = map ? Math.min(map.width_px, map.height_px) * 0.007 : 0;
  const status = mapIssue
    ? (chinese ? "地图影像暂不可用" : "Map imagery unavailable")
    : !registeredMap
      ? (chinese ? "正在载入地图" : "Loading map")
      : !telemetry
        ? (chinese ? "等待定位" : "Waiting for position")
        : !geometry
          ? (chinese ? "等待匹配的地图定位" : "Waiting for matching map position")
          : geometry.outsideImage
            ? (chinese ? "无人机位于地图影像范围外" : "Aircraft is outside the map image")
            : null;

  return <div className="autonomy-live-map" data-ready={Boolean(registeredMap)}>
    {registeredMap && map ? <svg className="autonomy-live-route" viewBox={`0 0 ${map.width_px} ${map.height_px}`}
      preserveAspectRatio="xMidYMid meet" role="img" aria-label={chinese ? "规划路线与实时位置" : "Planned route and live position"}>
      <image href={registeredMap.imageUrl} x="0" y="0" width={map.width_px} height={map.height_px} />
      {geometry?.start && geometry.goal ? <>
        <polyline className="autonomy-live-route-shadow" points={geometry.points} />
        <polyline className="autonomy-live-route-line" points={geometry.points} />
        <circle className="autonomy-live-route-start" cx={geometry.start.x} cy={geometry.start.y} r={markerRadius}>
          <title>{chinese ? "起点" : "Start"}</title>
        </circle>
        <circle className="autonomy-live-route-goal" cx={geometry.goal.x} cy={geometry.goal.y} r={markerRadius}>
          <title>{chinese ? "终点" : "Destination"}</title>
        </circle>
      </> : null}
      {geometry?.current ? <circle className="autonomy-live-route-current" cx={geometry.current.x} cy={geometry.current.y} r={markerRadius * 1.2}>
        <title>{chinese ? "无人机" : "Aircraft"}</title>
      </circle> : null}
    </svg> : null}
    {status ? <p className="autonomy-live-map-status" role="status">{status}</p> : null}
    <div className="autonomy-live-coordinates">
      {telemetry?.coordinate_frame === "wgs84" && typeof telemetry.latitude === "number" && typeof telemetry.longitude === "number"
        ? <><strong>{telemetry.latitude.toFixed(6)}, {telemetry.longitude.toFixed(6)}</strong><span>{telemetry.altitude_m?.toFixed(1) ?? "—"} m</span></>
        : telemetry
          ? <><strong>E {telemetry.east_m?.toFixed(1) ?? "—"} · N {telemetry.north_m?.toFixed(1) ?? "—"}</strong><span>{telemetry.up_m?.toFixed(1) ?? "—"} m</span></>
          : <span>{chinese ? "等待定位" : "Waiting for position"}</span>}
    </div>
  </div>;
}
