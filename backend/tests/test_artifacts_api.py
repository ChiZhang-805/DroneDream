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


def test_download_forbidden_path_traversal(client: TestClient, tmp_path: Path) -> None:
    job_id = _seed_job()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    traversed = tmp_path / "real_artifacts" / "jobs" / job_id / ".." / ".." / "outside.txt"
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="worker_log",
            display_name="outside.txt",
            storage_path=str(traversed),
            mime_type="text/plain",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 403


def test_download_s3_artifact_via_storage_backend(client: TestClient, monkeypatch) -> None:
    job_id = _seed_job()
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            display_name="report.json",
            storage_path="s3://bucket/jobs/job/report.json",
            mime_type="application/json",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    class _FakeStorage:
        def open_for_download(self, storage_uri: str):
            assert storage_uri.startswith("s3://")
            from app.storage.base import StorageDownload

            return StorageDownload(
                content=b'{"ok":true}',
                content_type="application/json",
                filename="report.json",
            )

    monkeypatch.setattr("app.routers.artifacts.get_artifact_storage", lambda: _FakeStorage())

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 200
    assert resp.text == '{"ok":true}'


def test_s3_storage_config_missing_returns_explicit_error(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    job_id = _seed_job()
    path = tmp_path / "x.txt"
    path.write_text("x", encoding="utf-8")
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            display_name="report.json",
            storage_path="s3://bucket/jobs/job/report.json",
            mime_type="application/json",
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "CONFIGURATION_ERROR"
