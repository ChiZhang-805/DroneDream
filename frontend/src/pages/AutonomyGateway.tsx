import { Box, Cable, ExternalLink, Map, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import type {
  AutonomyAssetConnector,
  AutonomyAssetConnectorCatalog,
  AutonomyAssetKind,
  AutonomyAssetMaturity,
  AutonomyConnectorAvailability,
} from "../features/autonomy/assetConnectors";
import { useI18n } from "../i18n/I18nProvider";

const MATURITY_ORDER: AutonomyAssetMaturity[] = [
  "visual_only",
  "physics_ready",
  "simulation_ready",
  "flight_ready",
  "qualified",
];

function ConnectorRow({
  connector,
  chinese,
}: {
  connector: AutonomyAssetConnector;
  chinese: boolean;
}) {
  const availability: Record<AutonomyConnectorAvailability, string> = chinese
    ? {
        builtin: "内置",
        companion_required: "需要本地桥接器",
        plugin_required: "需要插件",
      }
    : {
        builtin: "Built in",
        companion_required: "Local companion",
        plugin_required: "Plugin required",
      };
  const kinds: Record<AutonomyAssetKind, string> = chinese
    ? { map: "地图", world: "世界", vehicle: "无人机" }
    : { map: "Map", world: "World", vehicle: "Aircraft" };
  const maturity: Record<AutonomyAssetMaturity, string> = chinese
    ? {
        visual_only: "仅视觉",
        physics_ready: "物理就绪",
        simulation_ready: "仿真就绪",
        flight_ready: "飞行就绪",
        qualified: "已认证",
      }
    : {
        visual_only: "Visual only",
        physics_ready: "Physics ready",
        simulation_ready: "Simulation ready",
        flight_ready: "Flight ready",
        qualified: "Qualified",
      };

  return (
    <li className="autonomy-connector-row">
      <div className="autonomy-connector-name">
        <strong>{connector.name}</strong>
        <span>{connector.source_formats.join(" · ")}</span>
      </div>
      <span>{connector.asset_kinds.map((kind) => kinds[kind]).join(" / ")}</span>
      <span>{availability[connector.availability]}</span>
      <span>{maturity[connector.maximum_import_maturity]}</span>
    </li>
  );
}

export function AutonomyGateway() {
  const { locale } = useI18n();
  const chinese = locale === "zh-CN";
  const [catalog, setCatalog] = useState<AutonomyAssetConnectorCatalog | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    void apiClient.getAutonomyAssetConnectors().then(
      (next) => {
        if (active) setCatalog(next);
      },
      () => {
        if (active) setError(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  const grouped = useMemo(() => {
    const items = catalog?.items ?? [];
    return {
      ready: items.filter((item) => item.enabled),
      optional: items.filter((item) => !item.enabled),
    };
  }, [catalog]);

  return (
    <main className="autonomy-gateway-page">
      <header className="autonomy-gateway-header">
        <div>
          <p>AUTONOMY</p>
          <h1>{chinese ? "自主任务" : "Autonomous tasks"}</h1>
        </div>
        <Link className="button button-primary" to="/assistant?workspace=autonomy">
          {chinese ? "新建任务" : "New task"}
          <ExternalLink size={16} aria-hidden="true" />
        </Link>
      </header>

      <section className="autonomy-gateway-status" aria-label={chinese ? "资产边界" : "Asset boundary"}>
        <div><ShieldCheck aria-hidden="true" /><span>{chinese ? "导入代码默认不执行" : "Imported code never runs by default"}</span></div>
        <div><Cable aria-hidden="true" /><span>{catalog?.normalized_format ?? "ddpkg-v1"}</span></div>
        <div><Map aria-hidden="true" /><span>{chinese ? "地图与世界" : "Maps and worlds"}</span></div>
        <div><Box aria-hidden="true" /><span>{chinese ? "无人机模型" : "Aircraft models"}</span></div>
      </section>

      {error ? (
        <p className="autonomy-gateway-error">
          {chinese ? "连接器目录暂时无法读取。" : "The connector catalog is unavailable."}
        </p>
      ) : null}

      <section className="autonomy-connector-section">
        <h2>{chinese ? "可直接导入" : "Ready to import"}</h2>
        <ul>{grouped.ready.map((item) => <ConnectorRow key={item.connector_id} connector={item} chinese={chinese} />)}</ul>
      </section>

      <section className="autonomy-connector-section">
        <h2>{chinese ? "桥接器与插件" : "Companions and plugins"}</h2>
        <ul>{grouped.optional.map((item) => <ConnectorRow key={item.connector_id} connector={item} chinese={chinese} />)}</ul>
      </section>

      <ol className="autonomy-maturity-strip" aria-label={chinese ? "资格等级" : "Qualification levels"}>
        {MATURITY_ORDER.map((level, index) => (
          <li key={level}><b>L{index + 1}</b><span>{chinese
            ? ["仅视觉", "物理就绪", "仿真就绪", "飞行就绪", "已认证"][index]
            : ["Visual", "Physics", "Simulation", "Flight", "Qualified"][index]}</span></li>
        ))}
      </ol>
    </main>
  );
}

