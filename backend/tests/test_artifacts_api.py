from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from app import db, models


def _seed_job() -> str:
    with db.SessionLocal() as session:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
        )
        session.add(job)
        session.commit()
        return job.id


def test_download_pdf_artifact_success(client: TestClient, tmp_path: Path) -> None:
    job_id = _seed_job()
    root = tmp_path / "real_artifacts"
    path = root / "jobs" / job_id / "reports" / f"{job_id} report.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name=f"{job_id} report.pdf",
            storage_path=str(path),
            mime_type="application/pdf",
            file_size_bytes=path.stat().st_size,
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    content_disposition = resp.headers["content-disposition"]
    assert "attachment;" in content_disposition
    assert f"filename*=utf-8''{quote(f'{job_id} report.pdf')}" in content_disposition


def test_download_mock_artifact_rejected(client: TestClient) -> None:
    job_id = _seed_job()
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name=f"{job_id} report.pdf",
            storage_path=f"mock://jobs/{job_id}/reports/{job_id} report.pdf",
            mime_type="application/pdf",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 404


def test_download_missing_file_returns_404(client: TestClient, tmp_path: Path) -> None:
    job_id = _seed_job()
    missing_path = tmp_path / "real_artifacts" / "jobs" / job_id / "reports" / "missing.pdf"
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name=f"{job_id} report.pdf",
            storage_path=str(missing_path),
            mime_type="application/pdf",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 404


def test_download_forbidden_outside_root(client: TestClient, tmp_path: Path) -> None:
    job_id = _seed_job()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name=f"{job_id} report.pdf",
            storage_path=str(outside),
            mime_type="application/pdf",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 403
