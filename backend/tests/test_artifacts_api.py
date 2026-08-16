from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app import db, models
from app.storage.integrity import bind_artifact_integrity


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
    assert f'filename="{job_id} report.pdf"' in content_disposition
    assert resp.headers["x-dronedream-report-tier"] == "free"
    assert resp.headers["x-dronedream-report-watermark"] == "applied"
    page_count = re.search(rb"/Type /Pages /Kids \[.*?\] /Count (\d+)", resp.content)
    assert page_count is not None
    assert resp.content.count(b"% DD-FREE-REPORT-WATERMARK-V1") == int(page_count.group(1))


@pytest.mark.parametrize("paid_tier", ["plus", "pro"])
def test_paid_report_export_has_no_watermark(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paid_tier: str,
) -> None:
    job_id = _seed_job()
    root = tmp_path / "real_artifacts"
    path = root / "jobs" / job_id / "reports" / f"{job_id} report.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical_pdf = b"%PDF-1.4\n%canonical-paid-report\n"
    path.write_bytes(canonical_pdf)

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
        artifact_id = artifact.id

    monkeypatch.setattr(
        "app.routers.artifacts.resolve_report_export_tier",
        lambda **kwargs: paid_tier,
    )
    response = client.get(
        f"/api/v1/artifacts/{artifact_id}/download?tier=free",
    )

    assert response.status_code == 200
    assert response.content == canonical_pdf
    assert b"DD-FREE-REPORT-WATERMARK" not in response.content
    assert response.headers["x-dronedream-report-tier"] == paid_tier
    assert response.headers["x-dronedream-report-watermark"] == "none"


def test_client_tier_parameter_cannot_remove_free_report_watermark(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_job()
    root = tmp_path / "real_artifacts"
    path = root / "jobs" / job_id / "reports" / f"{job_id} report.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%canonical-free-report\n")

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name=f"{job_id} report.pdf",
            storage_path=str(path),
            mime_type="application/pdf",
        )
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    monkeypatch.setattr(
        "app.routers.artifacts.resolve_report_export_tier",
        lambda **kwargs: "free",
    )
    response = client.get(
        f"/api/v1/artifacts/{artifact_id}/download?tier=pro",
    )

    assert response.status_code == 200
    assert response.headers["x-dronedream-report-tier"] == "free"
    assert response.headers["x-dronedream-report-watermark"] == "applied"
    assert b"% DD-FREE-REPORT-WATERMARK-V1" in response.content


def test_download_repro_manifest_artifact_success(client: TestClient, tmp_path: Path) -> None:
    job_id = _seed_job()
    root = tmp_path / "real_artifacts"
    path = root / "jobs" / job_id / "job_artifacts" / "repro_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"ok":true}\n')

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="repro_manifest_json",
            display_name="Reproducibility manifest",
            storage_path=str(path),
            mime_type="application/json",
            file_size_bytes=path.stat().st_size,
        )
        session.add(artifact)
        session.commit()
        art_id = artifact.id

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.text == '{"ok":true}\n'


def test_digest_bound_download_rejects_byte_tampering(
    client: TestClient,
    tmp_path: Path,
) -> None:
    job_id = _seed_job()
    path = tmp_path / "real_artifacts" / "jobs" / job_id / "job_artifacts" / "verified.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"verified":true}\n')

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            display_name="verified.json",
            storage_path=str(path),
            mime_type="application/json",
        )
        session.add(artifact)
        receipt = bind_artifact_integrity(
            session,
            artifact=artifact,
            content=path,
        )
        session.commit()
        artifact_id = artifact.id
        assert receipt.evidence_id.startswith("sha256:")

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert response.status_code == 200
    assert response.content == b'{"verified":true}\n'

    path.write_bytes(b'{"verified":false}\n')
    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ARTIFACT_INTEGRITY_INVALID"


def test_digest_bound_local_download_serves_verified_snapshot(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_job()
    path = tmp_path / "real_artifacts" / "jobs" / job_id / "verified.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    verified_bytes = b"verified-before-response"
    replacement_bytes = b"replaced-after-verification"
    path.write_bytes(verified_bytes)

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            display_name="verified.bin",
            storage_path=str(path),
            mime_type="application/octet-stream",
        )
        session.add(artifact)
        bind_artifact_integrity(session, artifact=artifact, content=path)
        session.commit()
        artifact_id = artifact.id

    from app.routers import artifacts as artifacts_router

    original_require = artifacts_router.require_artifact_integrity
    verified_snapshots = 0

    def replace_source_after_snapshot(artifact, **kwargs):
        nonlocal verified_snapshots
        receipt = original_require(artifact, **kwargs)
        if kwargs.get("content_digest") is not None:
            verified_snapshots += 1
            path.write_bytes(replacement_bytes)
        return receipt

    monkeypatch.setattr(
        artifacts_router,
        "require_artifact_integrity",
        replace_source_after_snapshot,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")

    assert response.status_code == 200
    assert verified_snapshots == 1
    assert path.read_bytes() == replacement_bytes
    assert response.content == verified_bytes


def test_artifact_digest_receipt_rejects_update_and_delete(
    tmp_path: Path,
) -> None:
    job_id = _seed_job()
    path = tmp_path / "real_artifacts" / "immutable.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"immutable artifact")

    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            storage_path=str(path),
        )
        session.add(artifact)
        bind_artifact_integrity(
            session,
            artifact=artifact,
            content=path,
        )
        session.commit()
        artifact_id = artifact.id

    with db.SessionLocal() as session:
        artifact = session.get(models.Artifact, artifact_id)
        assert artifact is not None
        assert artifact.digest_receipt is not None
        artifact.digest_receipt.content_sha256 = "0" * 64
        with pytest.raises(DatabaseError, match="append-only"):
            session.flush()
        session.rollback()

    with db.SessionLocal() as session:
        artifact = session.get(models.Artifact, artifact_id)
        assert artifact is not None
        assert artifact.digest_receipt is not None
        session.delete(artifact.digest_receipt)
        with pytest.raises(DatabaseError, match="append-only"):
            session.flush()


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


def test_download_unknown_owner_type_fails_closed(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "real_artifacts"
    path = root / "jobs" / "forged" / "secret.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("secret", encoding="utf-8")
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="unknown",
            owner_id="forged",
            artifact_type="worker_log",
            display_name="secret.txt",
            storage_path=str(path),
            mime_type="text/plain",
        )
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


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
        def exists(self, storage_uri: str) -> bool:
            assert storage_uri.startswith("s3://")
            return True

        def copy_to(self, storage_uri: str, destination) -> tuple[str, int]:
            assert storage_uri.startswith("s3://")
            content = b'{"ok":true}'
            destination.write(content)
            return hashlib.sha256(content).hexdigest(), len(content)

    monkeypatch.setattr("app.routers.artifacts.get_artifact_storage", lambda: _FakeStorage())

    resp = client.get(f"/api/v1/artifacts/{art_id}/download")
    assert resp.status_code == 200
    assert resp.text == '{"ok":true}'


def test_free_s3_pdf_report_never_uses_presigned_redirect(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = _seed_job()
    canonical_pdf = b"%PDF-1.4\n%canonical-unwatermarked-report\n"
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name="experiment-report.pdf",
            storage_path="s3://bucket/jobs/job/experiment-report.pdf",
            mime_type="application/pdf",
        )
        session.add(artifact)
        bind_artifact_integrity(
            session,
            artifact=artifact,
            content=canonical_pdf,
        )
        session.commit()
        artifact_id = artifact.id

    class _FakeStorage:
        presign_calls = 0
        copy_calls = 0

        def exists(self, storage_uri: str) -> bool:
            assert storage_uri.startswith("s3://")
            return True

        def presign_download(
            self,
            storage_uri: str,
            *,
            expires_seconds: int | None = None,
        ) -> str:
            _ = storage_uri, expires_seconds
            self.presign_calls += 1
            return "https://example.invalid/unwatermarked-report"

        def read_bytes(self, storage_uri: str) -> bytes:
            raise AssertionError(f"watermarked report unexpectedly buffered {storage_uri}")

        def copy_to(self, storage_uri: str, destination) -> tuple[str, int]:
            assert storage_uri.startswith("s3://")
            self.copy_calls += 1
            destination.write(canonical_pdf)
            return hashlib.sha256(canonical_pdf).hexdigest(), len(canonical_pdf)

    storage = _FakeStorage()
    real_mkstemp = tempfile.mkstemp

    def scoped_mkstemp(*, prefix: str, suffix: str) -> tuple[int, str]:
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr(
        "app.routers.artifacts.get_artifact_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "app.routers.artifacts.tempfile.mkstemp",
        scoped_mkstemp,
    )
    monkeypatch.setattr(
        "app.routers.artifacts.resolve_report_export_tier",
        lambda **kwargs: "free",
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")

    assert response.status_code == 200
    assert storage.presign_calls == 0
    assert storage.copy_calls == 1
    assert response.headers["x-dronedream-report-tier"] == "free"
    assert response.headers["x-dronedream-report-watermark"] == "applied"
    assert b"% DD-FREE-REPORT-WATERMARK-V1" in response.content
    assert b"canonical-unwatermarked-report" not in response.content
    assert list(tmp_path.glob("dronedream-artifact-*.download")) == []


def test_legacy_s3_pdf_download_is_streamed_with_a_hard_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = _seed_job()
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="pdf_report",
            display_name="legacy-report.pdf",
            storage_path="s3://bucket/jobs/job/legacy-report.pdf",
            mime_type="application/pdf",
        )
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    class _FakeStorage:
        def exists(self, _storage_uri: str) -> bool:
            return True

        def copy_to(self, _storage_uri: str, destination) -> tuple[str, int]:
            content = b"oversized"
            destination.write(content)
            return hashlib.sha256(content).hexdigest(), len(content)

    real_mkstemp = tempfile.mkstemp

    def scoped_mkstemp(*, prefix: str, suffix: str) -> tuple[int, str]:
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr(
        "app.routers.artifacts.get_artifact_storage",
        lambda: _FakeStorage(),
    )
    monkeypatch.setattr(
        "app.routers.artifacts.tempfile.mkstemp",
        scoped_mkstemp,
    )
    monkeypatch.setattr(
        "app.routers.artifacts.resolve_report_export_tier",
        lambda **_kwargs: "plus",
    )
    monkeypatch.setattr(
        "app.routers.artifacts._MAX_PDF_REPORT_BYTES",
        4,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "ARTIFACT_TOO_LARGE"
    assert list(tmp_path.glob("dronedream-artifact-*.download")) == []


def test_digest_bound_s3_download_never_redirects_and_rejects_tampering(
    client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_id = _seed_job()
    verified_bytes = b'{"verified":true}'
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="report_json",
            display_name="verified.json",
            storage_path="s3://bucket/jobs/job/verified.json",
            mime_type="application/json",
        )
        session.add(artifact)
        bind_artifact_integrity(
            session,
            artifact=artifact,
            content=verified_bytes,
        )
        session.commit()
        artifact_id = artifact.id

    class _FakeStorage:
        content = verified_bytes
        presign_calls = 0
        copy_calls = 0

        def exists(self, storage_uri: str) -> bool:
            assert storage_uri.startswith("s3://")
            return True

        def presign_download(
            self,
            storage_uri: str,
            *,
            expires_seconds: int | None = None,
        ) -> str:
            _ = storage_uri, expires_seconds
            self.presign_calls += 1
            return "https://example.invalid/unchecked"

        def read_bytes(self, storage_uri: str) -> bytes:
            raise AssertionError(f"bounded download unexpectedly buffered {storage_uri}")

        def copy_to(self, storage_uri: str, destination) -> tuple[str, int]:
            assert storage_uri.startswith("s3://")
            self.copy_calls += 1
            destination.write(self.content)
            return hashlib.sha256(self.content).hexdigest(), len(self.content)

    storage = _FakeStorage()
    real_mkstemp = tempfile.mkstemp

    def scoped_mkstemp(*, prefix: str, suffix: str) -> tuple[int, str]:
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr(
        "app.routers.artifacts.get_artifact_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "app.routers.artifacts.tempfile.mkstemp",
        scoped_mkstemp,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert response.status_code == 200
    assert response.content == verified_bytes
    assert storage.presign_calls == 0
    assert storage.copy_calls == 1
    assert list(tmp_path.glob("dronedream-artifact-*.download")) == []

    storage.content = b'{"verified":false}'
    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ARTIFACT_INTEGRITY_INVALID"
    assert storage.presign_calls == 0
    assert storage.copy_calls == 2
    assert list(tmp_path.glob("dronedream-artifact-*.download")) == []


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
