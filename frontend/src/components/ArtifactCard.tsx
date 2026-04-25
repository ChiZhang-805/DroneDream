import { useState } from "react";

import { artifactDownloadUrl } from "../api/client";
import type { Artifact } from "../types/api";

interface ArtifactCardProps {
  artifact: Artifact;
}

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
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const label = artifact.display_name ?? artifact.artifact_type;
  const fileName = basename(artifact.storage_path);
  const isPdf =
    artifact.artifact_type === "pdf_report" ||
    artifact.mime_type === "application/pdf";

  const handleCopy = async () => {
    try {
      const ok = await copyToClipboard(artifact.storage_path);
      setCopyState(ok ? "copied" : "failed");
    } catch {
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 1500);
  };

  return (
    <article className="artifact-card" data-testid="artifact-card">
      <header className="artifact-card-header">
        <div className="artifact-card-title">{label}</div>
        <button
          type="button"
          className="btn btn-ghost artifact-copy-btn"
          onClick={handleCopy}
        >
          Copy path
        </button>
        {isPdf ? (
          <a
            className="btn"
            href={artifactDownloadUrl(artifact.id)}
            download
          >
            Download PDF
          </a>
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
        {artifact.file_size_bytes !== null ? <span>{artifact.file_size_bytes} bytes</span> : null}
        {copyState === "copied" ? <span className="artifact-copy-ok">Copied</span> : null}
        {copyState === "failed" ? <span className="artifact-copy-fail">Copy unavailable</span> : null}
      </div>
    </article>
  );
}
