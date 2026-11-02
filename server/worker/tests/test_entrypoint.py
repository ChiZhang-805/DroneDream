"""Entrypoint-only regression: no database, worker loop or simulator is started."""

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock


def test_startup_preserves_runner_arguments_without_logging_database_url(monkeypatch, caplog):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root))
    runner = ModuleType("app.orchestration.runner")
    runner.run_forever = Mock(return_value=7)
    monkeypatch.setitem(sys.modules, runner.__name__, runner)
    spec = importlib.util.spec_from_file_location("worker_entrypoint_under_test",
                                                 root / "drone_dream_worker/main.py")
    assert spec and spec.loader
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)
    # Fake credentials exercise both common DSN leak locations; not a real account.
    settings = SimpleNamespace(worker_log_level="info", worker_poll_interval_seconds=0.5,
        database_url="postgresql://fixture:fake-password@invalid/db?token=fake-query-secret")
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    with caplog.at_level(logging.INFO, logger="drone_dream.worker"):
        assert entrypoint.run(max_iterations=2) == 7
    runner.run_forever.assert_called_once_with(poll_interval_seconds=0.5, max_iterations=2)
    assert "starting" in caplog.text
    assert settings.database_url not in caplog.text
    assert "fake-password" not in caplog.text
    assert "fake-query-secret" not in caplog.text
