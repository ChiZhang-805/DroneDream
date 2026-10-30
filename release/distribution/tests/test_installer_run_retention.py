import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "prune_installer_runs", ROOT / "apps/desktop/scripts/prune-installer-runs.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run(identity, number, status="completed", workflow=10):
    return dict(id=identity, run_number=number, status=status, workflow_id=workflow)


def test_retains_current_newer_and_active_runs():
    retained = run(500, 5, "in_progress")
    older_success = run(400, 4)
    older_failure = run(300, 3)
    runs = [
        retained, older_success, older_failure,
        run(600, 6), run(200, 2, "in_progress"), run(100, 1, "queued"),
        run(50, 1, workflow=20),
    ]
    assert MODULE.obsolete_runs(runs, retained) == [older_success, older_failure]


def test_cleanup_waits_for_build_and_publication():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/desktop-installer.yml").read_text())
    job = workflow["jobs"]["retain-latest-run"]
    assert set(job["needs"]) == {"native-core", "windows-nsis", "publish-release"}
    assert "needs.windows-nsis.result == 'success'" in job["if"]
    assert "needs.publish-release.result == 'success'" in job["if"]
    assert "needs.publish-release.result == 'skipped'" in job["if"]
    assert job["permissions"] == {"actions": "write", "contents": "read"}
