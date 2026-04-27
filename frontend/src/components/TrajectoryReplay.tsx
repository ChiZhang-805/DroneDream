import { useEffect, useMemo, useState } from "react";

import { apiClient, ApiClientError } from "../api/client";
import { SectionCard } from "./SectionCard";
import { Alert } from "./Alert";
import { Loading, Empty } from "./States";
import type { ReplayArtifacts } from "./trajectoryReplayUtils";
import {
  extractPoints,
  extractReferencePoints,
  getCombinedBounds,
  to2DViewBoxCoordinates,
  to3DViewBoxCoordinates,
  type ReplayPoint,
} from "./trajectoryReplayMath";

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

type ReplayViewMode = "2d" | "3d";

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
  const [viewMode, setViewMode] = useState<ReplayViewMode>("2d");

  const primaryArtifact = artifacts.trajectory ?? artifacts.telemetry;

  useEffect(() => {
    let cancelled = false;

    async function loadReplayData() {
      setError(null);
      setIsPlaying(false);
      setPosition(0);
      setViewMode("2d");
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

    const bounds = getCombinedBounds([actualPoints, referencePoints]);
    const project =
      viewMode === "3d"
        ? (points: ReplayPoint[]) =>
            to3DViewBoxCoordinates(points, bounds ?? undefined)
        : (points: ReplayPoint[]) => to2DViewBoxCoordinates(points);

    const actual = project(actualPoints);
    const reference = referencePoints.length > 0 ? project(referencePoints) : null;
    return { actual, reference };
  }, [actualPoints, referencePoints, viewMode]);

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
          <div className="trajectory-controls">
            <label className="trajectory-speed">
              View
              <select
                aria-label="Replay view mode"
                value={viewMode}
                onChange={(event) => setViewMode(event.target.value as ReplayViewMode)}
              >
                <option value="2d">2D</option>
                <option value="3d">3D</option>
              </select>
            </label>
          </div>

          <div className="trajectory-replay-canvas-wrap">
            <svg
              className="trajectory-replay-canvas"
              viewBox="0 0 100 100"
              role="img"
              data-testid={`trajectory-replay-svg-${viewMode}`}
              aria-label={viewMode === "3d" ? "Trajectory replay 3D" : "Trajectory replay 2D"}
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
