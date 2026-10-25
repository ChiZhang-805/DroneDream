import { useEffect, useRef, useState } from "react";
import { Box, Check, CircleDashed, FolderOpen, LoaderCircle, MapPin, Route, Upload, X } from "lucide-react";
import type { BrandEditionId } from "../../brand/edition-brand.generated";
import { AssetInterpretButton } from "./AssetInterpretButton";
import {
  createMapUploadImport, getAgentCoreBootstrap, pickMapUpload, processAgentCoreAssetImportJob,
  type AgentCoreAssetVersion, type MapUploadReceipt, type MapUploadRole,
} from "./agentCore";

const slots = [
  { role: "scene", icon: Box, zh: "地图场景", en: "Map scene" },
  { role: "resources", icon: FolderOpen, zh: "模型与贴图", en: "Models & textures" },
  { role: "places", icon: MapPin, zh: "地点与出入口", en: "Places & entrances" },
  { role: "routes", icon: Route, zh: "通行网络", en: "Navigation network" },
] as const;

function mapUploadRoles(scene?: MapUploadReceipt): MapUploadRole[] {
  if (/\.(ddpkg|zip)$/iu.test(scene?.name ?? "")) return ["scene"];
  if (/\.yaml$/iu.test(scene?.name ?? "")) return ["scene", "resources"];
  return ["scene", "resources", "places", "routes"];
}

export function MapImportDialog({ open, chinese, edition, onClose, onImported }: {
  open: boolean; chinese: boolean; edition: BrandEditionId; onClose: () => void;
  onImported: (version: AgentCoreAssetVersion) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [uploads, setUploads] = useState<Partial<Record<MapUploadRole, MapUploadReceipt>>>({});
  const [busy, setBusy] = useState<MapUploadRole | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState<AgentCoreAssetVersion | null>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);
  const visibleRoles = mapUploadRoles(uploads.scene);
  const upload = async (role: MapUploadRole) => {
    setBusy(role);
    setError(null);
    try {
      const result = await pickMapUpload(role, chinese);
      if (result) {
        setUploads((current) => role === "scene" ? { scene: result } : { ...current, [role]: result });
        setVersion(null);
      }
    } catch {
      setError(chinese ? "上传失败" : "Upload failed");
    } finally { setBusy(null); }
  };
  const finish = async () => {
    setBusy("import");
    setError(null);
    try {
      const created = await createMapUploadImport(visibleRoles.flatMap((role) => uploads[role] ? [uploads[role]!] : []));
      const job = await processAgentCoreAssetImportJob(created.job_id);
      const hash = job.qualified_content_sha256 ?? job.normalized_content_sha256;
      const bootstrap = await getAgentCoreBootstrap();
      const imported = bootstrap.asset_versions.find((item) => item.asset_id === job.asset_id && item.content_sha256 === hash);
      if (!imported) throw new Error("MAP_IMPORT_INCOMPLETE");
      onImported(imported);
      setVersion(imported);
    } catch { setError(chinese ? "导入失败" : "Import failed"); }
    finally { setBusy(null); }
  };
  return <dialog ref={dialog} className="map-import-dialog" aria-labelledby="map-import-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id="map-import-title"><Upload aria-hidden="true" />{chinese ? "导入地图" : "Import map"}</h2>
      <button type="button" className="map-import-icon" aria-label={chinese ? "关闭" : "Close"} disabled={Boolean(busy)} onClick={onClose}><X aria-hidden="true" /></button>
    </header>
    <div className="map-import-slots">{slots.filter((slot) => visibleRoles.includes(slot.role)).map((slot) => {
      const receipt = uploads[slot.role];
      const label = chinese ? slot.zh : slot.en;
      return <div className="map-import-slot" key={slot.role}>
        <slot.icon aria-hidden="true" />
        <div className="map-import-file"><strong>{label}</strong>{receipt && <span title={receipt.name}>{receipt.name}</span>}</div>
        <span className="map-import-status" data-state={busy === slot.role ? "busy" : receipt ? "uploaded" : "waiting"}
          role="status" aria-label={`${label} · ${busy === slot.role ? (chinese ? "上传中" : "Uploading") : receipt ? (chinese ? "已上传" : "Uploaded") : (chinese ? "等待" : "Waiting")}`}>
          {busy === slot.role ? <LoaderCircle aria-hidden="true" /> : receipt ? <Check aria-hidden="true" /> : <CircleDashed aria-hidden="true" />}
        </span>
        <button type="button" className="map-import-icon" disabled={Boolean(busy) || (slot.role !== "scene" && !uploads.scene)}
          aria-label={`${chinese ? "上传" : "Upload"} ${label}`} title={`${chinese ? "上传" : "Upload"} ${label}`} onClick={() => void upload(slot.role)}><Upload aria-hidden="true" /></button>
      </div>;
    })}</div>
    {error && <span className="map-import-error" role="alert">{error}</span>}
    <footer>
      {version && <div className="map-import-ai"><span>{chinese ? "AI 解析 · 额度" : "AI analysis · credits"}</span>
        <AssetInterpretButton edition={edition} chinese={chinese} kind="map" assetId={version.asset_id} contentSha256={version.content_sha256} name={String(version.asset_ir?.name ?? version.asset_id)} />
      </div>}
      <button type="button" className="btn btn-primary" disabled={Boolean(busy) || !uploads.scene}
        onClick={() => version ? onClose() : void finish()}>
        {busy === "import" ? <LoaderCircle className="map-import-spin" aria-hidden="true" /> : <Check aria-hidden="true" />}
        {version ? (chinese ? "完成" : "Done") : (chinese ? "导入" : "Import")}
      </button>
    </footer>
  </dialog>;
}
