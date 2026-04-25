from __future__ import annotations

from app.config import get_settings


def test_default_real_simulator_artifact_root_matches_cli_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REAL_SIMULATOR_ARTIFACT_ROOT", raising=False)
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.real_simulator_artifact_root == "./artifacts"
    assert settings.real_artifact_root_path == (tmp_path / "artifacts").resolve()
    assert settings.real_artifact_root_path in settings.allowed_artifact_roots

    get_settings.cache_clear()
