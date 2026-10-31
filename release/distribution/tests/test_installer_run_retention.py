import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "prune_installer_runs", ROOT / "apps/desktop/scripts/prune-installer-runs.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run(identity, number, status="completed", workflow=10, conclusion="success", **extra):
    return dict(id=identity, run_number=number, status=status, workflow_id=workflow,
                conclusion=conclusion, run_attempt=1, updated_at="unchanged", **extra)


class RetentionTests(unittest.TestCase):
    workflows = [dict(id=10, state="active"), dict(id=20, state="active"), dict(id=30, state="deleted")]

    def keep(self, runs, releases=(), policy=None):
        return set(MODULE.retention_reasons(runs, self.workflows, releases, policy or {}))

    def test_success_per_workflow_and_active_runs(self):
        runs = [run(1, 1), run(2, 2), run(3, 3, "in_progress"), run(4, 4, "queued"),
                run(5, 1, workflow=20), run(6, 1, workflow=30)]
        self.assertEqual(self.keep(runs), {2, 3, 4, 5})

    def test_only_latest_unresolved_failure(self):
        runs = [run(1, 1, conclusion="failure"), run(2, 2), run(3, 3, conclusion="failure"),
                run(4, 4, conclusion="timed_out"), run(5, 5, conclusion="cancelled")]
        self.assertEqual(self.keep(runs), {2, 4})
        self.assertEqual(self.keep(runs + [run(6, 6)]), {6})
        self.assertEqual(self.keep([run(7, 1, conclusion="failure")]), {7})

    def test_review_survives_new_success(self):
        self.assertEqual(self.keep([run(1, 1), run(2, 2)], policy={"review_runs": {"1": "review"}}), {1, 2})

    def test_release_commit_tag_and_legacy_associations(self):
        releases = [dict(tag_name="build-10", commit_sha="sha")]
        runs = [run(1, 1, head_sha="sha"), run(2, 2, head_branch="build-10"),
                run(3, 3, display_title="Sign - build-10"), run(4, 4),
                run(5, 5, display_title="Sign - build-100"), run(6, 6)]
        policy = {"legacy_release_runs": {"build-10": [4]}}
        self.assertEqual(self.keep(runs, releases, policy), {1, 2, 3, 4, 6})
        self.assertEqual(self.keep(runs, [], policy), {6})

    def test_mutable_channel_target_does_not_pin_old_build(self):
        self.assertEqual(self.keep([run(1, 1, head_sha="old"), run(2, 2)],
                                  [dict(tag_name="desktop-sim-channel", commit_sha="old")]), {2})

    def test_rerun_is_not_deleted(self):
        original = run(1, 1)
        self.assertTrue(MODULE.unchanged_completed(original, original))
        for changes in ({"status": "queued"}, {"run_attempt": 2}, {"updated_at": "new"}):
            self.assertFalse(MODULE.unchanged_completed(original, dict(original, **changes)))

    def test_cleanup_uses_default_branch_and_does_not_trigger_itself(self):
        workflow = (ROOT / ".github/workflows/actions-retention.yml").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", workflow)
        self.assertNotIn("- 清理旧记录", workflow)
        self.assertNotIn("retain-latest-run:", (ROOT / ".github/workflows/desktop-installer.yml").read_text(encoding="utf-8"))
