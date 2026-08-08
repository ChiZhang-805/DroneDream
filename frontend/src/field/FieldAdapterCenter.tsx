import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleOff,
  Download,
  FileSearch,
  LockKeyhole,
  PackageOpen,
  RadioReceiver,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

import sourceCatalog from "../../../distribution/editions/field/adapters/catalog.v1.json";
import {
  getFieldAdapterCatalog,
  inspectFieldProtocolFrame,
  installFieldAdapter,
  isDesktopRuntime,
  probeFieldMavlinkTelemetry,
  type FieldAdapterCatalogEntry,
  type FieldAdapterCatalogReport,
  type FieldDiscoveredDevice,
  type FieldMavlinkTelemetryProbeReceipt,
  type FieldProtocolFrameInspection,
} from "../desktop/bridge";
import type { FieldLocale } from "./catalog";
import { hardwareDomainEdition } from "./hardwareDomain";

const CATALOG_SHA256 = "5b1a7b9f5bd64624b6d4af7b0745e1ba4b1babca63fab0ba765ca97e58ac9419";

const COPY = {
  en: {
    title: "Protocol adapters",
    body: "Enable source-bound open-protocol frame inspection and bounded read-only serial telemetry without adding proprietary SDKs to the base app.",
    refresh: "Refresh adapter state",
    offline: "Native adapter installation is available in the installed Field app.",
    loadError: "The native adapter catalog could not be verified.",
    installError: "Adapter installation was rejected.",
    boundary: "Managed open-protocol packages support offline inspection; MAVLink also supports one bounded, operator-confirmed read-only serial probe. Continuous sessions, radio, TCP, UDP, parameter access, and control remain disabled. Every hardware action still requires Vehicle Pack validation and the full native safety quorum.",
    protocol: "Protocol",
    transports: "Protocol transports",
    telemetry: "Telemetry",
    parameters: "Parameters",
    delivery: "Availability",
    install: "Install",
    installAll: "Install all open adapters",
    installing: "Installing",
    installingAll: "Installing open adapters",
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
    telemetryTitle: "Read-only MAVLink telemetry",
    telemetryDevice: "Observed port",
    telemetryAdapter: "Installed adapter",
    telemetryBaud: "Baud rate",
    telemetryConfirm: "Open the selected serial port for one read-only frame. No parameter, control, arm, or flight command will be sent.",
    telemetryProbe: "Read one frame",
    telemetryBusy: "Reading...",
    telemetryUnavailable: "Scan the serial registry and install a MAVLink adapter first.",
    telemetryError: "The read-only telemetry probe was rejected.",
    telemetryResult: "Received",
    inspectorTitle: "Offline protocol frame inspector",
    inspectorAdapter: "Installed adapter",
    inspectorFrame: "Captured frame (canonical base64)",
    inspectorPlaceholder: "Paste one captured protocol frame",
    inspectorAction: "Inspect frame",
    inspectorBusy: "Inspecting...",
    inspectorUnavailable: "Install an open protocol package to inspect captured frames.",
    inspectorError: "The offline frame was rejected.",
    inspectorResult: "Classified",
  },
  "zh-CN": {
    title: "协议适配器",
    body: "在不把专有 SDK 塞入基础应用的前提下，启用源绑定开放协议帧检查和有时间上限的只读串口遥测。",
    refresh: "刷新适配器状态",
    offline: "原生适配器安装仅在已安装的 Field 应用中可用。",
    loadError: "无法验证原生适配器目录。",
    installError: "适配器安装被拒绝。",
    boundary: "受管开放协议适配包支持离线检查；MAVLink 还支持一次有时间上限、经操作员确认的只读串口探测。连续会话、无线电、TCP、UDP、参数访问和控制仍处于禁用状态；任何真机动作仍必须通过机型包验证和完整原生安全仲裁。",
    protocol: "协议",
    transports: "协议可用传输方式",
    telemetry: "遥测",
    parameters: "参数",
    delivery: "可用状态",
    install: "安装",
    installAll: "安装全部开放协议适配器",
    installing: "正在安装",
    installingAll: "正在安装开放协议适配器",
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
    telemetryTitle: "只读 MAVLink 遥测",
    telemetryDevice: "已观察端口",
    telemetryAdapter: "已安装适配器",
    telemetryBaud: "波特率",
    telemetryConfirm: "仅为读取一个只读帧而打开所选串口，不发送参数、控制、解锁或飞行命令。",
    telemetryProbe: "读取一帧",
    telemetryBusy: "读取中...",
    telemetryUnavailable: "请先扫描串口注册表并安装一个 MAVLink 适配器。",
    telemetryError: "只读遥测探测被拒绝。",
    telemetryResult: "已接收",
    inspectorTitle: "离线协议帧检查器",
    inspectorAdapter: "已安装适配器",
    inspectorFrame: "已捕获帧（规范 base64）",
    inspectorPlaceholder: "粘贴一个已捕获的协议帧",
    inspectorAction: "检查帧",
    inspectorBusy: "正在检查...",
    inspectorUnavailable: "请先安装一个开放协议适配包。",
    inspectorError: "离线帧被拒绝。",
    inspectorResult: "已分类",
  },
} as const;

function staticCatalog(): FieldAdapterCatalogReport {
  return {
    schemaVersion: 1,
    kind: "dronedream-field-adapter-catalog-report",
    catalogVersion: sourceCatalog.catalogVersion,
    editionId: hardwareDomainEdition,
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
  devices?: FieldDiscoveredDevice[];
  onReadOnlyEvidence?: (evidence: FieldReadOnlyProtocolEvidence) => void;
}

export interface FieldReadOnlyProtocolEvidence {
  adapterId: string;
  observationSha256: string;
  deviceObservationId: string;
}

export function FieldAdapterCenter({
  locale,
  devices = [],
  onReadOnlyEvidence,
}: FieldAdapterCenterProps) {
  const copy = COPY[locale];
  const [catalog, setCatalog] = useState<FieldAdapterCatalogReport>(staticCatalog);
  const [busyAdapterId, setBusyAdapterId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedObservationId, setSelectedObservationId] = useState("");
  const [selectedTelemetryAdapterId, setSelectedTelemetryAdapterId] = useState("");
  const [baudRate, setBaudRate] = useState(115_200);
  const [readOnlyConfirmed, setReadOnlyConfirmed] = useState(false);
  const [telemetryBusy, setTelemetryBusy] = useState(false);
  const [telemetryError, setTelemetryError] = useState<string | null>(null);
  const [telemetryResult, setTelemetryResult] =
    useState<FieldMavlinkTelemetryProbeReceipt | null>(null);
  const [selectedInspectorAdapterId, setSelectedInspectorAdapterId] = useState("");
  const [frameBase64, setFrameBase64] = useState("");
  const [inspectorBusy, setInspectorBusy] = useState(false);
  const [inspectorError, setInspectorError] = useState<string | null>(null);
  const [inspectorResult, setInspectorResult] =
    useState<FieldProtocolFrameInspection | null>(null);
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
  const pendingManagedAdapters = useMemo(
    () => catalog.entries.filter((entry) => (
      entry.installable
      && !entry.installed
      && entry.deliveryMode === "embedded-managed"
      && entry.packageSha256 !== null
    )),
    [catalog.entries],
  );
  const installAll = useCallback(async () => {
    if (!desktop || busyAdapterId !== null || pendingManagedAdapters.length === 0) return;
    setBusyAdapterId("all");
    setError(null);
    try {
      for (const entry of pendingManagedAdapters) {
        if (!entry.packageSha256) {
          throw new Error("Managed adapter package hash is missing.");
        }
        await installFieldAdapter({
          adapterId: entry.adapterId,
          expectedPackageSha256: entry.packageSha256,
        });
      }
      setCatalog(await getFieldAdapterCatalog());
    } catch (reason) {
      setError(`${copy.installError} ${reason instanceof Error ? reason.message : String(reason)}`);
      try {
        setCatalog(await getFieldAdapterCatalog());
      } catch {
        // Preserve the installation failure as the primary diagnostic.
      }
    } finally {
      setBusyAdapterId(null);
    }
  }, [busyAdapterId, copy.installError, desktop, pendingManagedAdapters]);
  const installedMavlinkAdapters = useMemo(
    () => catalog.entries.filter((entry) => (
      entry.installed
      && entry.packageSha256 !== null
      && entry.adapterId.startsWith("mavlink-")
    )),
    [catalog.entries],
  );
  const installedInspectableAdapters = useMemo(
    () => catalog.entries.filter((entry) => (
      entry.installed
      && entry.packageSha256 !== null
      && entry.deliveryMode === "embedded-managed"
    )),
    [catalog.entries],
  );
  const selectedDevice = devices.find(
    (device) => device.observationId === selectedObservationId,
  ) ?? devices[0] ?? null;
  const selectedTelemetryAdapter = installedMavlinkAdapters.find(
    (entry) => entry.adapterId === selectedTelemetryAdapterId,
  ) ?? installedMavlinkAdapters[0] ?? null;
  const selectedInspectorAdapter = installedInspectableAdapters.find(
    (entry) => entry.adapterId === selectedInspectorAdapterId,
  ) ?? installedInspectableAdapters[0] ?? null;

  const inspectOfflineFrame = useCallback(async () => {
    if (!desktop || !selectedInspectorAdapter || frameBase64.trim() === "") return;
    setInspectorBusy(true);
    setInspectorError(null);
    setInspectorResult(null);
    try {
      const result = await inspectFieldProtocolFrame({
        adapterId: selectedInspectorAdapter.adapterId,
        frameBase64: frameBase64.trim(),
      });
      setInspectorResult(result);
      onReadOnlyEvidence?.({
        adapterId: result.adapterId,
        observationSha256: result.frameSha256,
        deviceObservationId: `offline-frame:${result.frameSha256.slice(0, 32)}`,
      });
    } catch (reason) {
      setInspectorError(
        `${copy.inspectorError} ${reason instanceof Error ? reason.message : String(reason)}`,
      );
    } finally {
      setInspectorBusy(false);
    }
  }, [copy.inspectorError, desktop, frameBase64, onReadOnlyEvidence, selectedInspectorAdapter]);

  const probeTelemetry = useCallback(async () => {
    if (
      !desktop
      || !readOnlyConfirmed
      || !selectedDevice
      || !selectedTelemetryAdapter?.packageSha256
    ) return;
    setTelemetryBusy(true);
    setTelemetryError(null);
    setTelemetryResult(null);
    try {
      const result = await probeFieldMavlinkTelemetry({
        adapterId: selectedTelemetryAdapter.adapterId,
        expectedPackageSha256: selectedTelemetryAdapter.packageSha256,
        observationId: selectedDevice.observationId,
        portName: selectedDevice.portName,
        baudRate: baudRate as 57600 | 115200 | 230400 | 460800 | 921600,
        readDeadlineMs: 3_000,
        operatorConfirmedReadOnly: true,
      });
      setTelemetryResult(result);
      onReadOnlyEvidence?.({
        adapterId: result.adapterId,
        observationSha256: result.frameSha256,
        deviceObservationId: result.observationId,
      });
    } catch (reason) {
      setTelemetryError(
        `${copy.telemetryError} ${reason instanceof Error ? reason.message : String(reason)}`,
      );
    } finally {
      setTelemetryBusy(false);
      setReadOnlyConfirmed(false);
    }
  }, [
    baudRate,
    copy.telemetryError,
    desktop,
    onReadOnlyEvidence,
    readOnlyConfirmed,
    selectedDevice,
    selectedTelemetryAdapter,
  ]);

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
      <div className="field-adapter-actions">
        <button
          type="button"
          disabled={!desktop || busyAdapterId !== null || pendingManagedAdapters.length === 0}
          onClick={() => void installAll()}
        >
          <Download aria-hidden="true" />
          {busyAdapterId === "all" ? copy.installingAll : copy.installAll}
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
              const busy = busyAdapterId === entry.adapterId || busyAdapterId === "all";
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
                      disabled={
                        !desktop
                        || busyAdapterId !== null
                        || entry.installed
                        || !entry.installable
                      }
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

      <div
        className="field-protocol-inspector"
        data-authority="false"
        data-device-open-attempts="0"
        data-hardware-write-attempts="0"
      >
        <header>
          <FileSearch aria-hidden="true" />
          <h3>{copy.inspectorTitle}</h3>
        </header>
        <div className="field-inspector-controls">
          <label>
            <span>{copy.inspectorAdapter}</span>
            <select
              value={selectedInspectorAdapter?.adapterId ?? ""}
              disabled={!desktop || installedInspectableAdapters.length === 0 || inspectorBusy}
              onChange={(event) => setSelectedInspectorAdapterId(event.target.value)}
            >
              {installedInspectableAdapters.length === 0
                ? <option value="">{copy.unavailable}</option>
                : null}
              {installedInspectableAdapters.map((entry) => (
                <option key={entry.adapterId} value={entry.adapterId}>
                  {entry.displayName[locale]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{copy.inspectorFrame}</span>
            <textarea
              value={frameBase64}
              maxLength={512}
              rows={3}
              placeholder={copy.inspectorPlaceholder}
              disabled={!desktop || !selectedInspectorAdapter || inspectorBusy}
              onChange={(event) => setFrameBase64(event.target.value)}
            />
          </label>
        </div>
        <button
          type="button"
          className="field-primary-command"
          disabled={
            !desktop
            || !selectedInspectorAdapter
            || frameBase64.trim() === ""
            || inspectorBusy
          }
          onClick={() => void inspectOfflineFrame()}
        >
          <FileSearch aria-hidden="true" />
          {inspectorBusy ? copy.inspectorBusy : copy.inspectorAction}
        </button>
        {!selectedInspectorAdapter ? (
          <p className="field-adapter-offline">
            <WifiOff aria-hidden="true" />{copy.inspectorUnavailable}
          </p>
        ) : null}
        {inspectorError ? (
          <p className="field-adapter-error" role="alert">{inspectorError}</p>
        ) : null}
        {inspectorResult ? (
          <output className="field-inspector-result" aria-live="polite">
            <Check aria-hidden="true" />
            <strong>
              {copy.inspectorResult} {inspectorResult.protocolFamily}
              {" · "}{inspectorResult.classification}
            </strong>
            <dl>
              {Object.entries(inspectorResult.fields).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
              ))}
            </dl>
          </output>
        ) : null}
      </div>

      <div className="field-telemetry-probe" data-authority="false">
        <header>
          <RadioReceiver aria-hidden="true" />
          <h3>{copy.telemetryTitle}</h3>
        </header>
        <div className="field-telemetry-controls">
          <label>
            <span>{copy.telemetryDevice}</span>
            <select
              value={selectedDevice?.observationId ?? ""}
              disabled={!desktop || devices.length === 0 || telemetryBusy}
              onChange={(event) => setSelectedObservationId(event.target.value)}
            >
              {devices.length === 0 ? <option value="">{copy.unavailable}</option> : null}
              {devices.map((device) => (
                <option key={device.observationId} value={device.observationId}>
                  {device.portName}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{copy.telemetryAdapter}</span>
            <select
              value={selectedTelemetryAdapter?.adapterId ?? ""}
              disabled={!desktop || installedMavlinkAdapters.length === 0 || telemetryBusy}
              onChange={(event) => setSelectedTelemetryAdapterId(event.target.value)}
            >
              {installedMavlinkAdapters.length === 0
                ? <option value="">{copy.unavailable}</option>
                : null}
              {installedMavlinkAdapters.map((entry) => (
                <option key={entry.adapterId} value={entry.adapterId}>
                  {entry.displayName[locale]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{copy.telemetryBaud}</span>
            <select
              value={baudRate}
              disabled={!desktop || telemetryBusy}
              onChange={(event) => setBaudRate(Number(event.target.value))}
            >
              {[57_600, 115_200, 230_400, 460_800, 921_600].map((rate) => (
                <option key={rate} value={rate}>{rate.toLocaleString("en-US")}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="field-telemetry-confirmation">
          <input
            type="checkbox"
            checked={readOnlyConfirmed}
            disabled={
              !desktop
              || !selectedDevice
              || !selectedTelemetryAdapter
              || telemetryBusy
            }
            onChange={(event) => setReadOnlyConfirmed(event.target.checked)}
          />
          <span>{copy.telemetryConfirm}</span>
        </label>
        <button
          type="button"
          className="field-primary-command"
          disabled={
            !desktop
            || !readOnlyConfirmed
            || !selectedDevice
            || !selectedTelemetryAdapter
            || telemetryBusy
          }
          onClick={() => void probeTelemetry()}
        >
          <RadioReceiver aria-hidden="true" />
          {telemetryBusy ? copy.telemetryBusy : copy.telemetryProbe}
        </button>
        {!selectedDevice || !selectedTelemetryAdapter ? (
          <p className="field-adapter-offline"><WifiOff aria-hidden="true" />{copy.telemetryUnavailable}</p>
        ) : null}
        {telemetryError ? <p className="field-adapter-error" role="alert">{telemetryError}</p> : null}
        {telemetryResult ? (
          <output className="field-telemetry-result" aria-live="polite">
            <Check aria-hidden="true" />
            <strong>{copy.telemetryResult} {telemetryResult.messageName}</strong>
            <span>
              MAVLink {telemetryResult.protocolVersion} · system {telemetryResult.systemId}
              {" · "}component {telemetryResult.componentId}
            </span>
          </output>
        ) : null}
      </div>

      <p className="field-adapter-boundary"><LockKeyhole aria-hidden="true" />{copy.boundary}</p>
    </section>
  );
}
