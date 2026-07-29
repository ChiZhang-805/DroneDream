"""Test fixtures for backend tests.

Each test gets a clean SQLite database file in a temp dir so tests are isolated
from the local dev DB and from each other.
"""

from __future__ import annotations

import importlib
import os
import sys
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

    models_was_loaded = "app.models" in sys.modules

    import app.db as db_module

    importlib.reload(db_module)

    if models_was_loaded:
        importlib.reload(sys.modules["app.models"])
    else:
        importlib.import_module("app.models")

    # Authentication captures both get_db and get_settings at import time.
    # Reload it after the database module so fixture order cannot leave a
    # TestClient bound to an earlier test's engine or cached Settings function.
    import app.auth as auth_module

    importlib.reload(auth_module)

    # Reload services so they import the freshly reloaded models/db.
    import app.services.jobs as jobs_service_module

    importlib.reload(jobs_service_module)

    import app.routers.artifacts as artifacts_router_module
    import app.routers.batches as batches_router_module
    import app.routers.jobs as jobs_router_module
    import app.routers.preferences as preferences_router_module
    import app.routers.trials as trials_router_module

    importlib.reload(artifacts_router_module)
    importlib.reload(batches_router_module)
    importlib.reload(jobs_router_module)
    importlib.reload(preferences_router_module)
    importlib.reload(trials_router_module)

    import app.main as main_module

    importlib.reload(main_module)

    with TestClient(main_module.app) as c:
        yield c

    # Cleanup
    config_module.get_settings.cache_clear()
    if "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]
