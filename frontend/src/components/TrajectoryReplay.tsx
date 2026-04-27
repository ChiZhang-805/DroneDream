import { useEffect, useMemo, useState } from "react";

import { apiClient, ApiClientError } from "../api/client";
import { SectionCard } from "./SectionCard";
import { Alert } from "./Alert";
import { Loading, Empty } from "./States";
import type { ReplayArtifacts } from "./trajectoryReplayUtils";

interface ReplayPoint {
  t: number;
  x: number;
  y: number;
  z: number;
}

interface ReplayMeta {
  scenario?: string;
  candidate_id?: string;
}

interface TrajectoryReplayProps {
  title?: string;
  artifacts: ReplayArtifacts;
  meta: ReplayMeta;
}

const SPEEDS = [0.5, 1, 2, 4] as const;

function normalizePoint(raw: unknown, idx: number): ReplayPoint | null {
  if (!raw || typeof raw !== "object") return null;
  const sample = raw as Record<string, unknown>;
  const x = Number(sample.x);
  const y = Number(sample.y);
  const z = Number(sample.z ?? 0);
  const t = Number(sample.t ?? idx);
  if (![x, y, z, t].every(Number.isFinite)) return null;
  return { x, y, z, t };
}

function extractPoints(payload: unknown): ReplayPoint[] {
  if (!payload || typeof payload !== "object") return [];
  const root = payload as Record<string, unknown>;
  const candidates: unknown[] = [
    root.samples,
    root.points,
    root.trajectory,
    root.path,
    root.reference_track,
  ];
  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) continue;
    const parsed = candidate
      .map((item, idx) => normalizePoint(item, idx))
      .filter((item): item is ReplayPoint => item !== null);
    if (parsed.length > 0) return parsed;
  }
  return [];
}

function extractReferencePoints(payload: unknown): ReplayPoint[] {
  if (!payload || typeof payload !== "object") return [];
  const root = payload as Record<string, unknown>;
  if (!Array.isArray(root.reference_track)) return [];
  return root.reference_track
    .map((item, idx) => normalizePoint(item, idx))
    .filter((item): item is ReplayPoint => item !== null);
}

function toViewBoxCoordinates(points: ReplayPoint[]): {
  linePoints: string;
  markerX: (idx: number) => number;
  markerY: (idx: number) => number;
} {
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  const pad = 8;

  const mapX = (x: number) => ((x - minX) / width) * (100 - pad * 2) + pad;
  const mapY = (y: number) => 100 - (((y - minY) / height) * (100 - pad * 2) + pad);

  return {
    linePoints: points.map((p) => `${mapX(p.x)},${mapY(p.y)}`).join(" "),
    markerX: (idx: number) => mapX(points[idx]?.x ?? points[0].x),
    markerY: (idx: number) => mapY(points[idx]?.y ?? points[0].y),
  };
}

function statusTextForError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return `${error.message} (${error.code})`;
  }
  if (error instanceof Error) return error.message;
  return "Unable to load trajectory JSON artifact.";
}

export function TrajectoryReplay({
  title = "Trajectory replay",
  artifacts,
  meta,
}: TrajectoryReplayProps) {
  const [actualPoints, setActualPoints] = useState<ReplayPoint[] | null>(null);
  const [referencePoints, setReferencePoints] = useState<ReplayPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);
  const [position, setPosition] = useState(0);

  const primaryArtifact = artifacts.trajectory ?? artifacts.telemetry;

  useEffect(() => {
    let cancelled = false;

    async function loadReplayData() {
      setError(null);
      setIsPlaying(false);
      setPosition(0);
      setActualPoints(null);
      setReferencePoints([]);

      if (!primaryArtifact) {
        setActualPoints([]);
        return;
      }

      try {
        const primary = await apiClient.fetchArtifactJson<unknown>(primaryArtifact.id);
        const primaryPoints = extractPoints(primary);
        if (!cancelled) {
          setActualPoints(primaryPoints);
          const embeddedReference = extractReferencePoints(primary);
          if (embeddedReference.length > 0) {
            setReferencePoints(embeddedReference);
          }
        }

        if (artifacts.reference) {
          const referencePayload = await apiClient.fetchArtifactJson<unknown>(
            artifacts.reference.id,
          );
          if (!cancelled) {
            setReferencePoints(extractPoints(referencePayload));
          }
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(statusTextForError(loadError));
          setActualPoints([]);
        }
      }
    }

    void loadReplayData();

    return () => {
      cancelled = true;
    };
  }, [artifacts.reference, primaryArtifact]);

  useEffect(() => {
    if (!isPlaying || !actualPoints || actualPoints.length <= 1) {
      return;
    }
    const timer = window.setInterval(() => {
      setPosition((prev) => {
        const next = prev + Math.max(1, Math.round(speed));
        if (next >= actualPoints.length - 1) {
          setIsPlaying(false);
          return actualPoints.length - 1;
        }
        return next;
      });
    }, Math.max(40, 220 / speed));

    return () => window.clearInterval(timer);
  }, [actualPoints, isPlaying, speed]);

  const primaryLabel = primaryArtifact?.display_name ?? primaryArtifact?.artifact_type;

  const viewModel = useMemo(() => {
    if (!actualPoints || actualPoints.length === 0) return null;
    const actual = toViewBoxCoordinates(actualPoints);
    const reference =
      referencePoints.length > 0 ? toViewBoxCoordinates(referencePoints) : null;
    return { actual, reference };
  }, [actualPoints, referencePoints]);

  const current = actualPoints?.[position] ?? null;

  return (
    <SectionCard
      title={title}
      description={
        primaryLabel
          ? `Source: ${primaryLabel}${artifacts.reference ? " (+ reference track)" : ""}`
          : "Render trajectory/telemetry JSON artifacts in-browser."
      }
    >
      {!primaryArtifact ? (
        <Empty
          title="Replay unavailable"
          description="No trajectory.json or telemetry.json artifact was found for this trial."
        />
      ) : actualPoints === null ? (
        <Loading label="Loading trajectory replay…" />
      ) : error ? (
        <Alert tone="danger" title="Replay failed">
          {error}
        </Alert>
      ) : !viewModel ? (
        <Empty
          title="Replay data missing"
          description="The selected artifact did not contain valid samples[] / points[] data."
        />
      ) : (
        <div className="stack-sm" data-testid="trajectory-replay">
          <div className="trajectory-replay-canvas-wrap">
            <svg
              className="trajectory-replay-canvas"
              viewBox="0 0 100 100"
              role="img"
              aria-label="Trajectory replay"
            >
              <rect x="0" y="0" width="100" height="100" fill="rgba(255,255,255,0.02)" />
              {viewModel.reference ? (
                <polyline
                  points={viewModel.reference.linePoints}
                  fill="none"
                  stroke="rgba(111, 188, 255, 0.8)"
                  strokeWidth="1.2"
                  strokeDasharray="2 2"
                />
              ) : null}
              <polyline
                points={viewModel.actual.linePoints}
                fill="none"
                stroke="#5b8dff"
                strokeWidth="1.5"
              />
              <circle
                cx={viewModel.actual.markerX(position)}
                cy={viewModel.actual.markerY(position)}
                r="1.8"
                fill="#3ecf8e"
              />
            </svg>
          </div>

          <div className="trajectory-controls">
            <button
              type="button"
              className="btn"
              onClick={() => setIsPlaying((p) => !p)}
              disabled={actualPoints.length <= 1}
            >
              {isPlaying ? "Pause" : "Play"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setPosition(0);
                setIsPlaying(false);
              }}
            >
              Reset
            </button>
            <label className="trajectory-speed">
              Speed
              <select
                value={String(speed)}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                {SPEEDS.map((value) => (
                  <option key={value} value={value}>
                    {value}x
                  </option>
                ))}
              </select>
            </label>
          </div>

          <input
            type="range"
            min={0}
            max={Math.max(0, actualPoints.length - 1)}
            value={position}
            onChange={(e) => {
              setIsPlaying(false);
              setPosition(Number(e.target.value));
            }}
          />

          <ul className="kv-list">
            <li>
              <span className="kv-key">t</span>
              <span className="kv-value">{current?.t.toFixed(2) ?? "—"} s</span>
            </li>
            <li>
              <span className="kv-key">x / y / z</span>
              <span className="kv-value">
                {current
                  ? `${current.x.toFixed(2)} / ${current.y.toFixed(2)} / ${current.z.toFixed(2)}`
                  : "—"}
              </span>
            </li>
            <li>
              <span className="kv-key">Scenario</span>
              <span className="kv-value">{meta.scenario ?? "—"}</span>
            </li>
            <li>
              <span className="kv-key">Candidate</span>
              <span className="kv-value">
                {meta.candidate_id ? <code>{meta.candidate_id}</code> : "—"}
              </span>
            </li>
          </ul>
        </div>
      )}
    </SectionCard>
  );
}
