import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleOff,
  Download,
  LockKeyhole,
  PackageOpen,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

import sourceCatalog from "../../../distribution/editions/field/adapters/catalog.v1.json";
import {
  getFieldAdapterCatalog,
  installFieldAdapter,
  isDesktopRuntime,
  type FieldAdapterCatalogEntry,
  type FieldAdapterCatalogReport,
} from "../desktop/bridge";
import type { FieldLocale } from "./catalog";

const CATALOG_SHA256 = "f1bfbaf7586b712018d84fd8b03571b00bd181ec26559bf4cb9efbd54df5a0e5";

const COPY = {
  en: {
    title: "Protocol adapters",
    body: "Enable source-bound offline frame inspection without adding proprietary SDKs to the base app.",
    refresh: "Refresh adapter state",
    offline: "Native adapter installation is available in the installed Field app.",
    loadError: "The native adapter catalog could not be verified.",
    installError: "Adapter installation was rejected.",
    boundary: "These packages inspect captured frames only. Live serial, radio, TCP, and UDP links are not enabled yet. Vehicle Pack validation and the full native safety quorum remain mandatory for every hardware action.",
    protocol: "Protocol",
    transports: "Protocol transports",
    telemetry: "Telemetry",
    parameters: "Parameters",
    delivery: "Availability",
    install: "Install",
    installing: "Installing",
    installed: "Installed",
    available: "Offline parser available",
    vendorAccess: "Vendor access required",
    platformBridge: "Platform bridge required",
    planned: "Planned",
    readOnly: "Read-only",
    quorumRequired: "Safety quorum required",
    unavailable: "Unavailable",
    vendorControlled: "Vendor controlled",
    verified: "Source-bound catalog",
  },
  "zh-CN": {
    title: "协议适配器",
    body: "在不把专有 SDK 塞入基础应用的前提下，启用源绑定的离线帧检查。",
    refresh: "刷新适配器状态",
    offline: "原生适配器安装仅在已安装的 Field 应用中可用。",
    loadError: "无法验证原生适配器目录。",
    installError: "适配器安装被拒绝。",
    boundary: "这些适配包目前只检查已采集的协议帧，尚未启用实时串口、无线电、TCP 或 UDP 链路。任何真机动作仍必须通过机型包验证和完整原生安全仲裁。",
    protocol: "协议",
    transports: "协议可用传输方式",
    telemetry: "遥测",
    parameters: "参数",
    delivery: "可用状态",
    install: "安装",
    installing: "正在安装",
    installed: "已安装",
    available: "可启用离线解析器",
    vendorAccess: "需要厂商授权",
    platformBridge: "需要平台桥接",
    planned: "计划中",
    readOnly: "只读",
    quorumRequired: "需要安全仲裁",
    unavailable: "不可用",
    vendorControlled: "由厂商控制",
    verified: "源绑定目录",
  },
} as const;

function staticCatalog(): FieldAdapterCatalogReport {
  return {
    schemaVersion: 1,
    kind: "dronedream-field-adapter-catalog-report",
    catalogVersion: sourceCatalog.catalogVersion,
    editionId: "field",
    source: "source-bound-embedded-catalog",
    catalogSha256: CATALOG_SHA256,
    hardwareAuthority: false,
    executableExtensionLoading: false,
    entries: sourceCatalog.entries.map((entry) => ({
      ...entry,
      implementationStatus: entry.implementationStatus as FieldAdapterCatalogEntry["implementationStatus"],
      deliveryMode: entry.deliveryMode as FieldAdapterCatalogEntry["deliveryMode"],
      capabilities: entry.capabilities as FieldAdapterCatalogEntry["capabilities"],
      safety: entry.safety as FieldAdapterCatalogEntry["safety"],
      installed: false,
      installedPackageSha256: null,
    })),
  };
}

interface FieldAdapterCenterProps {
  locale: FieldLocale;
}

export function FieldAdapterCenter({ locale }: FieldAdapterCenterProps) {
  const copy = COPY[locale];
  const [catalog, setCatalog] = useState<FieldAdapterCatalogReport>(staticCatalog);
  const [busyAdapterId, setBusyAdapterId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const desktop = isDesktopRuntime();

  const loadCatalog = useCallback(async () => {
    if (!desktop) return;
    setLoading(true);
    setError(null);
    try {
      setCatalog(await getFieldAdapterCatalog());
    } catch (reason) {
      setError(`${copy.loadError} ${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setLoading(false);
    }
  }, [copy.loadError, desktop]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const install = useCallback(async (entry: FieldAdapterCatalogEntry) => {
    if (!entry.packageSha256 || !entry.installable || !desktop) return;
    setBusyAdapterId(entry.adapterId);
    setError(null);
    try {
      await installFieldAdapter({
        adapterId: entry.adapterId,
        expectedPackageSha256: entry.packageSha256,
      });
      setCatalog(await getFieldAdapterCatalog());
    } catch (reason) {
      setError(`${copy.installError} ${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setBusyAdapterId(null);
    }
  }, [copy.installError, desktop]);

  const installedCount = useMemo(
    () => catalog.entries.filter((entry) => entry.installed).length,
    [catalog.entries],
  );

  const capabilityLabel = (capability: FieldAdapterCatalogEntry["capabilities"]["telemetryRead"]) => ({
    "read-only": copy.readOnly,
    "quorum-required": copy.quorumRequired,
    unavailable: copy.unavailable,
    "vendor-controlled": copy.vendorControlled,
  })[capability];

  const availability = (entry: FieldAdapterCatalogEntry) => {
    if (entry.installed) return copy.installed;
    return {
      available: copy.available,
      "vendor-access-required": copy.vendorAccess,
      "platform-bridge-required": copy.platformBridge,
      planned: copy.planned,
    }[entry.implementationStatus];
  };

  return (
    <section
      id="adapters"
      className="field-section field-adapter-center"
      aria-labelledby="field-adapter-title"
      data-authority="false"
      data-executable-extension-loading="false"
    >
      <header>
        <div>
          <h2 id="field-adapter-title">{copy.title}</h2>
          <p>{copy.body}</p>
        </div>
        <PackageOpen aria-hidden="true" />
      </header>

      <div className="field-adapter-summary">
        <span><ShieldCheck aria-hidden="true" />{copy.verified} {catalog.catalogVersion}</span>
        <strong>{installedCount} / {catalog.entries.length}</strong>
        <button
          type="button"
          aria-label={copy.refresh}
          title={copy.refresh}
          disabled={!desktop || loading || busyAdapterId !== null}
          onClick={() => void loadCatalog()}
        >
          <RefreshCw className={loading ? "field-auth-spinner" : undefined} aria-hidden="true" />
        </button>
      </div>

      {!desktop ? (
        <p className="field-adapter-offline"><WifiOff aria-hidden="true" />{copy.offline}</p>
      ) : null}
      {error ? <p className="field-adapter-error" role="alert">{error}</p> : null}

      <div className="field-table-scroll">
        <table className="field-adapter-table" aria-label={copy.title}>
          <thead>
            <tr>
              <th>{copy.protocol}</th>
              <th>{copy.transports}</th>
              <th>{copy.telemetry}</th>
              <th>{copy.parameters}</th>
              <th>{copy.delivery}</th>
              <th><span className="sr-only">{copy.install}</span></th>
            </tr>
          </thead>
          <tbody>
            {catalog.entries.map((entry) => {
              const busy = busyAdapterId === entry.adapterId;
              return (
                <tr key={entry.adapterId}>
                  <td>
                    <strong>{entry.displayName[locale]}</strong>
                    <small>{entry.vendor} · {entry.protocolFamily}</small>
                  </td>
                  <td>{entry.supportedTransports.join(", ")}</td>
                  <td>{capabilityLabel(entry.capabilities.telemetryRead)}</td>
                  <td>{capabilityLabel(entry.capabilities.parameterRead)}</td>
                  <td>
                    <span className="field-adapter-state" data-state={entry.implementationStatus}>
                      {entry.installed ? <Check aria-hidden="true" /> : <LockKeyhole aria-hidden="true" />}
                      {availability(entry)}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="field-adapter-install"
                      disabled={!desktop || busy || entry.installed || !entry.installable}
                      onClick={() => void install(entry)}
                    >
                      {entry.installed
                        ? <Check aria-hidden="true" />
                        : entry.installable
                          ? <Download aria-hidden="true" />
                          : <CircleOff aria-hidden="true" />}
                      {busy ? copy.installing : entry.installed ? copy.installed : copy.install}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="field-adapter-boundary"><LockKeyhole aria-hidden="true" />{copy.boundary}</p>
    </section>
  );
}
