"""Test fixtures for backend tests.

Each test gets a clean SQLite database file in a temp dir so tests are isolated
from the local dev DB and from each other.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path / "real_artifacts"))
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path / "mock_artifacts"))

    # Reset cached settings and re-import modules so the new env takes effect.
    from app import config as config_module

    config_module.get_settings.cache_clear()

    import app.db as db_module

    importlib.reload(db_module)

    import app.models as models_module

    importlib.reload(models_module)

    # Reload services so they import the freshly reloaded models/db.
    import app.services.jobs as jobs_service_module

    importlib.reload(jobs_service_module)

    import app.routers.artifacts as artifacts_router_module
    import app.routers.batches as batches_router_module
    import app.routers.jobs as jobs_router_module
    import app.routers.trials as trials_router_module

    importlib.reload(artifacts_router_module)
    importlib.reload(batches_router_module)
    importlib.reload(jobs_router_module)
    importlib.reload(trials_router_module)

    import app.main as main_module

    importlib.reload(main_module)

    with TestClient(main_module.app) as c:
        yield c

    # Cleanup
    config_module.get_settings.cache_clear()
    if "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]
