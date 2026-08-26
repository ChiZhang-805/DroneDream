"""Test fixtures for backend tests.

Each test gets a clean SQLite database file in a temp dir so tests are isolated
from the local dev DB and from each other.
"""

from __future__ import annotations

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

    # Reset cached settings and rebind the stable session factory.  Reloading
    # app.db/app.models would create duplicate SQLAlchemy class identities,
    # while reloading routers would leave already-collected tests holding stale
    # exception and dependency objects.
    import app.db as db_module
    import app.main as main_module
    import app.routers.autonomy as autonomy_router
    from app import config as config_module
    from app.autonomy.planner_artifact import VerifiedPlannerArtifactReceipt

    async def accept_test_planner_receipt(
        request, _authorization, expected_subject
    ) -> VerifiedPlannerArtifactReceipt:
        """Keep endpoint fixtures offline; receipt verification has dedicated tests."""

        planner = request.asset_context.planner_binding
        return VerifiedPlannerArtifactReceipt(
            owner_subject=expected_subject or "offline-test-owner",
            run_id=planner.run_id,
            provider=planner.provider,
            model=planner.model,
            artifact_sha256=planner.artifact_sha256,
        )

    monkeypatch.setattr(
        autonomy_router,
        "verify_planner_artifact_binding",
        accept_test_planner_receipt,
    )

    config_module.get_settings.cache_clear()
    database_url = f"sqlite:///{db_path}"
    db_module.rebind_database_for_testing(database_url)
    db_module.init_db()

    with TestClient(main_module.create_app()) as c:
        yield c

    config_module.get_settings.cache_clear()
