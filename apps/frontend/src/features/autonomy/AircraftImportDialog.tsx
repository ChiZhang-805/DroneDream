import { useEffect, useRef, useState } from "react";
import { Box, Check, CircleDashed, FolderOpen, LoaderCircle, Upload, X } from "lucide-react";
import {
  getAgentCoreBootstrap, pickAndCreateAgentCoreAssetImportJob, processAgentCoreAssetImportJob,
  type AgentCoreAssetImportJob, type AgentCoreAssetSourceAdapter, type AgentCoreAssetVersion,
} from "./agentCore";

export function AircraftImportDialog({ open, chinese, adapters, onClose, onImported }: {
  open: boolean; chinese: boolean; adapters: AgentCoreAssetSourceAdapter[];
  onClose: () => void; onImported: (version: AgentCoreAssetVersion) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [job, setJob] = useState<AgentCoreAssetImportJob | null>(null);
  const [source, setSource] = useState<"file" | "directory" | null>(null);
  const [busy, setBusy] = useState<"file" | "directory" | "import" | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);
  const upload = async (kind: "file" | "directory") => {
    setBusy(kind); setError(null);
    try {
      const received = await pickAndCreateAgentCoreAssetImportJob("vehicle", kind, chinese ? "zh-CN" : "en-US", adapters);
      if (received) { setJob(received); setSource(kind); setDone(false); }
    } catch { setError(chinese ? "上传失败" : "Upload failed"); }
    finally { setBusy(null); }
  };
  const finish = async () => {
    if (!job) return;
    setBusy("import"); setError(null);
    try {
      const processed = await processAgentCoreAssetImportJob(job.job_id);
      setJob(processed);
      const hash = processed.qualified_content_sha256 ?? processed.normalized_content_sha256;
      const bootstrap = await getAgentCoreBootstrap();
      const version = bootstrap.asset_versions.find((item) => item.asset_id === processed.asset_id && item.content_sha256 === hash);
      if (version) { onImported(version); setDone(true); }
      else setError(processed.state === "needs_input"
        ? (chinese ? "资产包缺少依赖或需要转换" : "Package needs dependencies or conversion")
        : (chinese ? "导入失败" : "Import failed"));
    } catch { setError(chinese ? "导入失败" : "Import failed"); }
    finally { setBusy(null); }
  };
  return <dialog ref={dialog} className="map-import-dialog aircraft-import-dialog" aria-labelledby="aircraft-import-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id="aircraft-import-title"><Upload aria-hidden="true" />{chinese ? "导入无人机" : "Import aircraft"}</h2>
      <button className="map-import-icon" type="button" aria-label={chinese ? "关闭" : "Close"} disabled={Boolean(busy)} onClick={onClose}><X aria-hidden="true" /></button></header>
    {(["file", "directory"] as const).map((kind) => {
      const Icon = kind === "file" ? Box : FolderOpen;
      const label = kind === "file" ? (chinese ? "无人机资产包" : "Aircraft package") : (chinese ? "模型与依赖文件夹" : "Model & dependencies folder");
      const received = source === kind && job;
      return <div className="map-import-slot" key={kind}>
        <Icon aria-hidden="true" /><div className="map-import-file"><strong>{label}</strong>{received && <span title={job.source_name}>{job.source_name}</span>}</div>
        <span className="map-import-status" data-state={busy === kind ? "busy" : received ? "uploaded" : "waiting"} role="status" aria-label={`${label} · ${received ? (chinese ? "已上传" : "Uploaded") : (chinese ? "等待" : "Waiting")}`}>
          {busy === kind ? <LoaderCircle aria-hidden="true" /> : received ? <Check aria-hidden="true" /> : <CircleDashed aria-hidden="true" />}</span>
        <button type="button" className="map-import-icon" disabled={Boolean(busy)} aria-label={`${chinese ? "上传" : "Upload"} ${label}`} onClick={() => void upload(kind)}><Upload aria-hidden="true" /></button>
      </div>;
    })}
    {error && <span className="map-import-error" role="alert">{error}</span>}
    <footer><button type="button" className="btn btn-primary" disabled={Boolean(busy) || !job} onClick={() => done ? onClose() : void finish()}>
      {busy === "import" ? <LoaderCircle className="map-import-spin" aria-hidden="true" /> : <Check aria-hidden="true" />}{done ? (chinese ? "完成" : "Done") : (chinese ? "导入" : "Import")}
    </button></footer>
  </dialog>;
}
