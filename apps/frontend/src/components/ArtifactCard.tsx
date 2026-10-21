import { useEffect, useRef, useState } from "react";

import { apiClient } from "../api/client";
import { useI18n } from "../i18n/I18nProvider";
import type { Artifact } from "../types/api";

interface ArtifactCardProps {
  artifact: Artifact;
}

// Reading an artifact through the download endpoint transfers the complete
// object. Only inspect bounded metadata-sized JSON automatically; telemetry
// payloads remain an explicit user download/replay action.
const MAX_SCHEMA_PREFETCH_BYTES = 64 * 1024;

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.at(-1) ?? path;
}

async function copyToClipboard(value: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return true;
  }
  if (typeof document === "undefined") return false;

  const input = document.createElement("textarea");
  input.value = value;
  input.setAttribute("readonly", "true");
  input.style.position = "fixed";
  input.style.left = "-9999px";
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(input);
  return copied;
}

export function ArtifactCard({ artifact }: ArtifactCardProps) {
  const { t } = useI18n();
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [downloadState, setDownloadState] = useState<"idle" | "downloading" | "failed">("idle");
  const [schemaVersion, setSchemaVersion] = useState<string | null>(null);
  const feedbackTimer = useRef<number | null>(null);
  const label = artifact.display_name ?? artifact.artifact_type;
  const fileName = basename(artifact.storage_path);
  const isPdf =
    artifact.artifact_type === "pdf_report" ||
    artifact.mime_type === "application/pdf";
  const isDownloadable = !artifact.storage_path.startsWith("mock://");

  const handleCopy = async () => {
    try {
      const ok = await copyToClipboard(artifact.storage_path);
      setCopyState(ok ? "copied" : "failed");
    } catch {
      setCopyState("failed");
    }
    if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current);
    feedbackTimer.current = window.setTimeout(() => {
      setCopyState("idle");
      feedbackTimer.current = null;
    }, 1500);
  };

  const handleDownload = async () => {
    setDownloadState("downloading");
    try {
      await apiClient.downloadArtifact(artifact.id, fileName);
      setDownloadState("idle");
    } catch {
      setDownloadState("failed");
    }
  };

  useEffect(() => () => {
    if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSchemaVersion(null);
    const isJson =
      artifact.mime_type === "application/json" ||
      artifact.storage_path.toLowerCase().endsWith(".json");
    const isBoundedMetadata = artifact.file_size_bytes !== null
      && artifact.file_size_bytes <= MAX_SCHEMA_PREFETCH_BYTES;
    if (!isJson || !isDownloadable || !isBoundedMetadata) return;
    void apiClient
      .fetchArtifactJson<Record<string, unknown>>(artifact.id)
      .then((payload) => {
        const value = payload?.schema_version;
        if (!cancelled && typeof value === "string" && value.length > 0) {
          setSchemaVersion(value);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [
    artifact.file_size_bytes,
    artifact.id,
    artifact.mime_type,
    artifact.storage_path,
    isDownloadable,
  ]);

  return (
    <article className="artifact-card" data-testid="artifact-card">
      <header className="artifact-card-header">
        <div className="artifact-card-title">{label}</div>
        <button
          type="button"
          className="btn btn-ghost artifact-copy-btn"
          onClick={handleCopy}
        >
          {t("artifact.copyPath")}
        </button>
        {isDownloadable ? (
          <button
            type="button"
            className="btn"
            onClick={() => void handleDownload()}
            disabled={downloadState === "downloading"}
          >
            {downloadState === "downloading"
              ? t("artifact.downloading")
              : t(isPdf ? "artifact.downloadPdf" : "artifact.download")}
          </button>
        ) : null}
      </header>

      <div className="artifact-file" title={artifact.storage_path}>
        <code>{fileName}</code>
      </div>

      <div className="artifact-path" title={artifact.storage_path}>
        {artifact.storage_path}
      </div>

      <div className="artifact-meta">
        {artifact.mime_type ? <span>{artifact.mime_type}</span> : null}
        {artifact.file_size_bytes !== null ? (
          <span>{t("artifact.bytes", { count: artifact.file_size_bytes })}</span>
        ) : null}
        {schemaVersion ? <span>{t("artifact.schema", { version: schemaVersion })}</span> : null}
        {copyState === "copied" ? (
          <span className="artifact-copy-ok" role="status">{t("artifact.copied")}</span>
        ) : null}
        {copyState === "failed" ? (
          <span className="artifact-copy-fail" role="alert">{t("artifact.copyUnavailable")}</span>
        ) : null}
        {downloadState === "failed" ? (
          <span className="artifact-copy-fail" role="alert">{t("artifact.downloadFailed")}</span>
        ) : null}
      </div>
    </article>
  );
}
